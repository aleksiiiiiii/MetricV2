"""Plafond de taille des requêtes, et le refus lisible qui va avec.

**Le symptôme** : en mode photo, « Estimer les macros » rendait un `413 Payload Too Large`
brut. Le client décide sur `error.code` et un refus de cette forme n'en porte aucun —
l'écran affichait donc un échec sans phrase.

Trois choses valent d'être nommées ici.

**Le refus vient probablement d'ailleurs.** Starlette borne les parties *non-fichier* d'un
formulaire multipart à 1 Mo, mais **pas** les fichiers : le corps d'une photo passe donc
son analyseur sans limite. Un Nginx Proxy Manager, lui, plafonne à 1 Mo par défaut
(`client_max_body_size`), et c'est la pièce en place en production (`OPS-01`). D'où deux
correctifs qui ne se remplacent pas : celui-ci, et la ligne de configuration du proxy
documentée dans `docs/deploiement.md`.

**La garde lit `Content-Length`, elle ne lit pas le corps.** Refuser après avoir tout
absorbé ferait payer au processus la mémoire d'un contenu qu'on rejette de toute façon.
Une requête sans `Content-Length` — en `chunked` — n'est pas refusée d'office : elle passe
et ce sont les bornes du domaine qui tranchent, faute de quoi tout client qui découpe son
envoi serait rejeté à tort.

**Le plafond est plus haut que celui des photos, et c'est voulu.** `photos.py` accepte
12 Mo d'image ; l'encodage multipart, les autres champs et les en-têtes s'ajoutent par
dessus. Un plafond de transport identique refuserait des images qui tiennent dans la
limite métier, et le message parlerait alors d'une taille que l'utilisateur a respectée.
"""

from __future__ import annotations

import json
import logging

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.exceptions import PayloadTooLargeError

logger = logging.getLogger("metric.limits")

#: 16 Mo. Les 12 Mo d'une photo (`nutrition/photos.py`), plus la marge de l'encodage
#: multipart et des champs qui l'accompagnent.
MAX_REQUEST_BYTES = 16 * 1024 * 1024


class RequestSizeLimit:
    """Refuse un corps annoncé trop gros, avant de le lire.

    Écrit en pur ASGI et non en `BaseHTTPMiddleware` : ce dernier construit une `Request`
    et branche un flux de réponse pour **chaque** appel, ce qu'un simple regard sur un
    en-tête ne justifie pas.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int = MAX_REQUEST_BYTES) -> None:
        self._app = app
        self._max = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        declared = _content_length(scope)
        if declared is None or declared <= self._max:
            await self._app(scope, receive, send)
            return

        await _refuse(send, declared, self._max)


def _content_length(scope: Scope) -> int | None:
    """Taille annoncée, ou `None` si l'en-tête est absent ou illisible."""
    for name, value in scope.get("headers", []):
        if name.lower() != b"content-length":
            continue
        try:
            return int(value)
        except ValueError:
            return None
    return None


async def _refuse(send: Send, declared: int, limit: int) -> None:
    """Rend le refus dans la forme de toutes les autres erreurs : `{code, message}`.

    Écrit ici plutôt que délégué au gestionnaire d'erreurs : une exception levée dans un
    middleware ASGI ne traverse pas les gestionnaires enregistrés sur l'application, qui
    vivent en dessous.
    """
    logger.warning("corps refusé : content-length=%d > %d", declared, limit)

    error = PayloadTooLargeError()
    body = json.dumps({"code": error.code, "message": error.message}).encode("utf-8")

    await send(
        {
            "type": "http.response.start",
            "status": error.status_code,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
