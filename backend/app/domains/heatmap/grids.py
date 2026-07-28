"""Lecture des grilles : de la configuration au moteur (`HEAT-24` → `HEAT-29`).

Ce module est la couture entre deux mondes. D'un côté `TrackService`, qui sait lire des
fichiers de configuration ; de l'autre `engine`, qui ne sait rien lire du tout mais juge
juste. Ici on rassemble les ingrédients — cadence applicable jour par jour, plages
neutralisées, agrégat quotidien, déclencheurs — et on appelle le moteur.

Aucune règle d'assiduité ne vit dans ce fichier, et c'est volontaire : une règle écrite
ici échapperait à la batterie de tests du moteur, qui est ce sur quoi repose la justesse
du projet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.core.cadence import Cadence, CadenceType
from app.core.dates import today_local
from app.domains.activity.service import RunService, WorkoutService
from app.domains.heatmap.engine import (
    Grid,
    OffRange,
    Range,
    TrackRules,
    default_range,
    evaluate,
)
from app.domains.heatmap.models import TrackRow
from app.domains.heatmap.service import TrackService, levels_from_text
from app.domains.heatmap.sources import DayDetail, daily_values, explain_day
from app.storage.files import FileStore

#: Déclencheur reconnu par la cadence `conditional` : « les jours où j'ai bougé ».
TRIGGER_WORKOUT = "workout"


@dataclass(frozen=True, slots=True)
class TrackGrid:
    """Une grille et la piste qui l'a produite."""

    track: TrackRow
    grid: Grid


class GridService:
    """Grilles et statistiques d'assiduité."""

    def __init__(self, store: FileStore) -> None:
        self._store = store
        self._tracks = TrackService(store)

    async def grid(
        self, track_id: str, *, window: Range | None = None, today: date | None = None
    ) -> TrackGrid:
        row = await self._tracks.resolve(track_id)
        moment = today or today_local()
        return TrackGrid(
            track=row.model,
            grid=await self._evaluate(row.model, window or default_range(moment), moment),
        )

    async def grids(
        self,
        track_ids: list[str] | None = None,
        *,
        window: Range | None = None,
        today: date | None = None,
    ) -> list[TrackGrid]:
        """Plusieurs grilles sur la même plage (`HEAT-25`).

        Neuf grilles sur un écran, c'est neuf fois les mêmes fichiers sources. Le cache de
        `FileStore` les sert une seule fois par requête (`STO-06`), ce qui rend la lecture
        groupée réellement moins chère que neuf appels — et pas seulement plus discrète.
        """
        moment = today or today_local()
        span = window or default_range(moment)
        wanted = set(track_ids) if track_ids else None

        return [
            TrackGrid(track=row.model, grid=await self._evaluate(row.model, span, moment))
            for row in await self._tracks.rows()
            if wanted is None or row.model.id in wanted
        ]

    async def day(self, track_id: str, day: date) -> list[DayDetail]:
        """Détail sous-jacent d'une cellule (`HEAT-29`)."""
        row = await self._tracks.resolve(track_id)
        return await explain_day(self._store, row.model.source, row.model.filter, day)

    # ── Interne ───────────────────────────────────────

    async def _evaluate(self, track: TrackRow, window: Range, today: date) -> Grid:
        values = await daily_values(self._store, track.source, track.filter)
        cadences = await self._cadences(track, window, today)

        return evaluate(
            rules=TrackRules(
                validation_threshold=track.validation_threshold,
                levels=levels_from_text(track.levels),
                binary=track.binary,
                created=track.created,
            ),
            cadence_at=cadences,
            values=values,
            window=window,
            today=today,
            off_ranges=[
                OffRange(start=model.date_from, end=model.date_to)
                for model in await self._tracks.neutralised(track.id)
                if model.date_from is not None and model.date_to is not None
            ],
            triggers=await self._triggers(cadences),
        )

    async def _cadences(self, track: TrackRow, window: Range, today: date) -> dict[date, Cadence]:
        """Cadence applicable à **chaque** jour de la plage (`HEAT-14`).

        Le moteur ne connaît pas le journal des prises d'effet : on lui remet une table
        déjà résolue. C'est ce qui permet de le tester avec un dictionnaire écrit à la
        main, et d'y faire entrer un changement de cadence à mi-historique sans monter
        de dépôt.
        """
        return await self._tracks.cadences_for(track.id, [*window.days(), today])

    async def _triggers(self, cadences: dict[date, Cadence]) -> set[date]:
        """Jours où le déclencheur d'une cadence `conditional` est vrai (`HEAT-12`).

        Un seul déclencheur est reconnu pour l'instant — « j'ai bougé ce jour-là » —, et
        c'est le cas d'usage nommé par la spec : le supplément péri-entraînement, qui
        n'est pas manqué les jours de repos parce qu'il n'y était pas attendu.
        """
        triggers = {
            str(cadence.params.get("trigger", ""))
            for cadence in cadences.values()
            if cadence.type is CadenceType.CONDITIONAL
        }
        if TRIGGER_WORKOUT not in triggers:
            # Déclencheur inconnu : aucun jour n'est attendu, donc aucun n'est manqué.
            # Se tromper vers `off` est le sens sûr — l'inverse peindrait en rouge un an
            # d'historique à cause d'une faute de frappe dans un fichier de réglages.
            return set()

        days = {row.model.date for row in await RunService(self._store).all()}
        days |= {row.model.date for row in await WorkoutService(self._store).all()}
        return days
