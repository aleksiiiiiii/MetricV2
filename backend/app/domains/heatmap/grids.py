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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from app.core.cadence import Cadence, CadenceType
from app.core.dates import today_local
from app.domains.activity.service import RunService, WorkoutService
from app.domains.heatmap.cache import GridCache, GridKey
from app.domains.heatmap.engine import (
    Day,
    DayState,
    Grid,
    OffRange,
    Range,
    TrackRules,
    default_range,
    evaluate,
)
from app.domains.heatmap.models import TrackRow
from app.domains.heatmap.schemas import (
    DayEntry,
    DayInspection,
    DayView,
    GridsView,
    GridTrack,
    GridView,
    RangeView,
    StatsView,
    TrackImpact,
    TrackUpdate,
    WeekView,
)
from app.domains.heatmap.service import TrackService, cadence_view, levels_from_text
from app.domains.heatmap.sources import (
    SEPARATOR,
    SOURCES,
    DayDetail,
    daily_values,
    explain_day,
    source_paths,
)
from app.storage.files import FileStore
from app.storage.paths import (
    HEATMAP_CADENCES,
    HEATMAP_OFF_DAYS,
    HEATMAP_TRACKS,
    RUNS,
    WORKOUTS,
)

#: Déclencheur reconnu par la cadence `conditional` : « les jours où j'ai bougé ».
TRIGGER_WORKOUT = "workout"

#: Fichiers que toute grille ouvre, quelle que soit sa source : la piste elle-même, son
#: journal de cadences, ses plages neutralisées. `RUNS` et `WORKOUTS` s'y ajoutent parce
#: qu'une cadence `conditional` y cherche ses déclencheurs (`HEAT-12`) — et qu'on ne sait
#: qu'après avoir lu le journal si l'une d'elles en est une.
COMMON_PATHS = (HEATMAP_TRACKS, HEATMAP_CADENCES, HEATMAP_OFF_DAYS, RUNS, WORKOUTS)


def _dependencies(tracks: Iterable[TrackRow]) -> set[str]:
    """Fichiers à ouvrir pour évaluer ces pistes.

    Sert **uniquement** au préchargement. Se tromper ici coûte un aller-retour de plus ou
    de moins, jamais une grille fausse : la validité du cache s'appuie sur les lectures
    réellement observées, pas sur cette liste.
    """
    return {*COMMON_PATHS, *(path for track in tracks for path in source_paths(track.source))}


@dataclass(frozen=True, slots=True)
class TrackGrid:
    """Une grille et la piste qui l'a produite."""

    track: TrackRow
    grid: Grid


