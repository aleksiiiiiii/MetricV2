"""Abonnements, créneaux et envoi (`NOT-01`, `NOT-03`).

Ce service ne décide de rien : il lit et il écrit. **Ce qui est dû et ce que ça dit** vit
dans `reminders.py`, qui est pur ; **comment un message est chiffré et remis** vit dans
`push.py`. Le partage est le même que celui du domaine Assiduité — `engine.py` juge,
`grids.py` coud — et il est ici pour la même raison : une règle écrite dans un service qui
lit des fichiers ne se teste plus sans monter l'application.

Deux choses valent d'être sues avant de le lire.

**L'identité d'un abonnement est son `endpoint`.** C'est le navigateur qui le choisit, et
c'est ce que le service push reconnaît. S'abonner deux fois depuis le même appareil doit
donc **remplacer** la ligne, pas en ajouter une seconde : sans cela, chaque
réinstallation du site laisserait un abonnement mort qu'on retenterait à chaque rappel.

**Un envoi qui échoue ne se traite pas comme un envoi refusé.** `PushGoneError` — `404`
ou `410` — veut dire que l'abonnement n'existe plus, et la seule conduite à tenir est de
retirer la ligne. Une panne réseau, elle, se retente au prochain créneau. Confondre les
deux ferait soit accumuler des abonnements morts, soit désabonner quelqu'un parce que le
Wi-Fi a hoqueté.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date, datetime, time

from app.core.dates import today_local
from app.domains.app_settings.service import SettingsService
from app.domains.notifications.models import SentRow, SubscriptionRow
from app.domains.notifications.push import PushGoneError, PushSender
from app.domains.notifications.reminders import ReminderKind, parse_slot
from app.domains.notifications.schemas import (
    Reminders,
    SubscribedDevice,
    SubscriptionPayload,
)
from app.storage.csv_repo import CsvRepository
from app.storage.files import FileStore
from app.storage.paths import NOTIFICATIONS_SENT, PUSH_SUBSCRIPTIONS

#: Préfixe des clés de `settings.csv` (`NOT-03`). Le suffixe est la valeur de
#: `ReminderKind` : une seule orthographe pour le réglage, la notification et le journal
#: d'envoi. Trois graphies différentes rendraient un redémarrage incapable de reconnaître
#: ce qu'il a déjà envoyé.
SETTING_PREFIX = "reminders_"


def setting_key(kind: ReminderKind) -> str:
    return f"{SETTING_PREFIX}{kind.value}"


#: Familles d'appareils reconnues, dans l'ordre où on les cherche.
#:
#: L'ordre compte : un iPad annonce « Macintosh » sur iPadOS récent, et un Chrome sous
#: Android annonce « Linux ». On cherche donc du plus précis au plus vague.
_FAMILIES: tuple[tuple[str, str], ...] = (
    ("iphone", "iPhone"),
    ("ipad", "iPad"),
    ("android", "Android"),
    ("macintosh", "Mac"),
    ("mac os", "Mac"),
    ("windows", "Windows"),
    ("linux", "Linux"),
)


def device_label(user_agent: str) -> str:
    """Nom court d'un appareil, dérivé de son `user-agent`.

    `Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X)…` tronqué dans une liste ne
    nomme rien et se lit comme un défaut d'affichage — c'est ce que la capture a montré.
    On en tire une famille, et **rien de plus** : ni modèle, ni version, qui seraient
    devinés autant que lus.

    Une chaîne qu'on ne reconnaît pas rend « Appareil », jamais une supposition. C'est
    « aucune valeur inventée » à l'échelle d'un libellé : mieux vaut un mot générique
    qu'un nom d'appareil faux.
    """
    lowered = user_agent.lower()
    for needle, label in _FAMILIES:
        if needle in lowered:
            return label
    return "Appareil"


class NotificationService:
    """Lit et écrit les abonnements, les créneaux et le journal d'envoi."""

    def __init__(self, store: FileStore) -> None:
        self._subs: CsvRepository[SubscriptionRow] = CsvRepository(
            store, PUSH_SUBSCRIPTIONS, SubscriptionRow
        )
        self._sent: CsvRepository[SentRow] = CsvRepository(store, NOTIFICATIONS_SENT, SentRow)
        self._settings = SettingsService(store)

    # ── Abonnements (`NOT-01`) ────────────────────────

    async def subscriptions(self) -> list[SubscriptionRow]:
        """Abonnements en vigueur.

        Une ligne sans `endpoint` est **écartée des listes et conservée dans le fichier** :
        on n'efface pas ce qu'on ne comprend pas. C'est la règle de la famille *planning*,
        et elle vaut ici comme pour `plan.csv`.
        """
        rows = await self._subs.read_all()
        return [row.model for row in rows if row.model.endpoint]

    async def devices(self) -> list[SubscribedDevice]:
        """Les appareils abonnés, tels qu'ils s'affichent.

        L'`endpoint` n'est **pas** publié : qui le détient peut envoyer une notification à
        cet appareil. Seuls ses derniers caractères le sont, ce qui suffit à distinguer
        deux téléphones dans une liste.
        """
        return [
            SubscribedDevice(
                id=row.id,
                created=row.created.isoformat() if row.created else None,
                label=device_label(row.user_agent),
                hint=row.endpoint[-8:],
            )
            for row in await self.subscriptions()
        ]

    async def subscribe(self, payload: SubscriptionPayload) -> None:
        """Enregistre un appareil, ou met à jour celui qui porte déjà cet `endpoint`.

        Idempotent **par `endpoint`** : le navigateur rend le même abonnement tant qu'il
        n'a pas été révoqué, et un écran rouvert ne doit pas créer un doublon. Les clés
        peuvent avoir changé (le navigateur les régénère à l'occasion) — c'est pourquoi on
        remplace au lieu d'ignorer.
        """
        rows = await self._subs.load()
        others = [row.model for row in rows.rows if row.model.endpoint != payload.endpoint.strip()]

        # L'identifiant d'origine est conservé si l'appareil était déjà connu : il sert de
        # clé à l'écran, et le voir changer sous les doigts ferait clignoter la liste.
        known = next(
            (row.model for row in rows.rows if row.model.endpoint == payload.endpoint.strip()),
            None,
        )

        await self._subs.overwrite(
            [
                *others,
                SubscriptionRow(
                    id=known.id if known and known.id else uuid.uuid4().hex[:12],
                    created=known.created if known and known.created else today_local(),
                    endpoint=payload.endpoint.strip(),
                    p256dh=payload.p256dh,
                    auth=payload.auth,
                    user_agent=payload.user_agent,
                ),
            ],
            token=rows.token,
        )

    async def unsubscribe(self, endpoint: str) -> bool:
        """Retire un abonnement. Rend faux s'il n'y en avait pas.

        Pas de `404` sur un abonnement absent : se désabonner deux fois doit aboutir au
        même état, et un écran qui rejoue le geste après un rechargement ne doit pas
        recevoir une erreur pour un résultat correct.
        """
        sheet = await self._subs.load()
        kept = [row.model for row in sheet.rows if row.model.endpoint != endpoint.strip()]
        if len(kept) == len(sheet.rows):
            return False
        await self._subs.overwrite(kept, token=sheet.token)
        return True

    async def forget(self, endpoints: Iterable[str]) -> None:
        """Retire des abonnements révoqués par leur service push.

        Appelé par l'ordonnanceur après un `404`/`410`. Une seule écriture pour tout le
        lot : à ~180 ms l'aller-retour WebDAV, en faire une par abonnement mort coûterait
        plus que l'envoi lui-même.
        """
        morts = {endpoint.strip() for endpoint in endpoints}
        if not morts:
            return
        sheet = await self._subs.load()
        kept = [row.model for row in sheet.rows if row.model.endpoint not in morts]
        if len(kept) != len(sheet.rows):
            await self._subs.overwrite(kept, token=sheet.token)

    # ── Créneaux (`NOT-03`) ───────────────────────────

    async def reminders(self) -> Reminders:
        """Les quatre créneaux, lus dans `settings.csv`.

        Un horaire illisible rend `None`, c'est-à-dire **éteint**. C'est le seul repli
        acceptable pour un rappel : une valeur par défaut réveillerait quelqu'un.
        """
        values = await self._settings.all()
        slots = {kind.value: parse_slot(values.get(setting_key(kind), "")) for kind in ReminderKind}
        return Reminders(
            supplements=_render(slots["supplements"]),
            hydration=_render(slots["hydration"]),
            meals=_render(slots["meals"]),
            workout=_render(slots["workout"]),
        )

    async def raw_settings(self) -> dict[str, str]:
        """Réglages sous leur forme textuelle, défauts compris.

        L'ordonnanceur lit ainsi les clés `reminders_*` sans passer par `Reminders`, qui
        est une forme d'API : il a besoin des `time`, pas de chaînes `HH:MM` qu'il aurait
        à réanalyser.
        """
        return await self._settings.all()

    async def settings_token(self) -> str:
        """Jeton de `settings.csv` — les créneaux y vivent (`STO-05`)."""
        return await self._settings.token()

    async def update_reminders(self, changes: dict[str, str | None], token: str) -> None:
        """Écrit les créneaux modifiés.

        `None` écrit une **cellule vide**, qui est l'extinction du rappel. Les clés
        absentes du dictionnaire ne sont pas touchées.
        """
        await self._settings.update_keys(
            {f"{SETTING_PREFIX}{name}": value or "" for name, value in changes.items()},
            token,
        )

    # ── Journal d'envoi (`NOT-02`) ────────────────────

    async def sent_on(self, day: date) -> frozenset[ReminderKind]:
        """Types déjà envoyés **ce jour-là**, lus dans le fichier.

        C'est ce qui rend un redémarrage sans effet : la mémoire de l'ordonnanceur est un
        fichier, pas une variable de processus.

        Le jour est **fourni**, jamais relu de l'horloge. C'est ce qui manquait à la
        première version, et un test l'a attrapé : l'ordonnanceur décidait du créneau avec
        son horloge injectée et consultait sa mémoire avec `today_local()`. Les deux
        s'accordent en production, mais une passe qui commence à 23 h 59 et écrit à
        00 h 00 rangerait le rappel sous le mauvais jour — donc l'enverrait deux fois, ou
        pas du tout.
        """
        known = {kind.value for kind in ReminderKind}
        return frozenset(
            ReminderKind(row.model.kind)
            for row in await self._sent.read_all()
            if row.model.date == day and row.model.kind in known
        )

    async def record(self, kind: ReminderKind, *, moment: datetime) -> None:
        """Consigne un envoi. En ajout, jamais en réécriture (`STO-03`).

        Le jour vient de l'instant fourni, pour la raison écrite dans `sent_on` : une seule
        horloge par passe, sinon la frontière du jour se traverse au milieu.
        """
        await self._sent.append(SentRow(date=moment.date(), kind=kind.value, sent_at=moment))

    # ── Envoi ─────────────────────────────────────────

    async def deliver(self, sender: PushSender, payload: dict[str, str]) -> int:
        """Remet une charge utile à tous les appareils abonnés. Rend le nombre de succès.

        Prend une charge utile et non un `Reminder` : la notification d'essai n'est pas un
        rappel, et lui faire emprunter un `ReminderKind` lui donnerait le `tag` d'un vrai
        créneau — donc **remplacerait** un rappel de suppléments dans le centre de
        notifications par un message d'essai.

        Les abonnements révoqués sont retirés en une écriture. Une panne de transport, en
        revanche, laisse la ligne en place : elle se retentera au prochain créneau.
        """
        livres = 0
        revoques: list[str] = []

        for subscription in await self.subscriptions():
            try:
                await sender.send(
                    endpoint=subscription.endpoint,
                    p256dh=subscription.p256dh,
                    auth=subscription.auth,
                    payload=payload,
                )
                livres += 1
            except PushGoneError:
                revoques.append(subscription.endpoint)
            except Exception:
                # Un appareil injoignable n'arrête pas les autres, et son abonnement est
                # **conservé** : c'est une panne de transport, pas une révocation.
                continue

        await self.forget(revoques)
        return livres


def _render(slot: time | None) -> str | None:
    """Un créneau sous sa forme `HH:MM`, ou `None` quand le rappel est éteint."""
    return f"{slot:%H:%M}" if slot is not None else None


__all__ = ["SETTING_PREFIX", "NotificationService", "device_label", "setting_key"]
