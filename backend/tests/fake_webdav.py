"""Faux serveur WebDAV en mémoire, monté en ASGI.

Tester la couche stockage contre un vrai Nextcloud serait lent, non reproductible, et
impossible en CI. Ce double implémente ce dont le client se sert réellement — GET
conditionnel, PUT avec `If-Match`/`If-None-Match`, DELETE, MKCOL, PROPFIND — plus une
**injection de pannes** qui permet de scénariser ce qu'on ne peut pas provoquer à la
demande : un 429 avec `Retry-After`, un verrou de fichier, une coupure en cours
d'écriture, une modification concurrente depuis un autre appareil.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote
from xml.sax.saxutils import escape

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

# Une panne scénarisée : soit une réponse HTTP forcée, soit une exception de transport.
Fault = tuple[int, dict[str, str]] | Exception


@dataclass(slots=True)
class StoredFile:
    content: bytes
    etag: str


@dataclass(slots=True)
class FakeWebDav:
    """Serveur WebDAV minimal, tout en mémoire."""

    files: dict[str, StoredFile] = field(default_factory=dict)
    collections: set[str] = field(default_factory=set)
    #: Pannes à servir avant de traiter normalement. `None` laisse passer la requête.
    faults: list[Fault | None] = field(default_factory=list)
    #: Journal `(méthode, chemin)` de toutes les requêtes reçues, pannes comprises.
    requests: list[tuple[str, str]] = field(default_factory=list)
    #: Simule un serveur qui n'annonce aucun ETag : la garde anti-conflit se dégrade.
    #: Distinct d'une panne injectée, qui court-circuiterait l'écriture elle-même.
    omit_etag: bool = False
    _revision: int = 0

    # ── Manipulation depuis les tests ─────────────────

    def seed(self, path: str, content: bytes | str) -> str:
        """Place un fichier sans passer par HTTP."""
        raw = content.encode("utf-8") if isinstance(content, str) else content
        self._revision += 1
        etag = f'"rev{self._revision}"'
        self.files[path.strip("/")] = StoredFile(content=raw, etag=etag)
        return etag

    def content_of(self, path: str) -> str:
        """Contenu texte d'un fichier, BOM retiré."""
        return self.files[path.strip("/")].content.decode("utf-8-sig")

    def etag_of(self, path: str) -> str:
        return self.files[path.strip("/")].etag

    def count(self, method: str) -> int:
        return sum(1 for verb, _ in self.requests if verb == method)

    def reset_journal(self) -> None:
        self.requests.clear()

    # ── ASGI ──────────────────────────────────────────

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        assert scope["type"] == "http"

        method: str = scope["method"]
        path = unquote(scope["path"]).strip("/")
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope["headers"]
        }
        body = await self._read_body(receive)
        self.requests.append((method, path))

        if self.faults:
            fault = self.faults.pop(0)
            if isinstance(fault, Exception):
                raise fault
            if fault is not None:
                status, extra = fault
                await self._respond(send, status, headers=extra)
                return

        handler = {
            "GET": self._get,
            "HEAD": self._get,
            "PUT": self._put,
            "DELETE": self._delete,
            "MKCOL": self._mkcol,
            "PROPFIND": self._propfind,
        }.get(method)

        if handler is None:
            await self._respond(send, 405)
            return
        await handler(send, path, headers, body)

    # ── Verbes ────────────────────────────────────────

    async def _get(self, send: Send, path: str, headers: dict[str, str], _: bytes) -> None:
        stored = self.files.get(path)
        if stored is None:
            await self._respond(send, 404)
            return

        if headers.get("if-none-match") == stored.etag:
            await self._respond(send, 304, headers={"ETag": stored.etag})
            return

        await self._respond(send, 200, body=stored.content, headers=self._etag(stored.etag))

    async def _put(self, send: Send, path: str, headers: dict[str, str], body: bytes) -> None:
        stored = self.files.get(path)

        # Parent absent : Nextcloud répond 409, ce qui invite à créer la collection.
        parent = "/".join(path.split("/")[:-1])
        if parent and parent not in self.collections:
            await self._respond(send, 409)
            return

        if_match = headers.get("if-match")
        if if_match and (stored is None or stored.etag != if_match):
            await self._respond(send, 412)
            return

        if headers.get("if-none-match") == "*" and stored is not None:
            await self._respond(send, 412)
            return

        etag = self.seed(path, body)
        await self._respond(send, 201 if stored is None else 204, headers=self._etag(etag))

    async def _delete(self, send: Send, path: str, _h: dict[str, str], _b: bytes) -> None:
        if self.files.pop(path, None) is None:
            await self._respond(send, 404)
            return
        await self._respond(send, 204)

    async def _mkcol(self, send: Send, path: str, _h: dict[str, str], _b: bytes) -> None:
        if path in self.collections:
            await self._respond(send, 405)  # comportement Nextcloud
            return
        self.collections.add(path)
        await self._respond(send, 201)

    async def _propfind(self, send: Send, path: str, headers: dict[str, str], _b: bytes) -> None:
        is_collection = path in self.collections or path == ""
        if not is_collection and path not in self.files:
            await self._respond(send, 404)
            return

        hrefs = ["/" + quote(path)] if path else ["/"]
        if headers.get("depth") == "1" and is_collection:
            prefix = f"{path}/" if path else ""
            children = {
                name[len(prefix) :].split("/")[0]
                for name in (*self.files, *self.collections)
                if name.startswith(prefix) and name != path
            }
            hrefs += ["/" + quote(f"{prefix}{child}") for child in sorted(children) if child]

        entries = "".join(
            f"<d:response><d:href>{escape(href)}</d:href></d:response>" for href in hrefs
        )
        xml = f'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">{entries}</d:multistatus>'
        await self._respond(
            send, 207, body=xml.encode(), headers={"Content-Type": "application/xml"}
        )

    # ── Plomberie ─────────────────────────────────────

    def _etag(self, etag: str) -> dict[str, str]:
        return {} if self.omit_etag else {"ETag": etag}

    @staticmethod
    async def _read_body(receive: Receive) -> bytes:
        chunks: list[bytes] = []
        while True:
            message = await receive()
            chunks.append(bytes(message.get("body", b"")))
            if not message.get("more_body", False):
                break
        return b"".join(chunks)

    @staticmethod
    async def _respond(
        send: Send,
        status: int,
        *,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        raw = [
            (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()
        ]
        raw.append((b"content-length", str(len(body)).encode()))
        await send({"type": "http.response.start", "status": status, "headers": raw})
        await send({"type": "http.response.body", "body": body})
