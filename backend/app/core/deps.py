"""Dépendances FastAPI partagées."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.core.exceptions import SessionExpiredError
from app.core.security import PasswordChecker, TokenIssuer
from app.core.throttle import LoginThrottle
from app.storage.files import FileStore
from app.storage.provider import StorageProvider

#: `auto_error=False` : on veut lever `SessionExpiredError` — donc un code machine du
#: catalogue (`API-07`) — plutôt que le 403 générique de FastAPI. Déclarer le schéma
#: sert aussi la documentation interactive (`API-05`).
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="Session Metric")


def _from_state(request: Request, name: str, expected: type[object]) -> object:
    value = getattr(request.app.state, name, None)
    if not isinstance(value, expected):  # pragma: no cover - erreur de câblage
        raise RuntimeError(f"« {name} » n'a pas été initialisé par le lifespan.")
    return value


def get_app_settings(request: Request) -> Settings:
    """Réglages **de cette application**, et non ceux du processus.

    `create_app(settings)` existe pour permettre des applications isolées — un test qui
    veut une clé d'abonnement iCal, un autre qui n'en veut pas. Lire `get_settings()`
    dans une route rendrait ce paramètre à moitié faux : l'application serait construite
    avec les réglages reçus et se comporterait selon ceux du fichier `.env`.

    Le repli sur `get_settings()` couvre une application montée sans passer par
    `create_app` ; il ne devrait jamais servir en production.
    """
    settings = getattr(request.app.state, "settings", None)
    return settings if isinstance(settings, Settings) else get_settings()


def get_storage_provider(request: Request) -> StorageProvider:
    """Fournisseur de stockage attaché à l'application par le `lifespan`."""
    provider = _from_state(request, "storage", StorageProvider)
    assert isinstance(provider, StorageProvider)
    return provider


def get_store(provider: Annotated[StorageProvider, Depends(get_storage_provider)]) -> FileStore:
    """`FileStore` prêt à l'emploi.

    Lève `StorageNotConfiguredError` — traduite en `503` avec un message actionnable — si
    Nextcloud n'est pas renseigné.
    """
    return provider.store


def get_password_checker(request: Request) -> PasswordChecker:
    checker = _from_state(request, "password_checker", PasswordChecker)
    assert isinstance(checker, PasswordChecker)
    return checker


def get_token_issuer(request: Request) -> TokenIssuer:
    issuer = _from_state(request, "token_issuer", TokenIssuer)
    assert isinstance(issuer, TokenIssuer)
    return issuer


def get_throttle(request: Request) -> LoginThrottle:
    throttle = _from_state(request, "login_throttle", LoginThrottle)
    assert isinstance(throttle, LoginThrottle)
    return throttle


def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    issuer: Annotated[TokenIssuer, Depends(get_token_issuer)],
) -> str:
    """Exige un jeton valide et rend l'identifiant qu'il porte (`AUTH-05`).

    Jeton absent, mal formé, expiré ou forgé aboutissent tous à `session_expired` : la
    conduite à tenir côté client est la même dans les quatre cas (`AUTH-06`).
    """
    if credentials is None or not credentials.credentials:
        raise SessionExpiredError(detail="en-tête Authorization absent ou vide")
    return issuer.read(credentials.credentials)


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
StoreDep = Annotated[FileStore, Depends(get_store)]
CheckerDep = Annotated[PasswordChecker, Depends(get_password_checker)]
IssuerDep = Annotated[TokenIssuer, Depends(get_token_issuer)]
ThrottleDep = Annotated[LoginThrottle, Depends(get_throttle)]
UserDep = Annotated[str, Depends(require_auth)]
