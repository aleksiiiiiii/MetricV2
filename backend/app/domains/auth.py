"""Authentification (`AUTH-01` → `AUTH-07`).

Un seul compte, décrit par la configuration serveur : ni inscription, ni multi-comptes.
La connexion émet un JWT que le client renvoie en `Authorization: Bearer`.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from app.core.deps import CheckerDep, IssuerDep, SettingsDep, ThrottleDep, UserDep
from app.core.exceptions import InvalidCredentialsError
from app.core.throttle import client_ip

router = APIRouter(prefix="/auth", tags=["authentification"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class SessionResponse(BaseModel):
    """Jeton de session et son échéance."""

    access_token: str = Field(description="JWT à renvoyer en « Authorization: Bearer »")
    token_type: str = Field(default="bearer", description="Type de jeton")
    expires_at: datetime = Field(description="Échéance du jeton, fuseau inclus")
    username: str = Field(description="Identifiant connecté")


class CurrentUser(BaseModel):
    username: str


@router.post(
    "/login",
    response_model=SessionResponse,
    summary="Ouvrir une session",
)
def login(
    payload: LoginRequest,
    request: Request,
    checker: CheckerDep,
    issuer: IssuerDep,
    throttle: ThrottleDep,
    settings: SettingsDep,
) -> SessionResponse:
    """Vérifie le couple identifiant / mot de passe et émet un jeton.

    L'ordre des opérations compte : le quota d'échecs est consulté **avant** de hacher,
    sinon une attaque par force brute ferait travailler Argon2 à chaque tentative et
    coûterait plus au serveur qu'à l'attaquant (`AUTH-04`).
    """
    caller = client_ip(request, trust_proxy=settings.trust_proxy_headers)
    throttle.guard(caller)

    if not checker.verify(payload.username, payload.password):
        throttle.record_failure(caller)
        raise InvalidCredentialsError

    # Une réussite libère l'adresse : se tromper deux fois puis réussir ne doit pas
    # laisser de pénalité derrière soi.
    throttle.clear(caller)

    session = issuer.issue(payload.username)
    return SessionResponse(
        access_token=session.access_token,
        expires_at=session.expires_at,
        username=session.username,
    )


@router.get("/me", response_model=CurrentUser, summary="Session courante")
def me(username: UserDep) -> CurrentUser:
    """Confirme qu'un jeton est encore valide, et pour qui.

    Sert au client à décider entre afficher l'application et redemander la connexion.
    """
    return CurrentUser(username=username)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Fermer la session",
)
def logout(username: UserDep) -> None:
    """Termine la session (`AUTH-07`).

    Le jeton étant autoporteur, il n'y a rien à invalider côté serveur : l'effacement du
    jeton local est ce qui termine réellement la session. Cet endpoint existe pour que le
    client ait un point d'appel explicite et pour journaliser la déconnexion.

    Conséquence assumée : un jeton volé reste valide jusqu'à son échéance. Une liste de
    révocation supposerait un état partagé côté serveur, donc une écriture sur Nextcloud
    à chaque déconnexion — disproportionné pour une application mono-utilisateur dont le
    jeton ne quitte pas l'appareil.
    """
    del username
