"""Endpoints du planning (`PLAN-01` → `PLAN-06`).

Deux routeurs, et leur séparation est une décision de sécurité, pas de rangement.

`router` est monté dans le **groupe protégé** : tout ce qui lit ou écrit le planning exige
un jeton, parce qu'il est dans le groupe et non parce que quelqu'un y a pensé (`AUTH-05`).

`calendar_router` est monté **au niveau de l'application**, avec la santé et la
documentation, et il n'exige pas de jeton — il est protégé par une clé secrète portée
dans son URL. Ce n'est pas un contournement de `AUTH-05` mais la seule forme que le
besoin admet : un abonnement Apple Calendar ou Google Agenda va chercher son `.ics` tout
seul, périodiquement, sans interface où saisir quoi que ce soit et **sans pouvoir porter
d'en-tête `Authorization`**. Exiger le JWT reviendrait à livrer une fonctionnalité qui ne
peut pas fonctionner.

Ce que cela impose en retour, et qui est vérifié plus bas :

* la clé est **longue** — une URL publique se devine, un mot de passe de six caractères
  se devine vite ;
* sa comparaison est à **temps constant** — l'URL est publique, donc mesurable ;
* une clé absente ne publie **rien**, au lieu de publier tout ;
* la réponse ne distingue pas « mauvaise clé » de « aucun flux », pour ne pas confirmer
  qu'il y a quelque chose à trouver.
"""

from __future__ import annotations

import secrets as secrets_module
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, Request, Response, status

from app.config import ICAL_SECRET_MIN_LENGTH, Settings
from app.core.dates import now_local, today_local
from app.core.deps import SettingsDep, StoreDep
from app.core.exceptions import NotFoundError
from app.domains.ai.deps import AiServiceDep
from app.domains.planning import ical
from app.domains.planning.schemas import (
    AdherenceView,
    AdoptionPayload,
    AdoptionResult,
    MonthView,
    PlannedSession,
    PlanPayload,
    Proposal,
    ProposalRequest,
    SubscriptionInfo,
)
from app.domains.planning.service import DEFAULT_ADHERENCE_WEEKS, PlanningService
from app.storage.errors import StorageConflictError
from app.storage.files import FileStore

router = APIRouter(prefix="/planning", tags=["planning"])

#: Routeur public du flux abonnable. Monté par `app.main`, hors du groupe protégé.
calendar_router = APIRouter(prefix="/api", tags=["planning"])

RowId = Annotated[int, Path(ge=0)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]
Month = Annotated[
    str | None,
    Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Mois affiché, `AAAA-MM`"),
]
Weeks = Annotated[int, Query(ge=1, le=52, description="Semaines observées")]


def _token(value: str | None) -> str:
    """Un `If-Match` absent est un **conflit**, jamais une permission (`STO-05`)."""
    if not value:
        raise StorageConflictError(
            "Recharge la donnée avant de la modifier.", detail="en-tête If-Match absent"
        )
    return value.strip('"')


def _month(raw: str | None) -> date:
    if raw is None:
        return today_local().replace(day=1)
    year, month = raw.split("-")
    return date(int(year), int(month), 1)


# ── Calendrier et séances ─────────────────────────────


@router.get("/month", response_model=MonthView, summary="Calendrier mensuel")
async def read_month(store: StoreDep, month: Month = None) -> MonthView:
    """Un mois de prévu et d'effectué, en une requête (`PLAN-01`).

    Prévu et réalisé arrivent ensemble : les demander séparément coûterait deux
    allers-retours pour un écran qui ne sait rien afficher tant qu'il n'a pas les deux.
    """
    return await PlanningService(store).month(_month(month))


@router.post(
    "/sessions",
    response_model=PlannedSession,
    status_code=status.HTTP_201_CREATED,
    summary="Planifier une séance",
)
async def create(payload: PlanPayload, store: StoreDep) -> PlannedSession:
    return await PlanningService(store).create(payload)


@router.patch(
    "/sessions/{row_id}", response_model=PlannedSession, summary="Modifier une séance prévue"
)
async def update(
    row_id: RowId, payload: PlanPayload, store: StoreDep, if_match: IfMatch = None
) -> PlannedSession:
    return await PlanningService(store).update(row_id, _token(if_match), payload)


