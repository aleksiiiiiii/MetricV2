"""Faux OpenRouter en mémoire, monté en ASGI.

Même parti pris que `fake_webdav.py`, et la même raison en plus forte : un vrai appel à
OpenRouter est **non déterministe par nature**. Le même modèle, la même photo et la même
consigne rendent deux réponses différentes, le catalogue gratuit change de semaine en
semaine, et les quotas dépendent de l'heure. Une batterie de tests branchée dessus dirait
tantôt vert tantôt rouge sans qu'une ligne de code ait bougé.

Ce double sert donc **toute** la conception : ce qu'on ne peut pas provoquer à la demande
sur le vrai service se scénarise ici en trois lignes — un `429` sur les deux premiers
modèles, un JSON coupé au milieu d'un nombre, un modèle bavard qui enrobe sa réponse de
politesses, un catalogue qui ne contient aucun modèle vision.

Le journal des appels permet de vérifier ce qui compte autant que la réponse : **quels**
modèles ont été essayés, dans quel ordre, et si l'image a bien été envoyée.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass, field
from typing import Any

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Reply:
    """Une réponse scénarisée à un appel de complétion."""

    status: int = 200
    #: Texte du modèle, tel qu'il arrive dans `choices[0].message.content`.
    content: str | None = None
    #: Corps complet, quand le scénario porte sur la **forme** de la réponse.
    body: dict[str, Any] | None = None

    @staticmethod
    def says(content: str) -> Reply:
        """Le modèle répond ce texte."""
        return Reply(content=content)

    @staticmethod
    def quota() -> Reply:
        """Le modèle est saturé — le cas que `IA-03` doit distinguer de tout le reste."""
        return Reply(status=429, body={"error": {"code": 429, "message": "rate limit exceeded"}})

    @staticmethod
    def quota_in_200() -> Reply:
        """Saturation annoncée dans un `200`. OpenRouter le fait quand le routage a
        réussi mais que le fournisseur en aval a refusé."""
        return Reply(body={"error": {"code": 429, "message": "Rate limit exceeded"}})

    @staticmethod
    def broken(status: int = 500) -> Reply:
        """Le modèle est en panne."""
        return Reply(status=status, body={"error": {"message": "upstream error"}})

    @staticmethod
    def mute() -> Reply:
        """Réponse bien formée, contenu vide : le monologue a mangé les jetons."""
        return Reply(body={"choices": [{"message": {"content": ""}}]})


@dataclass(slots=True)
class Call:
    """Un appel reçu, tel que la cascade l'a émis."""

    model: str
    #: Vrai si une image accompagnait la consigne (`IA-04`, `IA-06`).
    with_image: bool
    image_url: str | None


def free_model(
    identifier: str,
    *,
    vision: bool = True,
    context: int = 128000,
    free: bool = True,
) -> dict[str, Any]:
    """Une entrée de catalogue, à la forme publiée par OpenRouter."""
    price = "0" if free else "0.0000004"
    return {
        "id": identifier,
        "name": identifier.split("/")[-1],
        "context_length": context,
        "architecture": {
            "input_modalities": ["text", "image"] if vision else ["text"],
            "output_modalities": ["text"],
        },
        "pricing": {"prompt": price, "completion": price},
    }


@dataclass(slots=True)
class FakeOpenRouter:
    """Service minimal : le catalogue et la complétion, rien d'autre."""

    #: Modèles servis par `GET /models`.
    models: list[dict[str, Any]] = field(default_factory=list)
    #: Réponses à servir, dans l'ordre. Épuisée, la file rend `replies_exhausted`.
    replies: list[Reply] = field(default_factory=list)
    #: Panne du catalogue lui-même, pour vérifier qu'elle ne fait pas tomber l'écran.
    models_status: int = 200
    #: Journal des complétions reçues.
    calls: list[Call] = field(default_factory=list)
    #: Nombre d'appels au catalogue — c'est ce qui prouve la mémorisation d'une heure.
    models_calls: int = 0
    #: Réponse servie quand la file est vide : un modèle qui n'avait rien à dire.
    replies_exhausted: Reply = field(default_factory=Reply.mute)

    def say(self, *contents: str) -> None:
        """Scénarise des réponses textuelles, dans l'ordre."""
        self.replies.extend(Reply.says(content) for content in contents)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope["path"])
        body = await _read_body(receive)

        if path.endswith("/models"):
            self.models_calls += 1
            if self.models_status >= 400:
                await _respond(send, self.models_status, {"error": {"message": "nope"}})
                return
            await _respond(send, 200, {"data": self.models})
            return

        await self._complete(send, body)

    async def _complete(self, send: Send, body: bytes) -> None:
        request = json.loads(body or b"{}")
        model = str(request.get("model", ""))
        image_url = _image_of(request)
        self.calls.append(Call(model=model, with_image=image_url is not None, image_url=image_url))

        reply = self.replies.pop(0) if self.replies else self.replies_exhausted
        payload = reply.body
        if payload is None:
            payload = {"choices": [{"message": {"content": reply.content or ""}}]}
        await _respond(send, reply.status, payload)


def _image_of(request: dict[str, Any]) -> str | None:
    """Retrouve l'image d'une requête, à la forme des messages OpenAI."""
    for message in request.get("messages", []):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                url = part.get("image_url", {}).get("url")
                if isinstance(url, str):
                    return url
    return None


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        chunks.append(bytes(message.get("body", b"")))
        if not message.get("more_body", False):
            return b"".join(chunks)


async def _respond(send: Send, status: int, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": raw})
