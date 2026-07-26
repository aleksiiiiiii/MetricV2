"""Anti-brute-force sur la connexion (`AUTH-04`).

Fenêtre glissante en mémoire : au-delà de 5 échecs en 60 secondes depuis la même
adresse, la route de connexion répond `429` en annonçant le délai d'attente.

Seuls les **échecs** sont comptés, et une connexion réussie remet le compteur à zéro :
un utilisateur légitime qui se trompe deux fois puis réussit ne doit pas rester pénalisé.

En mémoire et non dans le stockage : un redémarrage remet les compteurs à zéro, ce qui
est acceptable pour une application mono-utilisateur — l'alternative serait d'écrire sur
Nextcloud à chaque tentative de connexion, donc de faire de la route de connexion le
point le plus lent et le plus fragile de l'API.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

from app.core.exceptions import TooManyAttemptsError

#: Au-delà de ce nombre d'adresses suivies, on purge les entrées périmées. Empêche une
#: attaque distribuée de faire grossir le dictionnaire indéfiniment.
_PRUNE_ABOVE = 1024


class LoginThrottle:
    """Compteur d'échecs de connexion par adresse."""

    def __init__(
        self,
        *,
        max_failures: int = 5,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_failures
        self._window = window_seconds
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}

    def guard(self, key: str) -> None:
        """Refuse la tentative si le quota est déjà atteint."""
        if len(self._failures) > _PRUNE_ABOVE:
            self._prune()

        recent = self._recent(key)
        if len(recent) < self._max:
            return

        # Le quota se libère quand la plus ancienne tentative sort de la fenêtre.
        wait = self._window - (self._clock() - recent[0])
        raise TooManyAttemptsError(retry_after=max(1, math.ceil(wait)))

    def record_failure(self, key: str) -> None:
        self._recent(key).append(self._clock())

    def clear(self, key: str) -> None:
        """Remet le compteur à zéro après une connexion réussie."""
        self._failures.pop(key, None)

    def failures(self, key: str) -> int:
        return len(self._recent(key))

    # ── Interne ───────────────────────────────────────

    def _recent(self, key: str) -> deque[float]:
        """Tentatives encore dans la fenêtre, les plus anciennes évacuées."""
        attempts = self._failures.setdefault(key, deque())
        horizon = self._clock() - self._window
        while attempts and attempts[0] <= horizon:
            attempts.popleft()
        return attempts

    def _prune(self) -> None:
        for key in list(self._failures):
            if not self._recent(key):
                del self._failures[key]


def client_ip(request: Request, *, trust_proxy: bool) -> str:
    """Adresse de l'appelant, pour clé de comptage.

    Derrière le reverse-proxy de production (`OPS-01`), `request.client` est l'adresse du
    proxy : compter dessus reviendrait à verrouiller tout le monde dès qu'une seule
    adresse se trompe. `TRUST_PROXY_HEADERS=true` fait alors lire `X-Forwarded-For`.

    Ce réglage est faux par défaut, et c'est délibéré : en exposition directe, n'importe
    qui pourrait forger l'en-tête et rendre le compteur inopérant.
    """
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first

    return request.client.host if request.client else "inconnue"
