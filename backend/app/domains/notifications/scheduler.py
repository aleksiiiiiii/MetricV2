"""L'ordonnanceur des rappels (`NOT-02`).

Il **coud** : il lit les fichiers, demande à `reminders.py` — qui est pur — ce qui est dû,
envoie, et consigne. Aucune règle de rappel ne vit ici. C'est le même partage que
`heatmap/grids.py` vis-à-vis de `heatmap/engine.py`, et il a la même conséquence pratique :
ce qui décide se teste sur des valeurs fixes, ce qui lit se teste contre un faux WebDAV.

── Deux découpages qui rendent ce fichier testable ───────────────────────────

**`tick()` fait une passe, `run()` boucle.** Un test appelle `tick()` avec l'instant qu'il
veut et lit ce qui est parti ; il ne dort jamais. Sans cette séparation, `L15-06`
deviendrait un test qui attend une minute pour vérifier qu'il ne s'est rien passé — ce qui
ne vérifie rien et ralentit `make check` pour tout le monde.

**L'horloge est injectable**, comme celle de `ModelCatalogue`. Deux horloges, et elles ne
servent pas à la même chose :

* `now` — l'heure **locale** du mur, qui dit quel jour on est et quel créneau est passé.
  Elle vient de `app.core.dates.now_local`, jamais d'UTC : un rappel de 20 h est un rappel
  de 20 h à Paris, et la frontière du jour est celle de l'horloge de l'utilisateur
  (`HEAT-32`).
* `sleep` — l'attente entre deux passes, pour que la boucle s'éprouve sans faire passer
  une minute réelle.

── Ce que l'ordonnanceur ne fait pas ────────────────────────────────────────

Il ne rattrape pas au-delà d'une heure, il n'envoie jamais deux fois le même créneau dans
la même journée, il n'envoie pas plus de dix notifications par jour ni deux à moins de
quinze minutes d'intervalle, et il ne démarre pas du tout sans clé VAPID. Les trois sont des décisions
de conception, pas des optimisations : **un rappel qui arrive au mauvais moment se
désinstalle en un geste et ne revient jamais.**
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time

from app.core.dates import now_local
from app.domains.activity.service import RunService, WorkoutService
from app.domains.hydration.service import HydrationService
from app.domains.notifications.push import PushSender
from app.domains.notifications.reminders import (
    DaySnapshot,
    ReminderKind,
    allowed,
    compose,
    parse_slots,
    pending,
)
from app.domains.notifications.service import NotificationService, setting_key
from app.domains.nutrition.service import NutritionService
from app.domains.supplements.service import SupplementService
from app.storage.files import FileStore

logger = logging.getLogger(__name__)

#: Intervalle entre deux passes.
#:
#: Soixante secondes : un créneau se règle à la minute, le mesurer plus finement n'apporte
#: rien, et plus grossièrement décalerait visiblement un rappel de 20 h. Une passe ne coûte
#: qu'une lecture de `settings.csv` — servie par le cache la plupart du temps — tant
#: qu'aucun créneau n'est atteint.
INTERVAL = 60.0


class ReminderScheduler:
    """Envoie les rappels dus, une passe à la fois."""

    def __init__(
        self,
        store: FileStore,
        sender: PushSender,
        *,
        now: Callable[[], datetime] = now_local,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        interval: float = INTERVAL,
    ) -> None:
        self._store = store
        self._sender = sender
        self._now = now
        self._sleep = sleep
        self._interval = interval
        self._task: asyncio.Task[None] | None = None

        # Créneaux atteints dont il n'y avait **rien à dire** — tout était déjà noté.
        #
        # En mémoire et non dans le fichier, et la distinction est réfléchie : `sent.csv`
        # répond à « quand ai-je été rappelé », et y écrire une ligne pour un rappel qui
        # n'est jamais parti rendrait cette réponse fausse. Ce qu'on économise ici, c'est
        # de relire cinq domaines à chaque minute de la fenêtre de rattrapage ; l'oublier
        # au redémarrage ne coûte qu'une lecture de plus.
        self._quiet: set[tuple[date, ReminderKind]] = set()

    # ── Une passe ─────────────────────────────────────

    async def tick(self) -> list[ReminderKind]:
        """Une passe. Rend les types effectivement envoyés."""
        service = NotificationService(self._store)
        moment = self._now()

        slots = await self._slots(service)
        if not any(slots.values()):
            return []

        already = await service.sent_on(moment.date())
        attendus = [
            checkpoint
            for checkpoint in pending(slots=slots, now=moment, already_sent=already)
            if (moment.date(), checkpoint.kind) not in self._quiet
        ]
        if not attendus:
            return []

        # L'état du jour n'est lu **qu'ici**, une seule fois, et seulement parce qu'un
        # créneau est atteint.
        snapshot = await self._snapshot(moment.date())
        envoyes: list[ReminderKind] = []
        partis, dernier = await service.budget_on(moment.date())

        for checkpoint in attendus:
            reminder = compose(checkpoint.kind, snapshot)
            if reminder is None:
                # Rien à dire — tout est noté, ou l'écart est trop petit pour valoir une
                # notification. Le type se tait pour **toute la journée** : l'état du jour
                # ne se relit qu'une fois par passe, et le rouvrir à chaque contrôle
                # coûterait cinq lectures WebDAV pour une réponse qui n'a pas bougé.
                #
                # Conséquence assumée : si l'écart d'hydratation redevient important entre
                # 14 h et 18 h, on ne le dira pas. Ça ne peut arriver qu'en effaçant une
                # prise — un cas où se taire est le bon choix.
                self._quiet.add((moment.date(), checkpoint.kind))
                continue

            # **Le budget se demande juste avant d'envoyer, jamais avant de composer.**
            # Un rappel qui n'avait rien à dire est clos pour la journée ; un rappel
            # repoussé doit revenir. Les distinguer après `compose` est la seule façon de
            # ne pas taire le second par accident.
            if not allowed(now=moment, sent_today=partis, last_sent=dernier):
                # Rien n'est marqué : il redeviendra dû à la passe suivante, tant que
                # `GRACE` n'est pas dépassée. Et on sort — les suivants sont soumis au
                # même délai, les examiner ne ferait que relire la même réponse.
                logger.info("rappel %s repoussé : budget du jour", checkpoint.kind.value)
                break

            livres = await service.deliver(self._sender, reminder.payload())
            # Consigné même si aucun appareil n'était joignable : le créneau a bien été
            # traité pour la journée, et réessayer à la minute suivante enverrait en
            # rafale dès qu'un téléphone se rallume.
            await service.record(checkpoint, moment=moment)
            # Le budget est tenu **en mémoire pour le reste de la passe** : le relire du
            # fichier après chaque envoi coûterait un aller-retour WebDAV par notification,
            # pour une valeur qu'on vient d'écrire soi-même.
            partis += 1
            dernier = moment
            envoyes.append(checkpoint.kind)
            logger.info(
                "rappel %s (%s) envoyé à %d appareil(s)",
                checkpoint.kind.value,
                f"{checkpoint.at:%H:%M}",
                livres,
            )

        return envoyes

    # ── Lectures ──────────────────────────────────────

    async def _slots(self, service: NotificationService) -> dict[ReminderKind, tuple[time, ...]]:
        """Les contrôles configurés, par type. Un horaire illisible vaut éteint.

        Une **liste** et non une heure : l'hydratation en porte trois (**N2**), séparées
        par des virgules, comme `hydration_presets_ml` le fait déjà pour ses volumes. Les
        types à un seul contrôle rendent un tuple d'un élément — la forme est la même pour
        tous, et il n'y a pas deux façons de lire un réglage.
        """
        values = await service.raw_settings()
        return {kind: parse_slots(values.get(setting_key(kind), "")) for kind in ReminderKind}

    async def _snapshot(self, day: date) -> DaySnapshot:
        """Ce que l'application **sait** du jour.

        Chaque source est un service existant : on ne réécrit ni calendrier de
        suppléments, ni total d'hydratation, ni compte de repas. `SupplementService.checklist`
        sait déjà ce qui est dû ce jour-là et ce qui est pris — le rappel ne cite donc que
        **ce qui reste**, et n'invente pas un second calendrier qui divergerait du premier.
        """
        # Import tardif, et ce n'est pas un goût : `planning.service` et `goals.router`
        # se citent l'un l'autre — `DEFAULT_ADHERENCE_WEEKS` d'un côté, `GoalService` de
        # l'autre. Le cycle ne se résout aujourd'hui que parce que `app/domains/api.py`
        # importe `goals` **avant** `planning`, par ordre alphabétique. Charger
        # `planning.service` en premier depuis ce module lève un `ImportError`.
        #
        # Le défaut est réel et **antérieur à ce lot** ; le corriger demande de déplacer
        # une constante ou d'inverser une dépendance entre deux domaines livrés, ce qui
        # n'a pas sa place ici. Ce module se contente de ne pas s'appuyer sur un ordre
        # d'import — il est noté au §7 du ROADMAP.
        from app.domains.planning.service import PlanningService

        checklist = await SupplementService(self._store).checklist(day)
        eau = await HydrationService(self._store).summary(day)
        repas = await NutritionService(self._store).totals(day)
        prevues = await PlanningService(self._store).between(day, day)

        # Le « réalisé » se compte chez le domaine Activité, comme le fait `PLAN-06` : une
        # course et une séance de musculation comptent toutes deux comme une séance faite.
        runs = [row for row in await RunService(self._store).all() if row.model.date == day]
        workouts = [row for row in await WorkoutService(self._store).all() if row.model.date == day]

        return DaySnapshot(
            supplements_pending=tuple(item.name for item in checklist.items if not item.taken),
            hydration_ml=eau.today_ml,
            hydration_target_ml=eau.target_ml,
            meals_logged=repas.meals,
            protein_g=repas.protein_g,
            protein_target_g=repas.protein_target_g,
            workouts_planned=len(prevues),
            workouts_logged=len(runs) + len(workouts),
        )

    # ── Cycle de vie ──────────────────────────────────

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Une passe qui échoue n'arrête pas l'ordonnanceur : Nextcloud peut être
                # injoignable une minute, et les rappels du soir n'ont aucune raison de
                # disparaître parce que celui du matin a rencontré un problème.
                logger.exception("passe de rappels échouée")
            await self._sleep(self._interval)

    def start(self) -> None:
        """Démarre la boucle en tâche de fond."""
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="rappels")

    async def stop(self) -> None:
        """Arrête la boucle et attend qu'elle ait rendu la main."""
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None


__all__ = ["INTERVAL", "ReminderScheduler"]
