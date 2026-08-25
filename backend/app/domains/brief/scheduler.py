"""L'ordonnanceur de la lecture du jour.

Il **coud**, comme celui des rappels : il regarde l'heure, demande au service ce qui a déjà
été écrit, et déclenche une génération si le jour n'a pas la sienne. Aucune règle de
rédaction ne vit ici — elle est dans `compose.py`, qui est pur.

── Deux découpages qui rendent ce fichier testable ───────────────────────────

**`tick()` fait une passe, `run()` boucle.** Un test appelle `tick()` avec l'instant qu'il
veut et lit ce qui s'est écrit ; il ne dort jamais. C'est le même partage que
`notifications/scheduler.py`, et il évite le même piège : une batterie qui attendrait une
heure pour vérifier qu'il ne s'est rien passé ne vérifie rien.

**L'horloge est injectable.** `now_local` et non UTC : « la lecture du matin » est une
notion d'heure locale, et la frontière du jour est celle de l'horloge de l'utilisateur
(`HEAT-32`).

── Pourquoi il ne vit pas avec l'ordonnanceur des rappels ───────────────────

`ReminderScheduler` ne démarre **pas sans paire VAPID** — c'est correct pour lui, il
n'aurait personne à qui envoyer. La lecture du jour n'a rien à voir avec le push : elle
s'affiche sur une carte, et la lier au réglage des notifications reviendrait à faire
dépendre un écran d'une clé qui n'a rien à faire là. Deux tâches de fond, deux conditions
de démarrage, et la seconde ne demande qu'une clé OpenRouter et un stockage.

── Ce que cet ordonnanceur ne fait pas ──────────────────────────────────────

Il n'écrit **qu'un créneau par passe**. Ouvrir l'application à vingt heures après une
journée sans passe ne doit pas déclencher trois appels de modèle d'affilée ; l'intervalle
est d'une heure, et les deux autres suivront.

Il ne réessaie pas dans la minute. Un modèle gratuit indisponible le reste souvent
plusieurs minutes, et la passe suivante viendra de toute façon ; entre-temps, la carte
porte son bouton et l'utilisateur n'attend pas après nous. Il ne rattrape pas non plus les
jours passés : une lecture du 12 août écrite le 19 commenterait des chiffres qui ont
changé, ce qui est exactement ce qu'un condensé daté existe pour empêcher.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, time

from app.core.dates import now_local
from app.domains.ai.service import AiService
from app.domains.brief.models import SLOT_HOURS, due_slots
from app.domains.brief.service import BriefService
from app.domains.planning.service import DEFAULT_ADHERENCE_WEEKS, PlanningService
from app.storage.files import FileStore

logger = logging.getLogger(__name__)

#: Intervalle entre deux passes.
#:
#: Une heure, et non une minute comme les rappels : une lecture du jour n'a pas de créneau
#: à respecter à la minute près, et une passe coûte une lecture de `insights/brief.csv`.
#: Ouvrir l'application avant la première passe n'est pas un problème — la carte porte son
#: bouton, qui écrit la même ligne par le même chemin.
INTERVAL = 3600.0

#: Heure locale du premier créneau, gardée pour les appelants qui la nommaient.
#:
#: Les trois heures vivent maintenant dans `models.SLOT_HOURS` : le service en a besoin
#: aussi — c'est lui qui décide quel créneau afficher quand l'écran n'en demande aucun — et
#: deux tables donneraient deux idées de « il est midi ».
FLOOR = SLOT_HOURS["matin"]


class BriefScheduler:
    """Écrit la lecture du jour une fois par jour, si elle manque."""

    def __init__(
        self,
        store: FileStore,
        ai: AiService,
        *,
        now: Callable[[], datetime] = now_local,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        interval: float = INTERVAL,
        floor: time = FLOOR,
    ) -> None:
        self._store = store
        self._ai = ai
        self._now = now
        self._sleep = sleep
        self._interval = interval
        self._floor = floor
        self._task: asyncio.Task[None] | None = None

    # ── Une passe ─────────────────────────────────────

    async def tick(self) -> bool:
        """Une passe. Rend vrai si une lecture vient d'être écrite.

        **Un créneau par passe, le plus ancien manquant.** Ouvrir l'application à vingt
        heures après une journée sans passe ne doit pas déclencher trois appels de modèle
        d'affilée : l'intervalle est d'une heure, les deux autres suivront, et la carte
        montre de toute façon le créneau en cours.

        Les créneaux dépassés se rattrapent donc dans la journée mais **pas d'un jour sur
        l'autre** : le service ne connaît que la date qu'on lui donne, et une lecture de
        midi écrite à minuit commenterait des chiffres qui ont bougé — exactement ce qu'un
        condensé daté existe pour empêcher.
        """
        moment = self._now()
        service = BriefService(self._store)

        for slot in due_slots(moment):
            # La vue **avant** l'écart plan / réalisé : dans le cas courant — la lecture
            # est déjà là — cette passe ne coûte qu'une lecture de fichier, et construire
            # le taux de respect pour le jeter serait quatre lectures de plus par créneau.
            if (await service.view(today=moment.date(), slot=slot)).state == "ready":
                continue

            adherence = await PlanningService(self._store).adherence(
                today=moment.date(), weeks=DEFAULT_ADHERENCE_WEEKS
            )
            await service.generate(
                self._ai, adherence=adherence, today=moment.date(), now=moment, slot=slot
            )
            logger.info("lecture « %s » écrite pour le %s", slot, moment.date().isoformat())
            return True

        return False

    # ── Cycle de vie ──────────────────────────────────

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Une passe qui échoue n'arrête pas l'ordonnanceur : un modèle gratuit
                # saturé ou un Nextcloud injoignable une heure n'ont aucune raison de
                # priver l'écran de toutes les lectures suivantes.
                logger.exception("passe de lecture du jour échouée")
            await self._sleep(self._interval)

    def start(self) -> None:
        """Démarre la boucle en tâche de fond."""
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="lecture-du-jour")

    async def stop(self) -> None:
        """Arrête la boucle et attend qu'elle ait rendu la main."""
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None


__all__ = ["FLOOR", "INTERVAL", "BriefScheduler"]
