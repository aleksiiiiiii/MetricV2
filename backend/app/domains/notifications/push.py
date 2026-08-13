"""Transport Web Push (`NOT-01`).

C'est le seul module du projet qui sait ce qu'est un chiffrement `aes128gcm`, et il n'en
écrit pas une ligne.

── Pourquoi une dépendance ici, alors que le projet les évite ────────────────

Le dépôt pilote Chrome en CDP sans Playwright, parle WebSocket sans `ws`, et écrit son
propre client WebDAV. Cette économie a une raison — cinq verbes et beaucoup de contrôle —
et elle ne s'applique pas ici : `aes128gcm` et l'échange ECDH de la RFC 8291 ne sont pas un
endroit où l'artisanat se justifie. Une erreur d'implémentation n'y produit pas un bogue
visible mais un chiffrement plus faible qu'annoncé, ou des notifications qui n'arrivent
jamais sans qu'on sache dire pourquoi.

**`pywebpush` chiffre, `py_vapid` signe.** Ce sont les deux bibliothèques de référence.

── Mais le transport reste le nôtre ──────────────────────────────────────────

`pywebpush.webpush()` enverrait avec `requests`, en synchrone, au milieu d'une application
entièrement asynchrone : un envoi bloquerait la boucle d'événements pendant tout un
aller-retour réseau. On n'appelle donc que `WebPusher.encode`, qui **ne fait aucune I/O**,
et l'envoi passe par `httpx2` comme tout le reste du projet.

Bénéfice secondaire, et il compte pour `L15-06` : le transport étant injectable comme celui
du client OpenRouter, la batterie scénarise un abonnement expiré sans détourner un module
tiers ni ouvrir une socket.
"""

from __future__ import annotations

import json
import time
from types import TracebackType

import httpx2
from py_vapid import Vapid02
from pywebpush import WebPusher

#: Un service push répond en une seconde ou pas du tout. Le délai est court **par
#: conception** : l'ordonnanceur envoie en série, et un service injoignable ne doit pas
#: retarder les rappels des autres appareils.
TIMEOUT = 10.0

#: Durée de validité de l'en-tête d'identification, en secondes. La RFC 8292 plafonne à
#: 24 h ; douze heures laissent de la marge à une horloge serveur légèrement décalée sans
#: rendre un en-tête intercepté réutilisable une journée entière.
JWT_TTL = 12 * 3600

#: Combien de temps le service push garde le message si l'appareil est hors ligne.
#:
#: Quatre heures : un rappel de suppléments de 20 h a du sens quand le téléphone se
#: rallume à 22 h, il n'en a plus le lendemain matin. C'est la même idée que la fenêtre de
#: rattrapage de `reminders.GRACE`, appliquée au dernier maillon — celui qu'on ne contrôle
#: pas.
TTL = 4 * 3600


class PushGoneError(Exception):
    """L'abonnement n'existe plus côté service push.

    `404` ou `410` : le navigateur a été réinstallé, les données du site effacées, ou
    l'utilisateur a retiré l'autorisation. **Ce n'est pas une panne** — c'est la façon
    normale dont un abonnement se termine, et la seule conduite à tenir est de retirer la
    ligne du fichier. La distinguer d'une erreur de transport évite de garder
    indéfiniment des abonnements morts qu'on retenterait à chaque rappel.
    """


class PushFailedError(Exception):
    """L'envoi a échoué pour une autre raison — réseau, `5xx`, refus du service.

    L'abonnement est **conservé** : réessayer au prochain créneau a un sens.
    """


class PushSender:
    """Envoie une charge utile chiffrée à un abonnement.

    Détient un pool de connexions keep-alive, comme le client WebDAV et le client
    OpenRouter : il naît dans la boucle d'événements et se relâche à l'arrêt.
    """

    def __init__(
        self,
        *,
        public_key: str,
        private_key: str,
        subject: str,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._public_key = public_key
        self._vapid = Vapid02.from_string(private_key)
        self._subject = subject
        self._client = httpx2.AsyncClient(timeout=TIMEOUT, transport=transport)

    @property
    def public_key(self) -> str:
        """Clé publique servie à l'écran pour `pushManager.subscribe`."""
        return self._public_key

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> PushSender:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def _authorization(self, endpoint: str) -> dict[str, str]:
        """En-tête d'identification du serveur d'application (RFC 8292).

        L'audience est l'**origine** du service push, pas l'URL complète : un jeton signé
        pour `https://fcm.googleapis.com/fcm/send/abc` serait refusé, et le message
        n'arriverait jamais.
        """
        parsed = httpx2.URL(endpoint)
        audience = f"{parsed.scheme}://{parsed.host}"
        claims = {
            "aud": audience,
            "exp": int(time.time()) + JWT_TTL,
            "sub": self._subject,
        }
        return dict(self._vapid.sign(claims))

    async def send(self, *, endpoint: str, p256dh: str, auth: str, payload: dict[str, str]) -> None:
        """Chiffre et remet une notification. Lève, ou ne rend rien.

        La charge utile est du JSON : c'est ce que lit le `push` du service worker. Elle ne
        porte **que du texte déjà composé** — le worker n'a aucune décision à prendre, et
        surtout aucun chiffre à mettre en forme lui-même.
        """
        subscription = {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}

        # `encode` ne fait aucune I/O : c'est le chiffrement seul. Tout ce qui suit est à
        # nous.
        body = WebPusher(subscription).encode(json.dumps(payload).encode("utf-8"))["body"]

        headers = {
            **self._authorization(endpoint),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(TTL),
        }

        try:
            response = await self._client.post(endpoint, content=body, headers=headers)
        except httpx2.HTTPError as error:  # réseau, DNS, délai dépassé
            raise PushFailedError(str(error)) from error

        if response.status_code in (404, 410):
            raise PushGoneError(f"abonnement révoqué ({response.status_code})")
        if response.status_code >= 400:
            raise PushFailedError(f"service push : {response.status_code}")


__all__ = ["TTL", "PushFailedError", "PushGoneError", "PushSender"]