@router.delete(
    "/sessions/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirer une séance du planning",
)
async def remove(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    await PlanningService(store).remove(row_id, _token(if_match))


@router.get("/adherence", response_model=AdherenceView, summary="Écart plan / réalisé")
async def adherence(store: StoreDep, weeks: Weeks = DEFAULT_ADHERENCE_WEEKS) -> AdherenceView:
    """Séances prévues contre séances effectuées, et taux de respect (`PLAN-06`)."""
    return await PlanningService(store).adherence(weeks=weeks)


# ── Proposition assistée (`PLAN-03`, `PLAN-04`) ───────


@router.post("/proposal", response_model=Proposal, summary="Proposer un planning")
async def propose(payload: ProposalRequest, store: StoreDep, ai: AiServiceDep) -> Proposal:
    """Demande une ou deux semaines à un modèle. **Rien n'est écrit** (`PLAN-04`).

    Sans clé OpenRouter, `AiServiceDep` fait échouer l'endpoint avec un code du catalogue
    avant même d'entrer ici (`IA-07`) : la planification manuelle, elle, reste entière.
    """
    return await PlanningService(store).propose(ai, payload)


@router.post(
    "/proposal/adopt",
    response_model=AdoptionResult,
    status_code=status.HTTP_201_CREATED,
    summary="Adopter les séances retenues",
)
async def adopt(payload: AdoptionPayload, store: StoreDep) -> AdoptionResult:
    """Écrit les séances que l'utilisateur a gardées, marquées `source=ai` (`PLAN-04`).

    Aucune dépendance à l'IA : une fois la proposition relue et amputée de ce qu'on n'en
    voulait pas, il ne reste qu'une saisie. C'est ce qui permet d'adopter une proposition
    affichée il y a dix minutes, ou dont on a tout réécrit.
    """
    return await PlanningService(store).adopt(payload.sessions)


# ── Export iCal (`PLAN-05`) ───────────────────────────


async def _calendar_response(store: FileStore, *, settings: Settings, download: bool) -> Response:
    """Rend le flux, en pièce jointe ou en ligne."""
    sessions = await PlanningService(store).feed_sessions()
    body = ical.render(sessions, stamp=now_local(), tz=settings.tz)

    disposition = "attachment" if download else "inline"
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'{disposition}; filename="metric-planning.ics"',
            # Un abonnement qui recevrait une version mémorisée par un intermédiaire
            # afficherait un planning périmé sans que rien ne le signale.
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@router.get(
    "/export.ics",
    summary="Télécharger le planning",
    response_class=Response,
    responses={200: {"content": {"text/calendar": {}}}},
)
async def export(store: StoreDep, settings: SettingsDep) -> Response:
    """Téléchargement ponctuel, sous jeton (`PLAN-05`).

    Route protégée ordinaire : ici l'appelant est un navigateur qui a une session, pas un
    client de calendrier. Elle n'a donc aucune raison de dépendre de la clé secrète — et
    elle reste utilisable quand celle-ci n'est pas configurée.
    """
    return await _calendar_response(store, settings=settings, download=True)


@router.get("/subscription", response_model=SubscriptionInfo, summary="Adresse d'abonnement")
def subscription(request: Request, settings: SettingsDep) -> SubscriptionInfo:
    """Dit si le flux est publiable, et à quelle adresse (`PLAN-05`).

    Répond `200` dans les deux cas, comme l'état de l'assistance IA : une clé absente est
    un **état**, pas une panne. L'écran affiche alors ce qu'il faut faire pour l'avoir.
    """
    if not settings.ical_enabled:
        return SubscriptionInfo(
            configured=False,
            url=None,
            message=(
                "Aucune clé d'abonnement n'est configurée. Renseigne « ICAL_SECRET » avec "
                "une valeur d'au moins "
                f"{ICAL_SECRET_MIN_LENGTH} caractères — par exemple le résultat de "
                '« python -c "import secrets; print(secrets.token_urlsafe(32))" » — '
                "puis redémarre l'API. Le téléchargement, lui, fonctionne déjà."
            ),
        )

    url = str(request.url_for("calendar_feed", secret=settings.ical_secret))
    return SubscriptionInfo(
        configured=True,
        url=url,
        message=(
            "Cette adresse contient ta clé : elle vaut mot de passe. Dans Apple Calendar, "
            "menu « Fichier », puis « Nouvel abonnement au calendrier » ; sur iPhone, "
            "onglet « Calendriers », « Ajouter un calendrier avec abonnement »."
        ),
    )


@calendar_router.get(
    "/calendar/{secret}.ics",
    name="calendar_feed",
    summary="Flux iCal abonnable",
    response_class=Response,
    responses={200: {"content": {"text/calendar": {}}}},
    include_in_schema=False,
)
async def calendar_feed(secret: str, store: StoreDep, settings: SettingsDep) -> Response:
    """Flux public protégé par clé (`PLAN-05`).

    Hors du schéma publié : la garde structurelle de `AUTH-05` lit l'OpenAPI et y exige un
    jeton sur toute opération de données. L'exposer là demanderait d'y déclarer une
    exception permanente, c'est-à-dire d'ouvrir une porte dans le mécanisme même qui les
    interdit. La route reste évidemment testée — mais elle ne figure pas dans le contrat
    des routes de données, parce qu'elle n'en est pas une.
    """
    expected = settings.ical_secret.strip()

    # `compare_digest` et non `==` : l'URL est publique, donc son temps de réponse est
    # mesurable, et une comparaison qui s'arrête au premier caractère faux se remonte
    # lettre par lettre.
    #
    # La clé absente est traitée **avant** la comparaison : sans cela, une configuration
    # vide publierait le planning à quiconque demande `/api/calendar/.ics`.
    if not settings.ical_enabled or not secrets_module.compare_digest(secret, expected):
        # Le même refus dans les deux cas : distinguer « clé fausse » de « aucun flux »
        # confirmerait qu'il y a quelque chose à trouver ici.
        raise NotFoundError("Ce calendrier n'existe pas.")

    return await _calendar_response(store, settings=settings, download=False)
