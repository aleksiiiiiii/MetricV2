"""Formes échangées par les notifications (`NOT-01`, `NOT-03`)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

#: Un créneau `HH:MM` sur 24 heures. Le motif refuse `25:00` et `7:5`, que `time.fromisoformat`
#: accepterait ou rejetterait selon la version — la frontière de l'API ne se repose pas sur
#: la tolérance d'une bibliothèque.
Slot = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]

#: Valeur base64url d'une clé d'abonnement. On ne l'interprète jamais : elle repart au
#: chiffrement telle qu'elle est arrivée. La borne haute existe pour qu'un appel malformé
#: n'écrive pas un kilo-octet dans une cellule de tableur.
PushKey = Annotated[str, StringConstraints(min_length=8, max_length=255, strip_whitespace=True)]


class PushStatus(BaseModel):
    """Ce que l'écran a besoin de savoir avant de proposer un abonnement (`NOT-01`).

    **Même forme que `AiStatus` et `SubscriptionInfo`, et pour la même raison** : un écran
    ne demande jamais « la clé est-elle configurée ? » à sa propre configuration — il ne la
    connaît pas. Il le demande au serveur, qui répond **`200` dans les deux cas** et
    fournit la phrase à afficher, en français (`API-07`).

    Une clé absente est un **état**, pas une panne. C'est `IA-07` appliqué au push.
    """

    configured: bool = Field(description="Une paire de clés VAPID est configurée")
    #: Clé publique à passer à `pushManager.subscribe`. `null` tant qu'il n'y en a pas —
    #: l'écran n'a donc rien à deviner et ne peut pas tenter un abonnement voué à l'échec.
    public_key: str | None = Field(default=None, description="Clé publique VAPID, base64url")
    message: str = Field(description="Ce qu'il y a à dire à l'écran, en français")


class SubscriptionPayload(BaseModel):
    """Un abonnement tel que le navigateur le rend (`PushSubscription.toJSON()`)."""

    #: Adresse du service push. C'est l'identité de l'abonnement : deux lignes de même
    #: `endpoint` sont un doublon, pas deux appareils.
    endpoint: Annotated[str, StringConstraints(min_length=8, max_length=2048)]
    p256dh: PushKey
    auth: PushKey
    #: Purement informatif — sert à distinguer deux appareils dans la liste. Aucune
    #: décision ne s'y appuie, donc aucune raison de le contraindre au-delà d'une borne.
    user_agent: Annotated[str, StringConstraints(max_length=255)] = ""


#: Une liste de créneaux `HH:MM`, séparés par des virgules — ou un seul.
#:
#: Le même format que `hydration_presets_ml` sur l'écran des réglages, et pour la même
#: raison : un réglage qui porte plusieurs valeurs doit se lire et se corriger dans un
#: tableur sans connaître le schéma.
SLOT_LIST_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d(,\s*([01]\d|2[0-3]):[0-5]\d)*$"
Slots = Annotated[str, Field(pattern=SLOT_LIST_PATTERN, max_length=64)]


class Reminders(BaseModel):
    """Les cinq créneaux (`NOT-03`, **N2**).

    `null` veut dire **éteint**, et c'est la valeur par défaut : aucun rappel n'est
    configuré à l'installation. Un rappel qui arrive au mauvais moment se désinstalle en un
    geste et ne revient jamais — chaque créneau est donc un choix explicite.

    **L'hydratation porte une liste**, les autres un créneau. L'écart d'hydratation se lit
    à plusieurs moments de la journée — 14 h, 18 h, 22 h 30 — et un contrôle unique
    obligerait à choisir entre « trop tôt pour savoir » et « trop tard pour agir ». Les
    autres types n'ont qu'un moment où ils veulent dire quelque chose.
    """

    supplements: Slot | None = None
    hydration: Slots | None = None
    meals: Slot | None = None
    workout: Slot | None = None
    #: L'écart aux protéines, au dernier moment où un repas peut le combler.
    protein: Slot | None = None


class RemindersPayload(BaseModel):
    """Modification des créneaux.

    **Un champ omis reste à sa valeur ; un champ à `null` éteint le rappel.** La distinction
    passe par `model_dump(exclude_unset=True)` — c'est déjà la convention de
    `SettingsPayload`, à ceci près qu'ici `null` porte un sens au lieu de valoir
    « non fourni ». D'où le passage par `SettingsService.update_keys`, qui écrit les cellules
    vides au lieu de les ignorer.
    """

    supplements: Slot | None = None
    hydration: Slots | None = None
    meals: Slot | None = None
    workout: Slot | None = None
    protein: Slot | None = None


class SubscribedDevice(BaseModel):
    """Un appareil abonné, tel qu'il s'affiche à l'écran."""

    id: str
    created: str | None = None
    #: Nom court — « iPhone », « Mac », « Appareil ». Il est **dérivé par le serveur** du
    #: `user-agent` conservé dans le fichier, qui n'est pas publié : `Mozilla/5.0 (iPhone;
    #: CPU iPhone OS 18_5 like…` tronqué à l'écran ne nomme rien et se lit comme un défaut
    #: d'affichage. Le dériver côté client aurait fait de la mise en forme une règle, et
    #: le §2 réserve les dérivations au serveur.
    label: str
    #: Les derniers caractères de l'`endpoint`. De quoi distinguer deux appareils sans
    #: publier l'adresse entière, qui est un secret : qui la détient peut envoyer une
    #: notification à cet appareil.
    hint: str


class NotificationsView(BaseModel):
    """Réponse unique de la section « Rappels » de `/reglages`."""

    push: PushStatus
    devices: list[SubscribedDevice]
    reminders: Reminders
    #: Garde anti-conflit du fichier de réglages (`STO-05`), à renvoyer en « If-Match ».
    #: C'est bien celui de `settings.csv` : les créneaux y vivent, pas dans un fichier à
    #: eux (`NOT-03`).
    token: str
