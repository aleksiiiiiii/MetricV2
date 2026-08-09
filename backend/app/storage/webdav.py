"""Client WebDAV minimal pour Nextcloud (`STO-01`, `STO-08`).

Cinq verbes suffisent — GET, PUT, DELETE, MKCOL, PROPFIND — mais il faut beaucoup de
contrôle sur ce qui les entoure : réessais sur erreur transitoire, respect de
`Retry-After`, verrous Nextcloud, pool de connexions limité et maintenu en keep-alive.
D'où un wrapper maison plutôt qu'une bibliothèque WebDAV généraliste.

Deux choix structurants :

* **ETag de bout en bout.** Chaque lecture rapporte l'ETag du fichier, chaque écriture
  peut exiger `If-Match`. C'est ce qui rend la garde anti-conflit (`STO-05`) réellement
  atomique côté serveur, et non fondée sur une comparaison faite chez nous.
* **`sleep` injectable.** Les réessais sont testables sans attendre : la batterie de
  tests vérifie les délais calculés sans les subir.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from urllib.parse import quote
from xml.etree import ElementTree

import httpx2

from app.storage.errors import (
    StorageAuthFailedError,
    StorageConflictError,
    StorageError,
    StorageLockedError,
    StorageNotFoundError,
    StorageUnavailableError,
)

# Statuts qui justifient un nouvel essai : saturation et pannes passagères.
# 423 est le verrou de fichier Nextcloud — fréquent quand la synchro tourne en parallèle.
RETRYABLE_STATUS = frozenset({423, 429, 500, 502, 503, 504, 507})

# Ce qui distingue, dans un 423, le verrou **tenu** du verrou passager.
#
# Nextcloud rend le même statut dans deux situations opposées. La synchro qui écrit au même
# instant relâche en quelques centaines de millisecondes — réessayer marche, et c'est ce que
# fait la boucle. Un verrou d'application, lui, est posé par l'éditeur Text quand on ouvre
# le fichier dans l'interface web, et il **tient jusqu'à ce que la session se ferme** : un
# `intake_log.csv` ouvert un vendredi soir bloquait encore l'écriture le dimanche.
#
# Sabre le signale par cette précondition, qui veut dire « il fallait présenter un jeton de
# verrou ». Un client qui n'en a pas ne l'obtiendra pas en insistant : trois secondes de
# réessais partent en pure perte, et le message conseille ensuite de recommencer.
HELD_LOCK_MARKER = b"lock-token-submitted"

# Erreurs de transport passagères.
RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
    httpx2.ConnectError,
    httpx2.ConnectTimeout,
    httpx2.ReadTimeout,
    httpx2.WriteTimeout,
    httpx2.PoolTimeout,
    httpx2.RemoteProtocolError,
    httpx2.NetworkError,
)

SleepFn = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Fetched:
    """Résultat d'une lecture conditionnelle.

    `not_modified` distingue « le serveur confirme que rien n'a changé » (304, contenu
    absent, on garde le cache) de « voici le contenu ».
    """

    content: bytes | None
    etag: str | None
    not_modified: bool = False


class WebDavClient:
    """Accès WebDAV à un dossier Nextcloud."""

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        root: str = "",
        max_attempts: int = 4,
        backoff_base: float = 0.5,
        backoff_cap: float = 8.0,
        sleep: SleepFn | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._root = root.strip("/")
        self._max_attempts = max(1, max_attempts)
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._sleep: SleepFn = sleep or asyncio.sleep

        self._client = httpx2.AsyncClient(
            base_url=base_url.rstrip("/"),
            auth=httpx2.BasicAuth(username, password),
            # Connexions limitées et maintenues en keep-alive (`STO-08`) : Nextcloud
            # n'apprécie pas qu'on ouvre dix sockets pour dix fichiers.
            limits=httpx2.Limits(max_connections=8, max_keepalive_connections=4),
            timeout=httpx2.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0),
            follow_redirects=True,
            # `None` = transport par défaut ; les tests injectent le double ASGI.
            transport=transport,
        )

    # ── Cycle de vie ──────────────────────────────────

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> WebDavClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ── Chemins ───────────────────────────────────────

    def url_for(self, path: str) -> str:
        """Chemin absolu d'une ressource, sous la racine de données configurée."""
        segments = [s for s in (self._root, *path.strip("/").split("/")) if s]
        return "/" + "/".join(quote(s) for s in segments)

    # ── Verbes ────────────────────────────────────────

    async def get(self, path: str, *, etag: str | None = None) -> Fetched:
        """Lit un fichier. Avec `etag`, lecture conditionnelle (`If-None-Match`).

        Un 304 revient sous forme de `Fetched(not_modified=True)` : c'est ce qui permet
        au cache de rester valide sans retransférer le fichier (`STO-06`).
        """
        headers = {"If-None-Match": etag} if etag else None
        response = await self._request("GET", path, headers=headers, allow_status={304})

        if response.status_code == 304:
            return Fetched(content=None, etag=etag, not_modified=True)
        etag_out: str | None = response.headers.get("etag")
        return Fetched(content=response.content, etag=etag_out)

    async def put(
        self,
        path: str,
        content: bytes,
        *,
        if_match: str | None = None,
        if_none_match: str | None = None,
        content_type: str = "text/csv; charset=utf-8",
    ) -> str | None:
        """Écrit un fichier et rend son nouvel ETag s'il est annoncé.

        `if_match` refuse l'écriture si le fichier a changé depuis la lecture ;
        `if_none_match="*"` refuse d'écraser un fichier existant. Les deux se traduisent
        en `409` métier (`STO-05`).
        """
        headers = {"Content-Type": content_type}
        if if_match:
            headers["If-Match"] = if_match
        if if_none_match:
            headers["If-None-Match"] = if_none_match

        response = await self._request("PUT", path, content=content, headers=headers)
        etag: str | None = response.headers.get("etag")
        return etag

    async def delete(self, path: str, *, missing_ok: bool = False) -> None:
        try:
            await self._request("DELETE", path)
        except StorageNotFoundError:
            if not missing_ok:
                raise

    async def mkcol(self, path: str) -> None:
        """Crée un dossier. Idempotent : un dossier déjà présent n'est pas une erreur.

        Nextcloud répond 405 quand la collection existe déjà.
        """
        await self._request("MKCOL", path, allow_status={405})

    async def ensure_collection(self, path: str) -> None:
        """Crée un dossier et tous ses parents (`STO-07`).

        Remonter la chaîne segment par segment est le seul moyen portable : WebDAV n'a
        pas de MKCOL récursif.

        Le dossier racine des données est créé en premier : au tout premier démarrage il
        n'existe pas, et un MKCOL sur `racine/sous-dossier` échouerait alors en 409 avec
        un message incompréhensible. On ne le fait que si une racine est configurée —
        sinon ce serait un MKCOL sur la racine WebDAV du compte.
        """
        if self._root:
            await self.mkcol("")

        segments = [s for s in path.strip("/").split("/") if s]
        for depth in range(1, len(segments) + 1):
            await self.mkcol("/".join(segments[:depth]))

    async def exists(self, path: str) -> bool:
        try:
            await self._request("PROPFIND", path, headers={"Depth": "0"})
        except StorageNotFoundError:
            return False
        return True

    async def list_collection(self, path: str) -> list[str]:
        """Noms des enfants directs d'un dossier."""
        response = await self._request("PROPFIND", path, headers={"Depth": "1"})
        base = self.url_for(path).rstrip("/")

        names: list[str] = []
        try:
            tree = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise StorageError(detail=f"PROPFIND illisible sur {path}") from exc

        for href in tree.iter("{DAV:}href"):
            value = (href.text or "").rstrip("/")
            if not value or value.rstrip("/") == base:
                continue
            names.append(value.rsplit("/", 1)[-1])
        return names

    # ── Moteur de requête et réessais ─────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        allow_status: Iterable[int] = (),
    ) -> httpx2.Response:
        """Envoie une requête, en réessayant ce qui vaut la peine de l'être."""
        url = self.url_for(path)
        allowed = set(allow_status)
        last_error: Exception | None = None
        attempted_delete = False

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._client.request(method, url, content=content, headers=headers)
            except RETRYABLE_ERRORS as exc:
                last_error = exc
                if attempt == self._max_attempts:
                    break
                await self._sleep(self._backoff_delay(attempt))
                continue
            except httpx2.HTTPError as exc:  # pragma: no cover - transport exotique
                raise StorageUnavailableError(detail=str(exc)) from exc

            status = response.status_code

            if status < 300 or status in allowed:
                return response

            # Un DELETE rejoué tombe sur un 404 : la première tentative avait abouti.
            if method == "DELETE" and status == 404 and attempted_delete:
                return response

            if status == 423 and HELD_LOCK_MARKER in response.content:
                raise StorageLockedError(detail=f"{method} {path} → verrou tenu")

            if status in RETRYABLE_STATUS and attempt < self._max_attempts:
                if method == "DELETE":
                    attempted_delete = True
                await self._sleep(self._retry_delay(response, attempt))
                continue

            raise self._error_for(response, method=method, path=path)

        raise StorageUnavailableError(
            detail=f"{method} {path} — {self._max_attempts} tentatives : {last_error}"
        )

    def _backoff_delay(self, attempt: int) -> float:
        """Exponentiel plafonné, avec gigue pour ne pas resynchroniser les réessais."""
        delay = min(self._backoff_base * float(2 ** (attempt - 1)), self._backoff_cap)
        return delay * (0.5 + random.random() / 2)

    def _retry_delay(self, response: httpx2.Response, attempt: int) -> float:
        """Délai avant nouvel essai, en honorant `Retry-After` s'il est fourni."""
        header = response.headers.get("retry-after")
        if header:
            seconds = self._parse_retry_after(header)
            if seconds is not None:
                # Le serveur a raison sur son propre rythme, mais on ne le laisse pas
                # nous immobiliser indéfiniment.
                return max(0.0, min(seconds, self._backoff_cap * 4))
        return self._backoff_delay(attempt)

    @staticmethod
    def _parse_retry_after(value: str) -> float | None:
        """`Retry-After` accepte un nombre de secondes ou une date HTTP."""
        value = value.strip()
        try:
            return float(value)
        except ValueError:
            pass
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return max(0.0, (when - datetime.now(tz=UTC)).total_seconds())

    @staticmethod
    def _error_for(response: httpx2.Response, *, method: str, path: str) -> StorageError:
        """Traduit un statut HTTP en erreur métier (`STO-09`)."""
        status = response.status_code
        where = f"{method} {path} → HTTP {status}"

        if status in (401, 403):
            return StorageAuthFailedError(detail=where)
        if status == 404:
            return StorageNotFoundError(detail=where)
        if status in (409, 412):
            # 412 : `If-Match` refusé, le fichier a changé.
            # 409 : parent absent — côté appelant, cela veut dire dossier à créer.
            return StorageConflictError(detail=where)
        if status == 423 and HELD_LOCK_MARKER in response.content:
            return StorageLockedError(detail=where)
        if status in RETRYABLE_STATUS:
            return StorageUnavailableError(detail=where)
        return StorageError(detail=where)
