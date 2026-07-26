"""Mots de passe et jetons de session (`AUTH-01` → `AUTH-03`).

Deux objets sans état partagé, construits une fois par application :

* `PasswordChecker` — vérifie un couple identifiant / mot de passe contre la
  configuration serveur, en Argon2id, sans jamais laisser le temps de réponse trahir
  lequel des deux champs est faux.
* `TokenIssuer` — émet et relit les JWT de session.

Aucun mot de passe en clair n'est conservé où que ce soit : la configuration ne contient
qu'un hash (`AUTH-02`), produit hors ligne par `make hash-password` (`AUTH-08`).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

from app.config import Settings
from app.core.exceptions import AuthNotConfiguredError, SessionExpiredError

#: Mot de passe factice, haché au démarrage. Il sert de cible de vérification quand
#: l'identifiant est inconnu : sans lui, un identifiant faux répondrait sans passer par
#: Argon2 et le temps de réponse dirait lequel des deux champs est en cause (`AUTH-04`).
_DECOY_SECRET = "mot de passe factice, jamais valide"


def hash_password(plain: str) -> str:
    """Produit un hash Argon2id, sel embarqué (`AUTH-02`, `AUTH-08`)."""
    return PasswordHasher(type=Type.ID).hash(plain)


@lru_cache(maxsize=1)
def _decoy_hash() -> str:
    """Hash du mot de passe factice, calculé une fois par processus.

    Argon2 est lent par construction — c'est son intérêt. Le recalculer à chaque
    construction d'application alourdirait inutilement le démarrage et la batterie de
    tests, alors que la valeur hachée est une constante.
    """
    return PasswordHasher(type=Type.ID).hash(_DECOY_SECRET)


@lru_cache(maxsize=8)
def _hash_is_readable(candidate: str) -> bool:
    """Vrai si la chaîne configurée est un hash Argon2 exploitable.

    Évalué une fois par valeur : c'est une propriété de la configuration, pas de la
    requête.
    """
    if not candidate:
        return False
    try:
        PasswordHasher(type=Type.ID).verify(candidate, _DECOY_SECRET)
    except VerifyMismatchError:
        return True  # hash valide, mot de passe simplement différent
    except (VerificationError, InvalidHashError):
        return False
    # Cas absurde : le hash configuré correspond au mot de passe factice.
    return False


class PasswordChecker:
    """Vérification du couple identifiant / mot de passe (`AUTH-01`, `AUTH-02`)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._hasher = PasswordHasher(type=Type.ID)
        self._decoy = _decoy_hash()
        # La validité du hash configuré est évaluée au démarrage, pas par requête :
        # sinon un hash illisible ferait échouer la vérification uniquement quand
        # l'identifiant est correct, ce qui en révélerait la valeur.
        self._hash_usable = _hash_is_readable(settings.auth_password_hash)

    @property
    def configured(self) -> bool:
        return bool(self._settings.auth_username) and self._hash_usable

    def verify(self, username: str, password: str) -> bool:
        """Vrai si le couple correspond à la configuration.

        Argon2 est exécuté dans **tous** les cas, y compris sur identifiant inconnu.
        C'est ce qui rend les deux échecs indistinguables au chronomètre (`AUTH-04`).
        """
        if not self.configured:
            raise AuthNotConfiguredError

        known_user = secrets.compare_digest(username, self._settings.auth_username)
        target = self._settings.auth_password_hash if known_user else self._decoy

        try:
            self._hasher.verify(target, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

        return known_user


@dataclass(frozen=True, slots=True)
class Session:
    """Jeton émis et son échéance."""

    access_token: str
    expires_at: datetime
    username: str


class TokenIssuer:
    """Émission et relecture des JWT de session (`AUTH-03`)."""

    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret
        self._algorithm = settings.jwt_algorithm
        self._ttl = timedelta(days=settings.jwt_ttl_days)

    def issue(self, username: str) -> Session:
        """Émet un jeton signé, valable `JWT_TTL_DAYS` jours.

        La session survit à la fermeture de l'app et au redémarrage de l'appareil : le
        jeton est autoporteur, il n'y a pas de session en mémoire côté serveur.
        """
        issued_at = datetime.now(tz=UTC)
        expires_at = issued_at + self._ttl

        token = jwt.encode(
            {"sub": username, "iat": issued_at, "exp": expires_at},
            self._secret,
            algorithm=self._algorithm,
        )
        return Session(access_token=token, expires_at=expires_at, username=username)

    def read(self, token: str) -> str:
        """Rend l'identifiant porté par un jeton valide.

        Jeton absent, expiré, mal signé ou forgé se soldent par la même erreur : côté
        client la conduite à tenir est identique — purger et redemander la connexion
        (`AUTH-06`).

        La liste d'algorithmes est explicite : c'est ce qui interdit à un jeton forgé
        d'imposer `alg: none` et de passer sans signature.
        """
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"require": ["sub", "exp"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise SessionExpiredError(detail="jeton expiré") from exc
        except jwt.InvalidTokenError as exc:
            raise SessionExpiredError(detail=f"jeton invalide : {exc}") from exc

        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise SessionExpiredError(detail="jeton sans sujet exploitable")
        return subject