class GridService:
    """Grilles et statistiques d'assiduité."""

    def __init__(self, store: FileStore, cache: GridCache | None = None) -> None:
        self._store = store
        self._tracks = TrackService(store)
        # Sans cache partagé, le service reste juste : il recalcule, simplement. C'est ce
        # qui permet aux tests du moteur et de la couture de l'ignorer complètement.
        self._cache = cache

    async def grid(
        self, track_id: str, *, window: Range | None = None, today: date | None = None
    ) -> TrackGrid:
        row = await self._tracks.resolve(track_id)
        moment = today or today_local()
        span = window or default_range(moment)

        await self._store.prefetch(_dependencies([row.model]))
        return TrackGrid(track=row.model, grid=await self._evaluate(row.model, span, moment))

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

        Les fichiers sont ouverts **en parallèle** avant d'évaluer quoi que ce soit. À
        ~180 ms d'aller-retour sur l'instance réelle, sept fichiers lus l'un après l'autre
        font plus d'une seconde d'attente pour un écran qui, le plus souvent, n'a même
        rien à recalculer.
        """
        moment = today or today_local()
        span = window or default_range(moment)
        wanted = set(track_ids) if track_ids else None

        rows = [
            row for row in await self._tracks.rows() if wanted is None or row.model.id in wanted
        ]
        await self._store.prefetch(_dependencies(row.model for row in rows))

        return [
            TrackGrid(track=row.model, grid=await self._evaluate(row.model, span, moment))
            for row in rows
        ]

    async def day(self, track_id: str, day: date) -> list[DayDetail]:
        """Détail sous-jacent d'une cellule (`HEAT-29`)."""
        row = await self._tracks.resolve(track_id)
        return await explain_day(self._store, row.model.source, row.model.filter, day)

    # ── Formes publiées (spec §8) ─────────────────────

    async def view(
        self, track_id: str, *, window: Range | None = None, today: date | None = None
    ) -> GridView:
        """Grille d'une piste, telle que l'API la rend (`HEAT-24`)."""
        return grid_view(await self.grid(track_id, window=window, today=today))

    async def multi_view(
        self,
        track_ids: list[str] | None = None,
        *,
        window: Range | None = None,
        today: date | None = None,
    ) -> GridsView:
        """Toutes les grilles d'un écran en une réponse (`HEAT-25`)."""
        moment = today or today_local()
        span = window or default_range(moment)
        items = await self.grids(track_ids, window=span, today=moment)
        return GridsView(range=range_view(span), grids=[grid_view(item) for item in items])

    async def inspect(
        self, track_id: str, day: date, *, today: date | None = None
    ) -> DayInspection:
        """Cellule explorable : son état, et ce qui le compose (`HEAT-29`).

        La plage évaluée est **le seul jour demandé**. C'est exact et non une
        approximation : le moteur charge de lui-même la marge amont dont une fenêtre
        glissante a besoin pour se prononcer sur sa première colonne.
        """
        moment = today or today_local()
        item = await self.grid(track_id, window=Range(day, day), today=moment)
        entries = await explain_day(self._store, item.track.source, item.track.filter, day)

        return DayInspection(
            track=track_descriptor(item.track),
            day=day_view(item.grid.days[0]),
            entries=[entry_view(entry) for entry in entries],
        )

    # ── Simulation d'une modification (`HEAT-20`, **D4**) ──

    async def impact(
        self, track_id: str, payload: TrackUpdate, *, today: date | None = None
    ) -> TrackImpact:
        """Chiffre ce qu'une modification ferait à l'historique, sans rien écrire.

        La méthode est celle que la spec décrit : évaluer la grille deux fois — telle
        qu'elle est, puis telle qu'elle serait — et comparer les états jour par jour.

        La **cadence du payload est ignorée** ici, et ce n'est pas un oubli : changer une
        cadence ne vaut que pour l'avenir (`HEAT-14`), donc la simuler sur le passé
        annoncerait un bouleversement qui n'aura pas lieu. Seul ce qui redéfinit « validé »
        rejuge l'historique.
        """
        row = await self._tracks.resolve(track_id)
        moment = today or today_local()
        window = default_range(moment)

        before = row.model
        after = before.model_copy(
            update={
                "source": payload.source,
                "filter": payload.filter,
                "validation_threshold": payload.validation_threshold,
                "levels": SEPARATOR.join(f"{value:g}" for value in payload.levels),
                "binary": payload.binary,
            }
        )
        if _same_judgement(before, after):
            return TrackImpact(
                retroactive=False,
                range=range_view(window),
                changed_days=0,
                to_missed=0,
                to_done=0,
                restyled=0,
            )

        await self._store.prefetch(_dependencies([before, after]))
        was = await self._compute(before, window, moment)
        would = await self._compute(after, window, moment)

        return _impact(was, would, window)

    # ── Interne ───────────────────────────────────────

    async def _evaluate(self, track: TrackRow, window: Range, today: date) -> Grid:
        """Grille d'une piste, mémorisée tant que ses sources n'ont pas bougé (`HEAT-33`)."""
        if self._cache is None:
            return await self._compute(track, window, today)

        key = GridKey(track_id=track.id, start=window.start, end=window.end, today=today)
        entry = self._cache.get(key)
        if entry is not None and await self._unchanged(entry.fingerprint):
            self._cache.record(hit=True)
            return entry.grid

        self._cache.record(hit=False)
        with self._store.observe() as fingerprint:
            # La ligne de la piste a été lue **avant** d'entrer ici, par `resolve` ou
            # `rows`. La relire — le cache la sert sans réseau — est ce qui fait entrer
            # `heatmap_tracks.csv` dans l'empreinte : sans elle, un seuil de validation
            # modifié laisserait la grille précédente valide, et `HEAT-20` promet
            # exactement l'inverse.
            await self._store.read(HEATMAP_TRACKS)
            grid = await self._compute(track, window, today)

        self._cache.store(key, grid, fingerprint)
        return grid

    async def _unchanged(self, fingerprint: Mapping[str, str]) -> bool:
        """Vrai si tous les fichiers de l'empreinte portent encore la même version.

        La lecture passe par `FileStore` : gratuite pendant son TTL, un `304` ensuite.
        On paie donc la fraîcheur en revalidations et jamais en recalculs — et un fichier
        modifié depuis un tableur est vu au plus tard une trentaine de secondes après
        (décision **D8**).
        """
        for path, mark in fingerprint.items():
            if (await self._store.read(path)).mark != mark:
                return False
        return True

    async def _compute(self, track: TrackRow, window: Range, today: date) -> Grid:
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


