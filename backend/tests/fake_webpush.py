"""Faux service push en mémoire, monté en ASGI (`L15-06`).

Même parti pris que `fake_webdav.py` et `fake_openrouter.py`, et la même raison
qu'OpenRouter en plus forte : **aucun envoi réel dans `make check`**. Un vrai service push
demanderait un navigateur enregistré, un contexte HTTPS, et rendrait la batterie dépendante
de Firebase — donc du réseau, donc non déterministe.

Ce double sert surtout à provoquer ce qu'on ne sait pas obtenir à la demande sur le vrai
service. Deux scénarios comptent, et ils demandent des conduites opposées :

* **`410 Gone`** — l'abonnement a été révoqué. Le navigateur a été réinstallé, les données
  du site effacées, l'autorisation retirée. La ligne doit être **retirée du fichier**,
  sinon on la retenterait à chaque rappel, pour toujours.
* **`503` ou une coupure réseau** — le service est en panne. La ligne doit être
  **conservée** : réessayer au prochain créneau a un sens.

Confondre les deux fait soit accumuler des abonnements morts, soit désabonner quelqu'un
parce que le Wi-Fi a hoqueté. C'est exactement ce que la batterie vérifie.

Le journal des envois permet de contrôler ce qui compte autant que le statut : **quel**
appareil a reçu quoi, et combien de fois.
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
class Delivery:
    """Un envoi reçu par le double."""

    path: str
    #: En-têtes de la requête, en minuscules. `authorization` porte le jeton VAPID.
    headers: dict[str, str]
    #: Corps chiffré. Le double **ne le déchiffre pas** — il n'a pas la clé privée de
    #: l'appareil, et c'est précisément la preuve que le chiffrement a bien eu lieu.
    body: bytes

    @property
    def encrypted(self) -> bool:
        """Vrai si le corps est bien du `aes128gcm` et non du JSON en clair.

        Le contrôle qui compte : une régression qui enverrait la charge utile telle quelle
        ferait passer les notifications par un service tiers **en clair**, et rien à
        l'écran ne le dirait.
        """
        if self.headers.get("content-encoding") != "aes128gcm":
            return False
        try:
            json.loads(self.body)
        except (UnicodeDecodeError, ValueError):
            return True
        return False


@dataclass
class FakeWebPush:
    """Service push scénarisable.

    Par défaut, tout envoi réussit avec un `201` — ce que rendent les vrais services.
    """

    #: Statut à rendre, par chemin d'`endpoint`. Le reste reçoit `default_status`.
    statuses: dict[str, int] = field(default_factory=dict)
    default_status: int = 201
    #: Journal des envois, dans l'ordre.
    deliveries: list[Delivery] = field(default_factory=list)

    # ── Scénarios ─────────────────────────────────────

    def revoke(self, endpoint: str) -> None:
        """L'abonnement n'existe plus : le service répondra `410`."""
        self.statuses[_path(endpoint)] = 410

    def break_down(self, endpoint: str, status: int = 503) -> None:
        """Le service est en panne pour cet appareil — la ligne doit survivre."""
        self.statuses[_path(endpoint)] = status

    # ── Lectures ──────────────────────────────────────

    def sent_to(self, endpoint: str) -> list[Delivery]:
        return [d for d in self.deliveries if d.path == _path(endpoint)]

    @property
    def count(self) -> int:
        return len(self.deliveries)

    # ── ASGI ──────────────────────────────────────────

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        assert scope["type"] == "http"

        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        path = scope["path"]
        self.deliveries.append(Delivery(path=path, headers=headers, body=body))

        status = self.statuses.get(path, self.default_status)
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send({"type": "http.response.body", "body": b""})


def _path(endpoint: str) -> str:
    """Chemin d'un `endpoint`, tel que l'ASGI le voit."""
    without_scheme = endpoint.split("://", 1)[-1]
    slash = without_scheme.find("/")
    return without_scheme[slash:] if slash >= 0 else "/"


__all__ = ["Delivery", "FakeWebPush"]
