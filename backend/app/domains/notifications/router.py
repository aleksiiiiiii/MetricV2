"""Endpoints des notifications push (`NOT-01`, `NOT-03`).

**Toutes ces routes sont dans le groupe protégé** de `app/domains/api.py`. Le flux `.ics`
du planning est la seule exception du projet, et le §2 de `docs/etat-du-projet.md` dit
qu'une deuxième n'y aurait pas droit : « c'est la forme du besoin qui l'a justifiée là, pas
la commodité ». Un abonnement push se fait depuis l'application connectée — il n'a aucun
besoin d'échapper au jeton.

L'état, lui, répond **`200` même sans clé**. C'est le régime de `AiStatus` et de
`SubscriptionInfo` : un écran ne demande jamais « la clé est-elle configurée ? » à sa
propre configuration, il le demande au serveur, et une clé absente est un état.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from app.core.deps import StoreDep
from app.core.exceptions import NotFoundError, PushNotConfiguredError
from app.domains.notifications.provider import PushProvider
from app.domains.notifications.schemas import (
    NotificationsView,
    PushStatus,
    RemindersPayload,
    SubscriptionPayload,
)
from app.domains.notifications.service import NotificationService
from app.storage.errors import StorageConflictError

router = APIRouter(prefix="/notifications", tags=["notifications"])

IfMatch = Annotated[str | None, Header(alias="If-Match")]


def get_push(request: Request) -> PushProvider:
    """Fournisseur attaché à l'application par le `lifespan`."""
    provider = getattr(request.app.state, "push", None)
    if not isinstance(provider, PushProvider):  # pragma: no cover - erreur de câblage
        raise RuntimeError("« push » n'a pas été initialisé par le lifespan.")
    return provider


PushDep = Annotated[PushProvider, Depends(get_push)]


def _status(push: PushDep) -> PushStatus:
    return PushStatus(
        configured=push.enabled,
        public_key=push.public_key,
        message=push.message,
    )


@router.get("", response_model=NotificationsView, summary="Rappels et appareils abonnés")
async def read_notifications(store: StoreDep, push: PushDep) -> NotificationsView:
    """Tout ce qu'affiche la section « Rappels » de `/reglages`, en une requête.

    Répond `200` avec ou sans clé : sans elle, `push.configured` vaut faux et le message
    dit ce qui manque. Les créneaux, eux, restent lisibles et modifiables — ils vivent dans
    `settings.csv` et ne dépendent d'aucune clé.
    """
    service = NotificationService(store)
    return NotificationsView(
        push=_status(push),
        devices=await service.devices(),
        reminders=await service.reminders(),
        token=await service.settings_token(),
    )


@router.post("/subscribe", status_code=204, summary="Abonner cet appareil")
async def subscribe(payload: SubscriptionPayload, store: StoreDep, push: PushDep) -> None:
    """Enregistre un appareil. Idempotent par `endpoint`.

    Refuse sans clé VAPID, **avec un code du catalogue** : accepter un abonnement qu'on ne
    saurait jamais signer laisserait l'écran afficher « abonné » pour quelqu'un qui ne
    recevrait rien. C'est le pire des deux états possibles.
    """
    if not push.enabled:
        raise PushNotConfiguredError
    await NotificationService(store).subscribe(payload)


@router.delete("/subscribe", status_code=204, summary="Désabonner cet appareil")
async def unsubscribe(endpoint: str, store: StoreDep) -> None:
    """Retire un abonnement.

    Ne dépend pas de la clé VAPID : on doit pouvoir se désabonner même après que la
    configuration a changé — sinon une ligne morte resterait dans le fichier sans aucun
    moyen de la retirer depuis l'application.
    """
    await NotificationService(store).unsubscribe(endpoint)


@router.patch("/reminders", response_model=NotificationsView, summary="Régler les rappels")
async def update_reminders(
    payload: RemindersPayload,
    store: StoreDep,
    push: PushDep,
    if_match: IfMatch = None,
) -> NotificationsView:
    """Modifie les créneaux (`NOT-03`).

    **Un champ omis reste à sa valeur ; un champ à `null` éteint le rappel.** C'est une
    modification partielle, d'où `PATCH` — le même verbe que `/api/settings`, qui édite le
    même fichier.

    La garde porte sur `settings.csv` entier, comme pour les autres réglages : un
    `If-Match` **absent est un conflit**, jamais une permission (`STO-05`).
    """
    if not if_match:
        raise StorageConflictError(
            "Recharge la donnée avant de la modifier.", detail="en-tête If-Match absent"
        )

    service = NotificationService(store)
    await service.update_reminders(payload.model_dump(exclude_unset=True), if_match.strip('"'))
    return NotificationsView(
        push=_status(push),
        devices=await service.devices(),
        reminders=await service.reminders(),
        token=await service.settings_token(),
    )


@router.post("/test", status_code=204, summary="Envoyer une notification d'essai")
async def send_test(store: StoreDep, push: PushDep) -> None:
    """Remet une notification d'essai à tous les appareils abonnés.

    C'est le seul moyen de vérifier la chaîne entière — clés, chiffrement, service push,
    service worker — sans attendre un créneau. La moitié de DoD du lot en dépend : « un
    rappel reçu application fermée » ne se teste pas en CI.

    Le texte suit la même règle que les vrais rappels : il ne dit rien de ce qui a été
    fait ou non. Et son `tag` lui est propre — emprunter celui d'un créneau ferait
    disparaître un vrai rappel du centre de notifications au profit d'un essai.
    """
    if not push.enabled or push.sender is None:
        raise PushNotConfiguredError

    service = NotificationService(store)
    if not await service.subscriptions():
        raise NotFoundError("Aucun appareil n'est abonné sur ce compte.")

    await service.deliver(
        push.sender,
        {
            "title": "Metric",
            "body": "Essai reçu. Les rappels arriveront à leurs créneaux.",
            "tag": "essai",
            "url": "/reglages",
        },
    )