# ── Du moteur au contrat (spec §8) ────────────────────
#
# Rien ici ne décide : on renomme et on met en forme. La frontière est nette et vaut
# d'être tenue — le jour où une de ces fonctions se mettrait à choisir un état, la
# batterie de tests du moteur cesserait de couvrir ce que voit l'utilisateur.


def range_view(window: Range) -> RangeView:
    return RangeView(from_=window.start, to=window.end)


def day_view(day: Day) -> DayView:
    return DayView(
        date=day.date,
        value=day.value,
        state=str(day.state),
        level=day.level,
        reason=None if day.reason is None else str(day.reason),
    )


def track_descriptor(track: TrackRow) -> GridTrack:
    source = SOURCES.get(track.source)
    return GridTrack(
        id=track.id,
        label=track.label or track.id,
        unit=source.unit if source else "",
        binary=track.binary,
        accent=track.accent,
        source=track.source,
        levels=[] if track.binary else levels_from_text(track.levels),
        validation_threshold=track.validation_threshold,
        created=track.created,
    )


def grid_view(item: TrackGrid) -> GridView:
    grid = item.grid
    stats = grid.stats

    return GridView(
        track=track_descriptor(item.track),
        # La cadence est celle du dernier jour évalué, et elle est **servie décrite** :
        # « un jour sur deux » se formule ici, pas dans le frontend (`HEAT-30`).
        cadence=cadence_view(grid.cadence, None),
        range=range_view(grid.range),
        days=[day_view(day) for day in grid.days],
        weeks=(
            None
            if grid.weeks is None
            else [
                WeekView(
                    start=week.week_start,
                    status=str(week.status),
                    done=week.done,
                    expected=week.expected,
                )
                for week in grid.weeks
            ]
        ),
        stats=StatsView(
            validated_days=stats.validated_days,
            expected_days=stats.expected_days,
            compliance=stats.compliance,
            longest_streak=stats.longest_streak,
            current_streak=stats.current_streak,
            best_day=stats.best_day,
            best_value=stats.best_value,
            total=stats.total,
        ),
    )


def _same_judgement(before: TrackRow, after: TrackRow) -> bool:
    """Vrai si les deux configurations jugent un jour de la même façon.

    Le seuil, les bornes d'intensité et le mode binaire disent ce que « validé » signifie ;
    la source et le filtre disent sur quoi. Changer l'un des cinq rejuge le passé — et
    `TrackService.update` retenait les trois premiers seulement, si bien que rebrancher
    une piste sur une autre source réécrivait l'historique sans le dire.
    """
    return (
        before.source == after.source
        and before.filter == after.filter
        and before.validation_threshold == after.validation_threshold
        and before.levels == after.levels
        and before.binary == after.binary
    )


def _impact(was: Grid, would: Grid, window: Range) -> TrackImpact:
    """Compare deux grilles de la même piste, jour par jour."""
    validated = (DayState.DONE, DayState.BONUS)

    to_missed = to_done = changed = restyled = 0
    for before, after in zip(was.days, would.days, strict=True):
        if before.state is after.state:
            restyled += before.level != after.level
            continue
        changed += 1
        to_missed += before.state in validated and after.state is DayState.MISSED
        to_done += before.state is DayState.MISSED and after.state in validated

    warnings: list[str] = []
    if to_missed:
        warnings.append(
            f"{to_missed} "
            + ("journée passerait" if to_missed == 1 else "journées passeraient")
            + " de validée à manquée."
        )
    if to_done:
        warnings.append(
            f"{to_done} "
            + ("journée passerait" if to_done == 1 else "journées passeraient")
            + " de manquée à validée."
        )
    if restyled and not changed:
        # Le cas d'un gradient déplacé seul : rien ne change de camp, mais la grille
        # change d'aspect. Ne rien dire laisserait croire le réglage sans effet.
        warnings.append(
            f"{restyled} "
            + ("journée garderait" if restyled == 1 else "journées garderaient")
            + " leur état mais changeraient d'intensité."
        )
    if not changed and not restyled:
        warnings.append("Aucune journée passée ne changerait.")

    return TrackImpact(
        retroactive=True,
        range=range_view(window),
        changed_days=changed,
        to_missed=to_missed,
        to_done=to_done,
        restyled=restyled,
        warnings=warnings,
    )


def entry_view(entry: DayDetail) -> DayEntry:
    return DayEntry(
        label=entry.label,
        value=entry.value,
        unit=entry.unit,
        time=entry.time,
        sets=entry.sets,
        reps=entry.reps,
        weight_kg=entry.weight_kg,
        muscle_group=entry.muscle_group,
        distance_km=entry.distance_km,
        duration_min=entry.duration_min,
        pace_min_km=entry.pace_min_km,
        dose=entry.dose,
        dose_unit=entry.dose_unit,
        note=entry.note,
    )
