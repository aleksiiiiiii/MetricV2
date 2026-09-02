"""Écriture et lecture du domaine Activité (`ACT-01` → `ACT-09`, `ACT-17`).

Les agrégats hebdomadaires et les progressions vivent dans `stats.py` : ce module ne
s'occupe que du cycle de vie des lignes.
"""

from __future__ import annotations

import secrets
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta

from app.core.exceptions import AiUnreadableError, ValidationFailedError
from app.core.parsing import estimate_one_rep_max, pace_min_per_km
from app.core.text import fold, fr
from app.core.validation import today_local
from app.domains.activity import (
    circuit_link,
    composer,
    exercise_catalog,
    notes,
    progress,
    splits,
)
from app.domains.activity.models import (
    CircuitExerciseRow,
    CircuitLoadLogRow,
    CircuitLoadRow,
    CircuitRow,
    CircuitSessionRow,
    CircuitSessionSetRow,
    ExerciseLogRow,
    ExerciseRow,
    MuscleGroup,
    RunRow,
    RunSplitRow,
    WorkoutRow,
)
from app.domains.activity.schemas import (
    Circuit,
    CircuitDonePayload,
    CircuitExercise,
    CircuitExercisePayload,
    CircuitList,
    CircuitPayload,
    CircuitProposal,
    CircuitSuggestion,
    ComposeRequest,
    DistanceBand,
    Exercise,
    ExerciseEntry,
    ExerciseEntryPayload,
    ExercisePayload,
    Load,
    LoadDay,
    LoadDetail,
    LoadList,
    LoadPayload,
    LoadPoint,
    LoadState,
    MonthTotals,
    NeglectedGroup,
    NoteDraft,
    ProposedCircuitExercise,
    Run,
    RunContext,
    RunDetail,
    RunMark,
    RunPayload,
    RunProgress,
    RunSplit,
    RunSplits,
    RunWindow,
    Workout,
    WorkoutPayload,
)
from app.domains.ai.images import prepare_data_url
from app.domains.ai.service import AiService
from app.domains.app_settings.service import SettingsService
from app.storage.csv_repo import CsvRepository, Row
from app.storage.errors import StorageConflictError, StorageNotFoundError
from app.storage.files import FileStore
from app.storage.paths import (
    CIRCUIT_EXERCISES,
    CIRCUIT_LOAD_LOG,
    CIRCUIT_LOADS,
    CIRCUIT_SESSION_SETS,
    CIRCUIT_SESSIONS,
    CIRCUITS,
    EXERCISE_LOG,
    EXERCISES,
    RUN_SPLITS,
    RUNS,
    WORKOUTS,
)

#: Longueur des identifiants stables. Assez court pour rester lisible dans un tableur,
#: assez long pour qu'une collision soit hors de portée à l'échelle d'une vie de relevés.
ID_BYTES = 6


def new_id() -> str:
    return secrets.token_hex(ID_BYTES)


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


# ── Courses ───────────────────────────────────────────


class RunService:
    """Courses : saisie, allure dérivée, correction, paliers (`ACT-01`, `ACT-02`, `ACT-05`)."""

    def __init__(self, store: FileStore) -> None:
        self._repo: CsvRepository[RunRow] = CsvRepository(store, RUNS, RunRow)
        self._splits: CsvRepository[RunSplitRow] = CsvRepository(store, RUN_SPLITS, RunSplitRow)

    @staticmethod
    def to_schema(row: Row[RunRow], *, splits: int = 0) -> Run:
        model = row.model
        pace = model.pace_min_km or pace_min_per_km(model.distance_km, model.duration_min)
        return Run(
            id=row.index,
            token=row.token,
            date=model.date,
            distance_km=model.distance_km,
            duration_min=model.duration_min,
            pace_min_km=_round(pace, 3),
            speed_kmh=_round(60 / pace, 2) if pace else None,
            avg_hr=model.avg_hr,
            elevation_m=model.elevation_m,
            cadence_spm=model.cadence_spm,
            note=model.note,
            source=model.source,
            run_id=model.run_id,
            active_calories=model.active_calories,
            total_calories=model.total_calories,
            start_time=model.start_time,
            end_time=model.end_time,
            split_length_km=model.split_length_km,
            splits=splits,
        )

    @staticmethod
    def _to_row(payload: RunPayload, source: str = "manual", run_id: str = "") -> RunRow:
        """La ligne à écrire.

        Distance et allure arrivent **déjà accordées** : le schéma complète l'une depuis
        l'autre et refuse une saisie qui n'en porte aucune. Rien n'est recalculé ici, sans
        quoi la règle vivrait à deux endroits et divergerait au premier cas limite.

        L'allure est stockée avec la course : recalculable, mais la conserver rend le
        fichier lisible sans outil (`ACT-02`, `STO-02`).

        `run_id` est **reçu**, jamais tiré ici : une correction doit conserver celui de la
        ligne qu'elle remplace, sinon les paliers déjà écrits se détacheraient de leur
        course sans que rien ne le signale. C'est la règle que `workout_id` porte déjà.
        """
        # Le schéma garantit les deux ; l'assertion documente l'invariant pour le
        # vérificateur de types, qui ne peut pas le lire dans un `model_validator`.
        assert payload.distance_km is not None
        assert payload.pace_min_km is not None
        return RunRow(
            date=payload.date,
            distance_km=payload.distance_km,
            duration_min=payload.duration_min,
            pace_min_km=_round(payload.pace_min_km, 3),
            avg_hr=payload.avg_hr,
            elevation_m=payload.elevation_m,
            cadence_spm=payload.cadence_spm,
            note=payload.note,
            source=source,
            run_id=run_id,
            active_calories=payload.active_calories,
            total_calories=payload.total_calories,
            start_time=payload.start_time,
            end_time=payload.end_time,
            split_length_km=_round(payload.split_length_km, 3),
        )

    async def all(self) -> list[Row[RunRow]]:
        return await self._repo.read_all()

    async def get(self, index: int) -> Run:
        rows = await self._repo.read_all()
        if not 0 <= index < len(rows):
            raise StorageNotFoundError("Cette course n'existe pas.")
        row = rows[index]
        return self.to_schema(row, splits=len(await self._splits_of(row.model.run_id)))

    async def create(self, payload: RunPayload, *, source: str = "manual") -> Run:
        """Enregistre une course, et ses paliers s'il y en a (`ACT-19`, `IMP-05`).

        **La course s'écrit d'abord.** Le stockage est un dépôt CSV sur WebDAV et n'a pas
        de transaction : si les paliers échouent après elle, il reste une course entière
        sans ses paliers — une perte de détail. L'ordre inverse laisserait des paliers
        orphelins rattachés à un `run_id` qui n'existe nulle part, c'est-à-dire un fichier
        que rien ne vient jamais nettoyer.
        """
        run_id = new_id() if payload.splits else ""
        row = await self._repo.append(self._to_row(payload, source, run_id))

        written = 0
        if payload.splits:
            written = len(await self._splits.extend(_split_rows(run_id, payload)))
        return self.to_schema(row, splits=written)

    async def update(self, index: int, token: str, payload: RunPayload) -> Run:
        """Corrige une course. **Ses paliers ne bougent pas.**

        Une correction porte sur ce que le formulaire affiche — la date, la distance, la
        durée —, et le formulaire n'affiche pas les paliers. Les réécrire depuis un
        payload qui n'en porte aucun les effacerait à chaque correction de faute de frappe.
        Les remplacer demande de repasser par l'import, qui est le seul geste qui les lit.
        """
        rows = await self._repo.read_all(fresh=True)
        current = rows[index].model if 0 <= index < len(rows) else None
        source = current.source if current else "manual"
        run_id = current.run_id if current else ""

        row = await self._repo.replace_by_token(index, token, self._to_row(payload, source, run_id))
        return self.to_schema(row, splits=len(await self._splits_of(run_id)))

    async def delete(self, index: int, token: str) -> None:
        """Supprime une course **et ses paliers**.

        L'ordre compte, et c'est l'inverse de celui de la création : les paliers partent en
        premier. Si la suppression de la course échoue derrière, il reste une course sans
        détail — visible, corrigible, supprimable à nouveau. La laisser partir d'abord
        aurait laissé des paliers que plus aucune ligne ne désigne, et qu'aucun écran ne
        montre pour qu'on pense à les retirer.
        """
        rows = await self._repo.read_all(fresh=True)
        run_id = rows[index].model.run_id if 0 <= index < len(rows) else ""
        if run_id:
            await self._splits.remove_where(lambda row: row.run_id == run_id)
        await self._repo.delete_by_token(index, token)

    # ── Paliers (`ACT-19`) ────────────────────────────

    async def detail(self, index: int) -> RunDetail:
        """Une course et ses paliers, prêts à l'affichage."""
        rows = await self._repo.read_all()
        if not 0 <= index < len(rows):
            raise StorageNotFoundError("Cette course n'existe pas.")
        return await self._detail_of(rows[index])

    async def latest(self) -> RunDetail:
        """La course la plus récente, ou un détail **vide** si l'historique l'est.

        Pas de `404` : « aucune course enregistrée » est une réponse, et l'écran a besoin
        de la distinguer d'une panne pour dire ce que coûte le prochain geste plutôt que
        d'afficher une erreur là où il n'y a qu'un début.
        """
        rows = await self._repo.read_all()
        if not rows:
            return RunDetail()
        # Le plus récent par date, et la position départage deux courses du même jour :
        # la seconde saisie est la seconde courue, faute de mieux — les bornes horaires
        # ne sont pas toujours là.
        latest = max(rows, key=lambda row: (row.model.date, row.index))
        return await self._detail_of(latest)

    async def progress(self) -> RunProgress:
        """Toutes les courses et ce qu'elles racontent, en une requête (`ACT-20`).

        Le fichier des paliers est lu **une fois** et compté par `run_id`, plutôt qu'une
        fois par course affichée : à cinquante courses, `_splits_of` aurait relu le même
        fichier cinquante fois pour en tirer cinquante nombres.
        """
        rows = await self._repo.read_all()
        counts: dict[str, int] = {}
        if any(row.model.run_id for row in rows):
            for split in await self._splits.read_all():
                key = split.model.run_id
                counts[key] = counts.get(key, 0) + 1

        computed = progress.analyse(
            [
                progress.Sortie(
                    index=row.index,
                    day=row.model.date,
                    distance_km=row.model.distance_km,
                    duration_min=row.model.duration_min,
                    pace_min_km=row.model.pace_min_km
                    or pace_min_per_km(row.model.distance_km, row.model.duration_min),
                    cadence_spm=row.model.cadence_spm,
                )
                for row in rows
            ]
        )

        return RunProgress(
            # La plus récente d'abord : c'est celle qu'on vient voir, et la liste se lit
            # du haut. L'ordre des agrégats, lui, est chronologique — une courbe se lit
            # dans le sens du temps.
            runs=[
                self.to_schema(row, splits=counts.get(row.model.run_id, 0))
                for row in sorted(rows, key=lambda row: (row.model.date, row.index), reverse=True)
            ],
            total_runs=computed.total_runs,
            total_distance_km=computed.total_distance_km,
            total_minutes=computed.total_minutes,
            overall_pace_min_km=computed.overall_pace_min_km,
            best_pace_min_km=computed.best_pace_min_km,
            best_pace_index=computed.best_pace_index,
            best_pace_day=computed.best_pace_day,
            longest_distance_km=computed.longest_distance_km,
            longest_distance_index=computed.longest_distance_index,
            longest_distance_day=computed.longest_distance_day,
            longest_duration_min=computed.longest_duration_min,
            bands=[
                DistanceBand(
                    label=band.label,
                    runs=band.runs,
                    best_pace_min_km=band.best_pace_min_km,
                    best_index=band.best_index,
                    best_day=band.best_day,
                    average_pace_min_km=band.average_pace_min_km,
                    total_distance_km=band.total_distance_km,
                )
                for band in computed.bands
            ],
            months=[
                MonthTotals(
                    month=month.month,
                    runs=month.runs,
                    distance_km=month.distance_km,
                    minutes=month.minutes,
                    pace_min_km=month.pace_min_km,
                )
                for month in computed.months
            ],
            window=RunWindow(
                size=computed.window.size,
                recent_pace_min_km=computed.window.recent_pace_min_km,
                previous_pace_min_km=computed.window.previous_pace_min_km,
                pace_delta_s_per_km=computed.window.pace_delta_s_per_km,
                recent_distance_km=computed.window.recent_distance_km,
                previous_distance_km=computed.window.previous_distance_km,
                distance_delta_km=computed.window.distance_delta_km,
            ),
            pace_domain_min_km=computed.pace_domain_min_km,
            volume_domain_km=computed.volume_domain_km,
            distance_domain_km=computed.distance_domain_km,
        )

    async def _detail_of(self, row: Row[RunRow]) -> RunDetail:
        stored = await self._splits_of(row.model.run_id)
        computed = _analysed(stored, row.model)
        return RunDetail(
            run=self.to_schema(row, splits=len(stored)),
            splits=computed,
            context=_context(await self._repo.read_all(), row),
        )

    async def _splits_of(self, run_id: str) -> list[RunSplitRow]:
        """Les paliers d'une course, dans l'ordre de leur numéro.

        Un `run_id` vide ne cherche rien : c'est le cas de toutes les courses saisies au
        clavier, et parcourir le fichier pour n'en rien tirer serait une lecture par
        course affichée.
        """
        if not run_id:
            return []
        rows = await self._splits.read_all()
        found = [row.model for row in rows if row.model.run_id == run_id]
        return sorted(found, key=lambda row: row.index)


def _split_rows(run_id: str, payload: RunPayload) -> list[RunSplitRow]:
    """Les lignes de paliers à écrire, drapeau et longueurs posés.

    Deux choses se décident ici et **nulle part en amont** : quels paliers sont des
    reliquats, et quelle distance chacun couvre. Le client peut se tromper sur les deux ;
    ce sont aussi les deux qui faussent toutes les moyennes de la page si on les croit.
    """
    marked = splits.mark_partials(
        [
            splits.Split(
                index=item.index,
                duration_s=item.duration_s,
                pace_min_km=item.pace_min_km,
                cadence_spm=item.cadence_spm,
                avg_hr=item.avg_hr,
                elevation_m=item.elevation_m,
            )
            for item in payload.splits
        ]
    )
    measured = splits.measure_distances(
        marked,
        split_length_km=payload.split_length_km,
        total_distance_km=payload.distance_km,
    )
    return [
        RunSplitRow(
            run_id=run_id,
            index=item.index,
            duration_s=round(item.duration_s, 1),
            # Une longueur que rien n'a permis de établir vaut le palier par défaut plutôt
            # qu'une cellule vide : la colonne est requise, et un reliquat sans distance
            # rendrait la ligne illisible dans un tableur — ce que `STO-02` interdit.
            distance_km=item.distance_km or splits.DEFAULT_SPLIT_KM,
            pace_min_km=_round(item.pace_min_km, 3),
            cadence_spm=item.cadence_spm,
            avg_hr=item.avg_hr,
            elevation_m=item.elevation_m,
            partial=item.partial,
        )
        for item in measured
    ]


#: Nombre de sorties que la courbe de tendance montre. Douze tient sur 390 px sans que les
#: points se touchent, et couvre un cycle d'entraînement plutôt qu'une semaine.
TREND_RUNS = 12


def _context(rows: list[Row[RunRow]], current: Row[RunRow]) -> RunContext:
    """Replace une course parmi les autres (`ACT-19`).

    **Une course seule ne se compare à rien**, et le rang de 1 sur 1 qu'on rendrait alors
    ressemblerait à un record. En dessous de deux courses, tout reste vide et l'écran
    n'affiche simplement pas la section.

    Le rang d'allure est rendu **avec** le nombre de courses comparées, jamais seul :
    comparer l'allure d'un 8 km à celle d'un 3 km est bancal, et c'est à l'écran de le
    dire — pas au service de choisir à la place de l'utilisateur ce qui est comparable.
    """
    if len(rows) < 2:
        return RunContext(runs_compared=len(rows))

    def pace_of(row: Row[RunRow]) -> float | None:
        return row.model.pace_min_km or pace_min_per_km(
            row.model.distance_km, row.model.duration_min
        )

    mine = pace_of(current)
    paces = [value for value in (pace_of(row) for row in rows) if value]
    distances = [row.model.distance_km for row in rows if row.model.distance_km > 0]

    # Le rang se compte sur les valeurs **strictement** meilleures : deux courses à la
    # même allure partagent leur rang, plutôt que l'une devançant l'autre sur sa position
    # de ligne — qui n'est pas un mérite.
    pace_rank = sum(1 for value in paces if value < mine) + 1 if mine and paces else None
    distance_rank = (
        sum(1 for value in distances if value > current.model.distance_km) + 1
        if distances
        else None
    )

    average_pace = sum(paces) / len(paces) if paces else None
    average_distance = sum(distances) / len(distances) if distances else None

    ordered = sorted(rows, key=lambda row: (row.model.date, row.index))
    trend = [value for value in (pace_of(row) for row in ordered[-TREND_RUNS:]) if value]
    return RunContext(
        runs_compared=len(rows),
        pace_rank=pace_rank,
        distance_rank=distance_rank,
        best_pace_min_km=_round(min(paces), 3) if paces else None,
        longest_distance_km=_round(max(distances)) if distances else None,
        average_pace_min_km=_round(average_pace, 3),
        average_distance_km=_round(average_distance),
        pace_delta_s_per_km=(
            round((mine - average_pace) * 60, 1) if mine and average_pace else None
        ),
        distance_delta_km=(
            _round(current.model.distance_km - average_distance) if average_distance else None
        ),
        recent=[
            RunMark(
                id=row.index,
                date=row.model.date,
                distance_km=row.model.distance_km,
                pace_min_km=_round(pace_of(row), 3),
                current=row.index == current.index,
            )
            for row in ordered[-TREND_RUNS:]
        ],
        # Le plus lent d'abord : l'axe part retourné, comme celui des paliers. Deux
        # graphiques d'allure dans la même page qui ne se liraient pas dans le même sens
        # seraient pires que pas de second graphique du tout.
        pace_domain_min_km=(
            (round(max(trend), 4), round(min(trend), 4)) if len(trend) >= 2 else None
        ),
    )


def _analysed(stored: list[RunSplitRow], run: RunRow) -> RunSplits:
    """Traduit les paliers rangés en ce que la page affiche.

    Le drapeau `partial` est **relu depuis le fichier** et non recalculé : il a été décidé
    à l'écriture, et le recalculer à chaque lecture ferait basculer un palier limite d'un
    affichage à l'autre sans que rien n'ait changé dans les données.
    """
    if not stored:
        return RunSplits()

    computed = [
        splits.Split(
            index=row.index,
            duration_s=row.duration_s,
            distance_km=row.distance_km,
            pace_min_km=row.pace_min_km,
            cadence_spm=row.cadence_spm,
            avg_hr=row.avg_hr,
            elevation_m=row.elevation_m,
            partial=row.partial,
        )
        for row in stored
    ]
    analysis = splits.analyse(computed)
    ceiling = analysis.cadence_max_spm
    average = analysis.average_pace_min_km
    widest = analysis.deviation_max_s_per_km

    def deviation(pace: float | None) -> tuple[float | None, float | None]:
        """Écart à la moyenne, et la part **signée** de la barre qui le dessine.

        Le signe voyage avec la valeur plutôt que d'être redécidé à l'écran : une barre
        divergente qui déciderait elle-même de son côté referait ici un calcul métier.
        """
        if pace is None or average is None:
            return None, None
        delta = round((pace - average) * 60, 1)
        if not widest:
            return delta, 0.0
        return delta, round(delta / widest, 4)

    # La cadence se compare à sa propre moyenne, et non à son maximum : de 158 à 174 pas
    # par minute, des parts du maximum tiennent toutes entre 91 % et 100 % du rail et ne
    # montrent rien de la variation qu'on vient regarder.
    beat = analysis.cadence_avg_spm
    widest_beat = analysis.cadence_deviation_max_spm

    def cadence_deviation(value: int | None) -> tuple[float | None, float | None]:
        if value is None or beat is None:
            return None, None
        delta = round(value - beat, 1)
        if not widest_beat:
            return delta, 0.0
        return delta, round(delta / widest_beat, 4)

    rendered: list[RunSplit] = []
    for row, split in zip(stored, computed, strict=True):
        delta, ratio = deviation(row.pace_min_km)
        beat_delta, beat_ratio = cadence_deviation(row.cadence_spm)
        rendered.append(
            RunSplit(
                index=row.index,
                duration_s=row.duration_s,
                distance_km=row.distance_km,
                pace_min_km=row.pace_min_km,
                cadence_spm=row.cadence_spm,
                avg_hr=row.avg_hr,
                elevation_m=row.elevation_m,
                partial=row.partial,
                cadence_ratio=(
                    round(row.cadence_spm / ceiling, 4) if row.cadence_spm and ceiling else None
                ),
                speed_kmh=_round(splits.speed_kmh(row.pace_min_km)),
                stride_m=_round(splits.stride_m(split), 3),
                # Un reliquat n'a pas d'écart à montrer : son allure est extrapolée, et la
                # comparer à une moyenne de mesures donnerait une barre qui ment.
                delta_s_per_km=None if row.partial else delta,
                deviation_ratio=None if row.partial else ratio,
                # Le reliquat garde les siens : sa cadence est mesurée, pas extrapolée.
                cadence_delta_spm=beat_delta,
                cadence_deviation_ratio=beat_ratio,
            )
        )

    return RunSplits(
        splits=rendered,
        full_count=analysis.full_count,
        partial_count=analysis.partial_count,
        drift_s_per_km=analysis.drift_s_per_km,
        first_half_pace_min_km=analysis.first_half_pace_min_km,
        second_half_pace_min_km=analysis.second_half_pace_min_km,
        fastest_index=analysis.fastest_index,
        slowest_index=analysis.slowest_index,
        pace_domain_min_km=analysis.pace_domain_min_km,
        cadence_max_spm=analysis.cadence_max_spm,
        average_pace_min_km=analysis.average_pace_min_km,
        fastest_pace_min_km=analysis.fastest_pace_min_km,
        slowest_pace_min_km=analysis.slowest_pace_min_km,
        pace_spread_s_per_km=analysis.pace_spread_s_per_km,
        pace_sd_s_per_km=analysis.pace_sd_s_per_km,
        negative_split=analysis.negative_split,
        cadence_avg_spm=analysis.cadence_avg_spm,
        cadence_min_spm=analysis.cadence_min_spm,
        cadence_drift_spm=analysis.cadence_drift_spm,
        stride_avg_m=analysis.stride_avg_m,
        stride_min_m=analysis.stride_min_m,
        stride_max_m=analysis.stride_max_m,
        deviation_max_s_per_km=analysis.deviation_max_s_per_km,
    )


# ── Exercices ─────────────────────────────────────────


def read_aliases(raw: str) -> list[str]:
    """Les alias d'une ligne, depuis sa cellule."""
    return [part.strip() for part in raw.split(";") if part.strip()]


def write_aliases(aliases: list[str]) -> str:
    """La cellule, depuis les alias."""
    return ";".join(aliases)


class ExerciseService:
    """Catalogue d'exercices et journal des performances (`ACT-06` → `ACT-09`)."""

    def __init__(self, store: FileStore) -> None:
        self._repo: CsvRepository[ExerciseRow] = CsvRepository(store, EXERCISES, ExerciseRow)
        self._log: CsvRepository[ExerciseLogRow] = CsvRepository(
            store, EXERCISE_LOG, ExerciseLogRow
        )

    @staticmethod
    def entry_to_schema(row: Row[ExerciseLogRow]) -> ExerciseEntry:
        model = row.model
        return ExerciseEntry(
            id=row.index,
            token=row.token,
            workout_id=model.workout_id,
            date=model.date,
            exercise_id=model.exercise_id,
            exercise_name=model.exercise_name,
            muscle_group=model.muscle_group,
            weight_kg=model.weight_kg,
            sets=model.sets,
            reps=model.reps,
            note=model.note,
            volume_kg=_round(model.weight_kg * model.sets * model.reps) or 0,
            one_rep_max_kg=_round(estimate_one_rep_max(model.weight_kg, model.reps)),
        )

    async def catalogue(self) -> list[Exercise]:
        """Catalogue enrichi du rappel de dernière performance (`ACT-08`)."""
        rows = await self._repo.read_all()
        entries = await self._log.read_all()

        latest: dict[str, ExerciseLogRow] = {}
        # Ce que le catalogue conserve derrière lui : le compte des séries qui portent une
        # copie de cet exercice. Il dit ce qu'un retrait laisse intact et ce qu'une
        # correction touche — deux phrases que l'écran ne peut pas écrire sans lui, et
        # qu'il n'a pas le droit de calculer.
        counts: dict[str, int] = {}
        for entry in sorted(entries, key=lambda item: (item.model.date, item.index)):
            latest[entry.model.exercise_id] = entry.model
            counts[entry.model.exercise_id] = counts.get(entry.model.exercise_id, 0) + 1

        catalogue: list[Exercise] = []
        for row in rows:
            if not row.model.id:
                continue  # ligne sans identifiant : le journal ne peut pas s'y rattacher
            last = latest.get(row.model.id)
            catalogue.append(
                Exercise(
                    id=row.index,
                    token=row.token,
                    exercise_id=row.model.id,
                    name=row.model.name,
                    muscle_group=row.model.muscle_group,
                    aliases=read_aliases(row.model.aliases),
                    entries=counts.get(row.model.id, 0),
                    last_weight_kg=last.weight_kg if last else None,
                    last_reps=last.reps if last else None,
                    last_sets=last.sets if last else None,
                    last_date=last.date if last else None,
                )
            )
        return catalogue

    async def read_notes(self, ai: AiService, text: str, photo: bytes | None) -> NoteDraft:
        """Lit une séance écrite en clair, ou photographiée (`C07`). **N'écrit rien.**

        Une photo passe par le **même modèle** que le reste : l'OCR n'est pas une brique
        à part, c'est la même consigne avec une image. Le texte tiré de l'image alimente
        ensuite exactement le même rapprochement qu'une note tapée — un second chemin
        divergerait du premier au premier cas limite.
        """
        # Le catalogue part **avec** la consigne : sans lui le modèle ne peut rien
        # rapprocher, et tout arriverait en création.
        existing = await self.catalogue()
        prompt = notes.prompt_with(existing)

        if photo:
            payload = await ai.ask_json(
                instruction=notes.INSTRUCTION,
                prompt=prompt,
                images=[prepare_data_url(photo)],
                max_tokens=1200,
            )
        else:
            payload = await ai.ask_json(
                instruction=notes.INSTRUCTION,
                prompt=f"{prompt}\n\n## La note\n\n{text.strip()}",
                max_tokens=1200,
            )

        lines = notes.read_lines(payload)
        if notes.is_unreadable(payload, lines):
            raise AiUnreadableError(
                "Rien n'a pu être lu dans cette note. Vérifie qu'elle porte bien des "
                "exercices, ou saisis-les à la main."
            )

        return NoteDraft(lines=notes.match(lines, existing), source_text=text.strip())

    async def create(self, payload: ExercisePayload) -> Exercise:
        row = await self._repo.append(
            ExerciseRow(
                id=new_id(),
                name=payload.name,
                muscle_group=payload.muscle_group,
                aliases=write_aliases(payload.aliases or []),
            )
        )
        return Exercise(
            id=row.index,
            token=row.token,
            exercise_id=row.model.id,
            name=row.model.name,
            muscle_group=row.model.muscle_group,
            aliases=read_aliases(row.model.aliases),
        )

    async def update(self, index: int, token: str, payload: ExercisePayload) -> Exercise:
        """Corrige le nom ou le groupe d'un exercice, **et le répercute au journal**.

        Deux décisions, et elles ont chacune une conséquence qui ne se voit pas tout de
        suite.

        **`id` survit à la correction.** C'est la clé stable à laquelle `exercise_log.csv`
        rattache tout l'historique. En régénérer un orphelinerait des années de relevés
        sans lever la moindre erreur — c'est la ligne la plus dangereuse de ce module.

        **Les copies du journal suivent.** `exercise_log.csv` duplique `exercise_name` et
        `muscle_group`, et trois lecteurs se servent de la copie plutôt que du catalogue :
        la progression (`stats.progress`), le tonnage par groupe et les groupes négligés
        (`stats._muscles`, `stats._neglected`), et le détail d'une journée d'assiduité.
        Sans répercussion, corriger une faute de frappe laisserait la barre de progression
        étiquetée avec la faute pendant que le sélecteur affiche la forme corrigée — et
        changer un groupe ferait compter le même exercice dans deux groupes, selon la date
        de chaque série.

        La duplication existe pour qu'un exercice **supprimé** garde son historique
        lisible (`ACT-06`, `STO-02`), pas pour figer un nom contre sa propre correction.
        Le corollaire est assumé et l'écran l'annonce avant le geste : renommer est une
        *correction*, pas un recyclage de ligne.

        L'ordre compte, comme pour `WorkoutService.delete` : la ligne gardée part en
        premier. Si la garde refuse, rien n'a bougé. Si la répercussion échoue après coup,
        le journal garde ses anciennes copies et rejouer la même correction converge — le
        projet n'a pas de transaction.
        """
        rows = await self._repo.read_all(fresh=True)
        if not 0 <= index < len(rows):
            raise StorageConflictError(detail=f"exercice {index} absent du catalogue")

        existing = rows[index].model
        row = await self._repo.replace_by_token(
            index,
            token,
            ExerciseRow(
                id=existing.id,
                name=payload.name,
                muscle_group=payload.muscle_group,
                # `None` laisse les alias en place : le formulaire du catalogue n'en parle
                # pas, et corriger une faute de frappe ne doit pas effacer ce que la
                # lecture de notes a appris.
                aliases=existing.aliases
                if payload.aliases is None
                else write_aliases(payload.aliases),
            ),
        )

        if existing.id:
            await self._log.update_where(
                lambda entry: entry.exercise_id == existing.id,
                lambda entry: entry.model_copy(
                    update={
                        "exercise_name": payload.name,
                        "muscle_group": payload.muscle_group,
                    }
                ),
            )

        return Exercise(
            id=row.index,
            token=row.token,
            exercise_id=row.model.id,
            name=row.model.name,
            muscle_group=row.model.muscle_group,
            aliases=read_aliases(row.model.aliases),
        )

    async def delete(self, index: int, token: str) -> None:
        """Retire un exercice du catalogue.

        Le journal n'est **pas** touché : `ACT-06` exige que l'historique survive. C'est
        précisément pourquoi `exercise_log.csv` duplique le nom et le groupe musculaire —
        les lignes passées restent lisibles sans le catalogue.
        """
        await self._repo.delete_by_token(index, token)

    async def add_alias(self, exercise_id: str, alias: str) -> Exercise:
        """Ajoute une graphie reconnue à un exercice existant (`C07`).

        Un ajout et non un remplacement : la fois suivante, « dev couché » **et** toutes
        les abréviations déjà apprises seront reconnues. Un alias déjà présent — au repli
        près — ne se réécrit pas, ce qui rend l'opération sûre à rejouer.
        """
        rows = await self._repo.read_all(fresh=True)
        for index, row in enumerate(rows):
            if row.model.id != exercise_id:
                continue
            existing = read_aliases(row.model.aliases)
            known = {fold(item) for item in [*existing, row.model.name]}
            if fold(alias) not in known:
                existing.append(alias.replace(";", " ").strip())
            saved = await self._repo.replace_by_token(
                index, row.token, row.model.model_copy(update={"aliases": write_aliases(existing)})
            )
            return Exercise(
                id=saved.index,
                token=saved.token,
                exercise_id=saved.model.id,
                name=saved.model.name,
                muscle_group=saved.model.muscle_group,
                aliases=read_aliases(saved.model.aliases),
            )
        raise StorageNotFoundError("Cet exercice n'existe pas.")

    async def resolve(self, exercise_id: str) -> ExerciseRow:
        rows = await self._repo.read_all()
        for row in rows:
            if row.model.id == exercise_id:
                return row.model
        raise StorageNotFoundError("Cet exercice n'est pas au catalogue.")

    async def log_entries(self) -> list[Row[ExerciseLogRow]]:
        return await self._log.read_all()

    async def ensure(self, name: str, muscle_group: str) -> ExerciseRow:
        """L'exercice du catalogue portant ce nom, **créé s'il n'y est pas**.

        C'est le pont entre un circuit Cadence et le catalogue de Metric : « Push-Ups
        Classic » y entre au premier circuit déclaré fait, puis se réutilise. Sans ça, le
        journal porterait un `exercise_id` vide et « Progression des charges » ignorerait
        ces exercices.

        La reconnaissance passe par `fold` — casse, accents et ponctuation ignorés — et par
        les alias, exactement comme la relecture d'une note manuscrite (`C07`). Deux
        graphies du même mouvement ne doivent pas donner deux lignes de catalogue, sinon
        l'historique de charge se coupe en deux au premier changement d'orthographe.

        **Ne renomme jamais un exercice existant** et ne corrige pas son groupe : le
        catalogue appartient à l'utilisateur, un circuit n'est pas une autorité sur lui.
        """
        wanted = fold(name)
        for row in await self._repo.read_all():
            if fold(row.model.name) == wanted:
                return row.model
            if any(fold(alias) == wanted for alias in read_aliases(row.model.aliases)):
                return row.model

        created = await self._repo.append(
            ExerciseRow(id=new_id(), name=name, muscle_group=muscle_group)
        )
        return created.model

    async def log_timed(
        self, workout_id: str, day: date, exercise: ExerciseRow, *, sets: int, reps: int
    ) -> ExerciseEntry:
        """Journalise une série **sans passer par `ExerciseEntryPayload`**, et c'est assumé.

        Le schéma de saisie borne `reps` à `ge=1`, parce qu'une saisie manuelle n'a aucune
        raison d'écrire un nombre négatif. Un exercice de circuit au temps, lui, n'a pas de
        répétitions du tout : il porte la sentinelle `-1`, la même que
        `circuit_exercises.csv`, et la même règle de lecture — c'est `reps` qui dit la
        nature de la ligne.

        Desserrer `Reps` pour l'accueillir aurait rendu `-1` acceptable **à la saisie
        manuelle** aussi, où ce serait une faute de frappe silencieuse dans un journal de
        charge. Un second point d'entrée, documenté et étroit, coûte moins cher qu'une
        borne relâchée pour tout le monde.

        `weight_kg = 0` est le poids du corps, valeur légitime (`ACT-07`) : le tonnage
        d'un tabata est donc nul, ce qui est vrai. Ce qu'il apporte aux statistiques, ce
        sont ses **séries** par groupe musculaire.
        """
        row = await self._log.append(
            ExerciseLogRow(
                workout_id=workout_id,
                date=day,
                exercise_id=exercise.id,
                exercise_name=exercise.name,
                muscle_group=exercise.muscle_group,
                weight_kg=0,
                sets=sets,
                reps=reps,
            )
        )
        return self.entry_to_schema(row)

    async def log(self, workout_id: str, day: date, payload: ExerciseEntryPayload) -> ExerciseEntry:
        exercise = await self.resolve(payload.exercise_id)
        row = await self._log.append(
            ExerciseLogRow(
                workout_id=workout_id,
                date=day,
                exercise_id=exercise.id,
                # Dupliqués volontairement : le fichier doit rester compréhensible seul.
                exercise_name=exercise.name,
                muscle_group=exercise.muscle_group,
                weight_kg=payload.weight_kg,
                sets=payload.sets,
                reps=payload.reps,
                note=payload.note,
            )
        )
        return self.entry_to_schema(row)

    async def update_entry(
        self, index: int, token: str, payload: ExerciseEntryPayload
    ) -> ExerciseEntry:
        rows = await self._log.read_all(fresh=True)
        if not 0 <= index < len(rows):
            raise StorageConflictError(detail=f"ligne {index} absente du journal")

        existing = rows[index].model
        exercise = await self.resolve(payload.exercise_id)
        row = await self._log.replace_by_token(
            index,
            token,
            ExerciseLogRow(
                workout_id=existing.workout_id,
                date=existing.date,
                exercise_id=exercise.id,
                exercise_name=exercise.name,
                muscle_group=exercise.muscle_group,
                weight_kg=payload.weight_kg,
                sets=payload.sets,
                reps=payload.reps,
                note=payload.note,
            ),
        )
        return self.entry_to_schema(row)

    async def delete_entry(self, index: int, token: str) -> None:
        await self._log.delete_by_token(index, token)

    async def purge_workout(self, workout_id: str) -> int:
        """Supprime les performances rattachées à une séance (`ACT-04`)."""
        return await self._log.remove_where(lambda row: row.workout_id == workout_id)


# ── Séances ───────────────────────────────────────────


class WorkoutService:
    """Séances : saisie, exercices rattachés, duplication (`ACT-03`, `ACT-04`, `ACT-17`)."""

    def __init__(self, store: FileStore) -> None:
        self._repo: CsvRepository[WorkoutRow] = CsvRepository(store, WORKOUTS, WorkoutRow)
        self._exercises = ExerciseService(store)

    async def all(self) -> list[Row[WorkoutRow]]:
        return await self._repo.read_all()

    def _to_schema(self, row: Row[WorkoutRow], entries: list[ExerciseEntry]) -> Workout:
        model = row.model
        return Workout(
            id=row.index,
            token=row.token,
            workout_id=model.id,
            date=model.date,
            type=model.type,
            duration_min=model.duration_min,
            calories=model.calories,
            rpe=model.rpe,
            note=model.note,
            source=model.source,
            exercises=entries,
            volume_kg=_round(sum(entry.volume_kg for entry in entries)) or 0,
        )

    async def get(self, index: int) -> Workout:
        rows = await self._repo.read_all()
        if not 0 <= index < len(rows):
            raise StorageNotFoundError("Cette séance n'existe pas.")

        row = rows[index]
        entries = [
            self._exercises.entry_to_schema(entry)
            for entry in await self._exercises.log_entries()
            if entry.model.workout_id == row.model.id
        ]
        return self._to_schema(row, entries)

    async def create(self, payload: WorkoutPayload, *, source: str = "manual") -> Workout:
        """Enregistre une séance, et ses exercices s'il y en a. `source` reste `manual`
        sauf import (`IMP-05`).

        **Les exercices sont résolus avant la première écriture.** Un identifiant inconnu
        est le seul échec courant de cette route, et il refuse alors la demande entière
        sans avoir rien écrit — ce qui est précisément ce qu'un assistant de saisie
        abandonné en cours de route ne doit pas laisser derrière lui.
        """
        # Résolution d'abord : elle lève sur un exercice absent du catalogue, et à ce
        # moment-là rien n'est encore parti sur le stockage.
        for entry in payload.exercises:
            await self._exercises.resolve(entry.exercise_id)

        row = await self._repo.append(
            WorkoutRow(
                date=payload.date,
                type=payload.type,
                duration_min=payload.duration_min,
                calories=payload.calories,
                rpe=payload.rpe,
                note=payload.note,
                source=source,
                id=new_id(),
            )
        )

        logged = [
            await self._exercises.log(row.model.id, payload.date, entry)
            for entry in payload.exercises
        ]
        return self._to_schema(row, logged)

    async def update(self, index: int, token: str, payload: WorkoutPayload) -> Workout:
        rows = await self._repo.read_all(fresh=True)
        if not 0 <= index < len(rows):
            raise StorageConflictError(detail=f"séance {index} absente")

        existing = rows[index].model
        row = await self._repo.replace_by_token(
            index,
            token,
            WorkoutRow(
                date=payload.date,
                type=payload.type,
                duration_min=payload.duration_min,
                calories=payload.calories,
                rpe=payload.rpe,
                note=payload.note,
                # Identifiant et source survivent à une correction : les exercices y sont
                # rattachés, et l'origine de la donnée ne change pas (`IMP-05`).
                source=existing.source,
                id=existing.id,
            ),
        )
        entries = [
            self._exercises.entry_to_schema(entry)
            for entry in await self._exercises.log_entries()
            if entry.model.workout_id == existing.id
        ]
        return self._to_schema(row, entries)

    async def delete(self, index: int, token: str) -> None:
        """Supprime une séance **et purge ses exercices** (`ACT-04`).

        L'ordre compte : la séance part en premier, sous garde. Purger d'abord laisserait
        des exercices orphelins si la garde refusait la suppression.
        """
        rows = await self._repo.read_all(fresh=True)
        if not 0 <= index < len(rows):
            raise StorageConflictError(detail=f"séance {index} absente")
        workout_id = rows[index].model.id

        await self._repo.delete_by_token(index, token)
        await self._exercises.purge_workout(workout_id)

    async def duplicate(self, index: int, day: date) -> Workout:
        """Recrée une séance passée, exercices compris (`ACT-17`).

        Saisir une répétition de routine devient une action au lieu d'une dizaine.
        """
        source = await self.get(index)

        created = await self.create(
            WorkoutPayload(
                date=day,
                type=source.type,
                duration_min=source.duration_min,
                calories=source.calories,
                rpe=None,  # l'effort perçu appartient à la séance vécue, pas au modèle
                note=source.note,
            )
        )

        entries: list[ExerciseEntry] = []
        for entry in source.exercises:
            entries.append(
                await self._exercises.log(
                    created.workout_id,
                    day,
                    ExerciseEntryPayload(
                        exercise_id=entry.exercise_id,
                        weight_kg=entry.weight_kg,
                        sets=entry.sets,
                        reps=entry.reps,
                    ),
                )
            )

        created.exercises = entries
        created.volume_kg = _round(sum(entry.volume_kg for entry in entries)) or 0
        return created


# ── Circuits (Cadence Tabata) ─────────────────────────


def _group_of(item: CircuitExerciseRow) -> str:
    """Le groupe musculaire d'un exercice de circuit, ou `autre`.

    Le repli existe pour les lignes écrites à la main ou avant que la colonne existe
    (`STO-04`). Il ne se voit jamais depuis la saisie : le schéma exige le groupe.
    """
    cleaned = item.muscle_group.strip()
    return cleaned if cleaned in {group.value for group in MuscleGroup} else MuscleGroup.AUTRE.value


class CircuitService:
    """Séances **modèles**, ouvertes dans Cadence Tabata (**D2**, **D3**, **D7**).

    ## Un circuit fait entre dans l'ancien système, entièrement

    **D2 est renversée**, et c'est le bon sens : un tabata *est* du sport, il n'a aucune
    raison de vivre à côté des séances. Déclarer un circuit fait écrit une séance `HIIT`
    **et** ses séries dans `exercise_log.csv`, donc dans le tonnage, dans l'équilibre par
    groupe musculaire et dans les pistes d'assiduité — comme n'importe quelle séance.

    Ce qui rend ça possible sans table de correspondance : **chaque exercice de circuit
    porte son groupe musculaire**, choisi une fois à la création. On ne devine rien depuis
    le nom anglais de Cadence — une correspondance approximative de plus se serait trompée
    en silence, exactement comme celle des illustrations.

    Le nom, lui, rejoint le catalogue de Metric au premier « fait » (`ensure`), reconnu par
    `fold` et par les alias. Deux graphies du même mouvement ne créent donc pas deux entrées.

    ## Ce qui reste séparé

    Le **catalogue d'illustrations de Cadence** — ses 35 noms anglais — n'est toujours
    rapproché d'aucune donnée de Metric. Il sert à choisir un intitulé qui affiche une
    image, et rien d'autre.
    """

    #: La provenance écrite dans `workouts.csv`. Elle rejoint `manual`, `apple` et `ia` ;
    #: `IMP-05` s'applique — corriger la durée d'une séance venue d'ici ne la transforme
    #: pas en saisie manuelle.
    SOURCE = "cadence"

    #: Le type de séance écrit quand on déclare un circuit fait. Il est déjà dans
    #: `WORKOUT_TYPES`, donc il ne crée pas un vocabulaire de plus.
    WORKOUT_TYPE = "HIIT"

    def __init__(self, store: FileStore) -> None:
        # Gardé en plus des dépôts : la composition assistée lit les réglages et les
        # indicateurs du coach, qui vivent dans d'autres services construits sur demande.
        self._store = store
        self._repo: CsvRepository[CircuitRow] = CsvRepository(store, CIRCUITS, CircuitRow)
        self._items: CsvRepository[CircuitExerciseRow] = CsvRepository(
            store, CIRCUIT_EXERCISES, CircuitExerciseRow
        )
        self._workouts = WorkoutService(store)
        self._exercises = ExerciseService(store)
        self._sessions = CircuitSessionService(store)
        self._settings = SettingsService(store)
        self._loads: CsvRepository[CircuitLoadRow] = CsvRepository(
            store, CIRCUIT_LOADS, CircuitLoadRow
        )

    # ── Conversions ───────────────────────────────────

    #: Ce qui sépare la charge de la note sur la même ligne. Un point médian, comme partout
    #: ailleurs dans l'application — deux ponctuations pour la même jointure se
    #: remarqueraient, et celle-ci s'affiche chez quelqu'un d'autre.
    NOTE_JOIN = " · "

    #: Longueur au-delà de laquelle la note composée est coupée.
    #:
    #: `llms.txt` §11 : « les notes sont courtes : elles s'affichent sur une ligne ». La
    #: saisie est déjà bornée à 60 ; la **composée** peut la dépasser en y ajoutant la
    #: charge, et c'est le seul endroit où ça se produit. Couper ici plutôt que laisser
    #: Cadence pousser le reste hors de l'écran de quelqu'un qui force.
    NOTE_MAX = 72

    @classmethod
    def note_of(cls, load: CircuitLoadRow | None, typed: str = "") -> str:
        """La note que le lien porte pour un exercice — sa charge **et** ce qu'on a écrit.

        **Un seul endroit au monde où « 12 » devient « 12 kg » et où les deux se joignent.**
        La note du lien et le champ que l'écran affiche sortent d'ici tous les deux ; deux
        compositions divergeraient, et le symptôme serait un lien qui n'annonce pas ce que
        la carte dit.

        ## La charge d'abord, la note ensuite

        La charge est le chiffre qu'on cherche des yeux entre deux séries ; « genoux au
        sol » se relit une fois et se sait. L'inverse ferait chercher le nombre derrière
        une phrase, sur un écran qu'on regarde une seconde.

        ## Le poids du corps ne produit aucune note

        Un tabata sans charge n'a rien de plus à dire, et une ligne « poids du corps » sur
        chaque écran de repos serait du bruit qui pousse le reste hors de vue. La note
        saisie, elle, s'affiche seule dans ce cas — c'est bien qu'on a voulu l'y mettre.

        **C7 est révisée** : la note n'est plus « jamais saisie ». Elle reste fabriquée
        ici — le client ne compose toujours aucune URL, l'invariant du §2 tient — mais elle
        peut porter ce que l'application n'a aucun moyen de savoir.
        """
        charge = (
            ""
            if load is None or load.bodyweight or load.weight_kg is None
            else f"{fr(load.weight_kg)} kg"
        )
        parts = [part for part in (charge, typed.strip()) if part]
        return cls.NOTE_JOIN.join(parts)[: cls.NOTE_MAX]

    @classmethod
    def _to_link(
        cls,
        row: CircuitRow,
        items: list[CircuitExerciseRow],
        loads: dict[str, CircuitLoadRow] | None = None,
    ) -> circuit_link.LinkCircuit:
        """Les lignes du fichier → la forme que le module pur manipule.

        C'est **ici** qu'on lit la sentinelle `-1`, et nulle part ailleurs : le module pur
        la connaît, l'API ne la voit jamais.

        `loads` est facultatif, et son absence veut dire « pas de note » plutôt que « à
        aller chercher ». Les appelants qui n'ont besoin que de la **durée** — `mark_done`
        pour ses rounds bornés — évitent ainsi une lecture Nextcloud qui ne changerait rien
        à leur résultat : une note ne pèse pas une seconde dans l'estimation.
        """
        found = loads or {}
        return circuit_link.LinkCircuit(
            name=row.name,
            rounds=row.rounds,
            round_rest_s=row.round_rest_s,
            exercises=tuple(
                circuit_link.LinkExercise(
                    name=item.name,
                    duration_s=item.duration_s,
                    reps=item.reps,
                    rest_s=item.rest_s,
                    note=cls.note_of(found.get(fold(item.name)), item.note),
                )
                for item in items
            ),
        )

    def _to_schema(
        self,
        row: Row[CircuitRow],
        items: list[CircuitExerciseRow],
        base: str,
        loads: dict[str, CircuitLoadRow] | None = None,
    ) -> Circuit:
        link = self._to_link(row.model, items, loads)
        prediction = circuit_link.estimate(link)

        return Circuit(
            id=row.index,
            token=row.token,
            circuit_id=row.model.id,
            name=row.model.name,
            rounds=row.model.rounds,
            round_rest_s=row.model.round_rest_s,
            created=row.model.created,
            note=row.model.note or None,
            exercises=[
                CircuitExercise(
                    position=item.position,
                    muscle_group=_group_of(item),
                    duration_s=item.duration_s if item.reps == circuit_link.TIMED else None,
                    reps=None if item.reps == circuit_link.TIMED else item.reps,
                    name=item.name,
                    rest_s=item.rest_s,
                    note=item.note,
                    link_note=self.note_of((loads or {}).get(fold(item.name)), item.note) or None,
                )
                for item in items
            ],
            url=circuit_link.build_url(base, link),
            estimated_duration_min=prediction.minutes,
            exact=prediction.exact,
        )

    @staticmethod
    def _to_rows(
        circuit_id: str, payload: CircuitPayload
    ) -> tuple[CircuitRow, list[CircuitExerciseRow]]:
        """La charge utile → les lignes du fichier, avec la sentinelle remise en place.

        `position` est écrite explicitement et non déduite de l'ordre du fichier : c'est
        ce qui permet de trier `circuit_exercises.csv` dans un tableur sans intervertir
        les exercices de tous les circuits.
        """
        items = [
            CircuitExerciseRow(
                circuit_id=circuit_id,
                position=index,
                name=exercise.name,
                muscle_group=exercise.muscle_group,
                duration_s=exercise.duration_s or circuit_link.DEFAULT_DURATION_S,
                reps=circuit_link.TIMED if exercise.reps is None else exercise.reps,
                rest_s=exercise.rest_s,
                note=exercise.note.strip(),
            )
            for index, exercise in enumerate(payload.exercises, start=1)
        ]
        row = CircuitRow(
            id=circuit_id,
            name=payload.name,
            rounds=payload.rounds,
            round_rest_s=payload.round_rest_s,
            created=today_local(),
            note=payload.note or "",
        )
        return row, items

    # ── Lecture ───────────────────────────────────────

    async def _base(self) -> str:
        """L'adresse de Cadence, ou la chaîne vide (**D1**)."""
        return (await self._settings.values()).cadence_base_url

    async def _loads_by_name(self) -> dict[str, CircuitLoadRow]:
        """Les charges déclarées, indexées par nom **replié** (**C7**).

        Lue une fois par affichage de liste et posée sur chaque lien : c'est ce qui fait
        qu'un changement de charge se voit **immédiatement** dans les trois circuits qui
        emploient l'exercice, sans qu'aucun lien soit réécrit dans un fichier. Le lien est
        fabriqué à la lecture, il n'est stocké nulle part.
        """
        return {
            fold(row.model.name): row.model
            for row in await self._loads.read_all()
            if row.model.name
        }

    async def _items_of(self, circuit_id: str) -> list[CircuitExerciseRow]:
        """Les exercices d'un circuit, dans l'ordre **écrit** sur les lignes.

        Un circuit sans identifiant ne réclame aucun exercice : sinon toutes les lignes
        orphelines d'un fichier corrigé à la main lui seraient rattachées d'un coup.
        """
        if not circuit_id:
            return []
        rows = [
            row.model for row in await self._items.read_all() if row.model.circuit_id == circuit_id
        ]
        return sorted(rows, key=lambda item: item.position)

    async def list(self) -> CircuitList:
        """Tous les circuits, du plus récent au plus ancien.

        Une seule lecture des exercices pour toute la liste : une par circuit ferait autant
        d'allers-retours vers Nextcloud qu'il y a de séances enregistrées.
        """
        base = await self._base()
        loads = await self._loads_by_name()
        rows = await self._repo.read_all()
        items = [row.model for row in await self._items.read_all()]

        grouped: dict[str, list[CircuitExerciseRow]] = {}
        for item in items:
            grouped.setdefault(item.circuit_id, []).append(item)
        for bucket in grouped.values():
            bucket.sort(key=lambda entry: entry.position)

        circuits = [
            self._to_schema(row, grouped.get(row.model.id, []) if row.model.id else [], base, loads)
            for row in rows
        ]
        # Tri décroissant sur la date puis sur la position : deux circuits créés le même
        # jour gardent l'ordre d'écriture, et une date absente ne fait pas tomber le tri.
        circuits.sort(key=lambda item: (item.created or date.min, item.id), reverse=True)

        return CircuitList(circuits=circuits, linkable=bool(base.strip()))

    async def get(self, index: int) -> Circuit:
        rows = await self._repo.read_all()
        if not 0 <= index < len(rows):
            raise StorageNotFoundError("Ce circuit n'existe pas.")

        row = rows[index]
        return self._to_schema(
            row, await self._items_of(row.model.id), await self._base(), await self._loads_by_name()
        )

    async def find(self, circuit_id: str) -> Circuit | None:
        """Un circuit par son identifiant **stable**, ou `None`.

        Par `circuit_id` et non par position : ce point d'entrée sert à joindre une séance
        à un planning, et une position se décale à la première suppression — la séance
        prévue pointerait alors vers une autre.
        """
        if not circuit_id.strip():
            return None
        rows = await self._repo.read_all()
        for row in rows:
            if row.model.id == circuit_id:
                return self._to_schema(
                    row,
                    await self._items_of(row.model.id),
                    await self._base(),
                    await self._loads_by_name(),
                )
        return None

    # `Sequence` et non `list`, et ce n'est pas un choix de style : cette classe porte une
    # méthode `list`, qui masque le type interne dans toute annotation de son corps. Le
    # symptôme est un message de mypy qui parle de « callback protocol » sans jamais nommer
    # la collision.
    async def suggestions(
        self,
        query: str = "",
        *,
        body_part: str | None = None,
        equipment: str | None = None,
    ) -> Sequence[CircuitSuggestion]:
        """Les noms proposés à la saisie : les tiens d'abord, ceux de Cadence ensuite.

        ## Pourquoi une recherche et plus une liste

        Elle rendait 35 noms, tous ceux qui affichaient alors une illustration. Cadence en
        embarque **1324** : les servir d'un bloc mettrait 70 ko sur le réseau pour qu'un
        téléphone les filtre, c'est-à-dire le calcul métier du mauvais côté. Le filtrage
        est donc ici, et le plafond est celui du catalogue — `exercise_catalog.LIMIT`.

        ## Pourquoi le catalogue de Metric passe devant

        Ce sont les seuls noms qui portent un **groupe musculaire**, et c'est lui qui fait
        qu'un tabata déclaré fait compte dans « groupes négligés » (**D2**). Un nom de
        Cadence n'en porte aucun, et en deviner un serait inventer une valeur que les
        statistiques prendraient au sérieux.

        Un exercice nommé des deux côtés n'apparaît **qu'une fois**, sous la graphie de
        l'utilisateur : le rapprochement passe par `fold`, celui du reste du domaine.

        ## Le filtre par zone ou par matériel ne s'applique qu'au catalogue de Cadence

        Lui seul porte ces champs. Filtrer « je n'ai que des haltères » écarte donc les
        exercices de Metric plutôt que d'en laisser passer dont on ne sait rien — c'est le
        seul choix qui ne ment pas sur ce qui a été filtré.
        """
        filtered = body_part is not None or equipment is not None
        catalogue = [] if filtered else await self._exercises.catalogue()
        needle = fold(query)

        mine = [
            CircuitSuggestion(name=item.name, muscle_group=item.muscle_group)
            for item in catalogue
            if not needle or needle in fold(item.name)
        ]
        known_names = {fold(item.name) for item in catalogue}

        theirs = [
            CircuitSuggestion(
                name=found.name,
                muscle_group=None,
                body_part=found.body_part,
                equipment=found.equipment,
            )
            for found in exercise_catalog.search(
                query, body_part=body_part, equipment=equipment, limit=exercise_catalog.LIMIT
            )
            if fold(found.name) not in known_names
        ]

        return [*mine, *theirs][: exercise_catalog.LIMIT]

    # ── Écriture ──────────────────────────────────────

    async def create(self, payload: CircuitPayload) -> Circuit:
        """Enregistre un circuit et ses exercices.

        **Le circuit s'écrit d'abord**, comme une course et ses paliers : le stockage n'a
        pas de transaction, et l'ordre inverse laisserait des exercices rattachés à un
        identifiant qui n'existe nulle part, c'est-à-dire des lignes que rien ne vient
        jamais nettoyer.
        """
        circuit_id = new_id()
        row_model, items = self._to_rows(circuit_id, payload)

        row = await self._repo.append(row_model)
        await self._items.extend(items)

        return self._to_schema(row, items, await self._base(), await self._loads_by_name())

    async def update(self, index: int, token: str, payload: CircuitPayload) -> Circuit:
        """Corrige un circuit, sous garde anti-conflit (`STO-05`).

        **L'identifiant stable est conservé**, et la date de création aussi : une
        correction ne fait pas naître un nouveau circuit. Les exercices, eux, sont
        remplacés en bloc — on ne sait pas apparier un exercice renommé avec celui qu'il
        remplace, et deviner ferait pire qu'une réécriture franche.
        """
        rows = await self._repo.read_all(fresh=True)
        if not 0 <= index < len(rows):
            raise StorageConflictError(detail=f"circuit {index} absent")

        existing = rows[index].model
        circuit_id = existing.id or new_id()
        row_model, items = self._to_rows(circuit_id, payload)
        row_model.created = existing.created

        row = await self._repo.replace_by_token(index, token, row_model)
        await self._items.remove_where(lambda item: item.circuit_id == circuit_id)
        await self._items.extend(items)

        return self._to_schema(row, items, await self._base(), await self._loads_by_name())

    async def delete(self, index: int, token: str) -> None:
        """Supprime un circuit et ses exercices (`ACT-04`, même motif que les séances).

        Ce qui **survit** : les liens déjà collés dans une note de planning. Une URL
        Cadence est autoportante — elle contient la séance entière — donc supprimer le
        modèle ne casse aucune séance prévue. C'est le seul endroit où l'absence de base
        de données joue en notre faveur.
        """
        rows = await self._repo.read_all(fresh=True)
        if not 0 <= index < len(rows):
            raise StorageConflictError(detail=f"circuit {index} absent")
        circuit_id = rows[index].model.id

        await self._repo.delete_by_token(index, token)
        if circuit_id:
            await self._items.remove_where(lambda item: item.circuit_id == circuit_id)

    async def import_link(self, url: str) -> Circuit:
        """Relit un lien Cadence collé et l'enregistre comme circuit.

        Le décodeur est celui de l'aller-retour ; ce qu'il rend est déjà borné. Un lien
        illisible n'est pas une panne mais une saisie à corriger, d'où un refus qui porte
        un code plutôt qu'une trace.
        """
        parsed = circuit_link.parse_url(url)
        if parsed is None:
            raise ValidationFailedError(
                "Ce lien ne contient pas de séance lisible.", detail="lien Cadence illisible"
            )

        return await self.create(
            CircuitPayload(
                name=parsed.name,
                rounds=parsed.rounds,
                round_rest_s=parsed.round_rest_s,
                exercises=[
                    CircuitExercisePayload(
                        name=exercise.name,
                        # Un lien Cadence ne porte aucun groupe musculaire : il n'a pas de
                        # champ pour ça. `autre` est donc le seul choix honnête — deviner
                        # depuis le nom serait la correspondance approximative que ce lot
                        # s'interdit. L'écran laisse corriger, et c'est un geste de plus
                        # qu'on assume plutôt qu'un groupe faux qu'on n'aurait pas vu.
                        muscle_group=MuscleGroup.AUTRE.value,
                        duration_s=exercise.duration_s if exercise.timed else None,
                        reps=None if exercise.timed else exercise.reps,
                        rest_s=exercise.rest_s,
                    )
                    for exercise in parsed.exercises
                ],
            )
        )

    # ── Composition assistée (**R5**) ─────────────────

    async def compose(self, ai: AiService, request: ComposeRequest) -> CircuitProposal:
        """Demande un circuit à un modèle. **N'écrit rien.**

        La symétrie avec `PlanningService.propose` est voulue : cette méthode ne connaît
        pas l'écriture, `create` ne connaît pas l'IA, et entre les deux il y a un écran et
        un appui. C'est là que vit « rien n'est écrit sans validation ».

        ## Ce que l'utilisateur n'a pas à taper

        Le **matériel possédé** et les **groupes négligés** partent avec la demande (§5
        bis). Sans eux, « fais-moi 30 minutes » obtient un développé couché de qui n'a ni
        banc ni barre — et le refuser après coup ne rend pas la proposition utilisable.

        Les **contraintes** du profil partent aussi, dans leur rubrique à elles : une
        épaule sensible n'est pas une préférence qu'on arbitre contre le reste.
        """
        # Import tardif, et ce n'est pas un goût : `app.domains.assistant` exécute le
        # `__init__` du paquet, donc son routeur, donc son service, qui lit `stats.py`,
        # qui lit **ce** module. En clair, l'import échouerait sur un module à moitié
        # construit. C'est l'arrangement du reste du dépôt pour la même raison.
        from app.domains.assistant import profile

        settings = await SettingsService(self._store).all()
        materiel, _inconnus = profile.equipment(settings.get(profile.EQUIPMENT, ""))
        negliges = [
            f"{groupe.muscle_group} : jamais travaillé"
            if groupe.days_since is None
            else f"{groupe.muscle_group} : il y a {groupe.days_since} jour(s)"
            for groupe in await self._neglected()
        ]

        payload = await ai.ask_json(
            instruction=composer.INSTRUCTION,
            prompt=composer.build_prompt(
                demande=request.wish,
                materiel=materiel,
                groupes=[group.value for group in MuscleGroup],
                negliges=negliges,
                contraintes=settings.get(profile.CONSTRAINTS, ""),
            ),
            max_tokens=1200,
        )

        proposal, dropped = composer.read_proposal(
            payload,
            groups={group.value for group in MuscleGroup},
            fallback_group=MuscleGroup.AUTRE.value,
        )
        if proposal is None:
            # La chaîne a fonctionné, la réponse ne contient rien qu'on puisse afficher.
            # Un `503` dirait « réessaie plus tard » ; ici, réessayer ou composer à la main
            # sont deux conduites également valables, et c'est ce que dit `422`.
            raise AiUnreadableError(
                "Le modèle n'a proposé aucun exercice exploitable. Réessaie, ou compose "
                "à la main — le formulaire est juste à côté."
            )

        return CircuitProposal(
            name=proposal.name,
            rounds=proposal.rounds,
            round_rest_s=proposal.round_rest_s,
            exercises=[
                ProposedCircuitExercise(
                    name=item.name,
                    muscle_group=item.muscle_group,
                    duration_s=item.duration_s,
                    reps=item.reps,
                    rest_s=item.rest_s,
                    illustrated=item.illustrated,
                )
                for item in proposal.exercises
            ],
            # L'argument de la proposition, montré à l'écran. Une suggestion dont on voit
            # sur quoi elle s'appuie se discute ; une suggestion nue se croit ou se rejette.
            basis=[
                f"Matériel pris en compte : {', '.join(materiel)}"
                if materiel
                else "Aucun matériel déclaré — poids du corps seulement.",
                *negliges[:3],
            ],
            dropped=dropped,
        )

    async def _neglected(self) -> Sequence[NeglectedGroup]:
        """Les groupes par ancienneté, lus chez `ActivityStats`.

        Importé tardivement : `stats.py` importe ce module pour ses services, et le citer
        en tête ferait un cycle. La règle `ACT-16` y vit déjà — la recopier ici en donnerait
        une seconde version, qui répondrait autrement au premier cas limite.
        """
        from app.domains.activity.stats import ActivityStats

        return (await ActivityStats(self._store).overview(today_local(), limit=1)).neglected

    async def mark_done(self, index: int, payload: CircuitDonePayload) -> Workout:
        """Déclare un circuit fait : une séance **et ses séries** (**D3**), dans les deux
        mondes.

        ## Ce qui est écrit

        Une ligne dans `workouts.csv` — type `HIIT`, `source: cadence`, datée par le
        serveur — puis une ligne de journal par exercice du circuit, avec :

        * `sets` = le nombre de **rounds** : chaque round est bien une série de plus ;
        * `reps` = les répétitions, ou `-1` si l'exercice est au temps ;
        * `weight_kg` = 0, le poids du corps (`ACT-07`), donc un tonnage nul — ce qui est
          vrai. Ce qu'un tabata apporte aux statistiques, ce sont ses **séries** par groupe.

        ## L'ordre, et ce qu'une panne laisse derrière

        Les exercices rejoignent le catalogue **avant** que la séance soit écrite. Le
        stockage n'a pas de transaction : dans cet ordre, une panne laisse au pire une
        entrée de catalogue en trop — visible, corrigeable, sans conséquence. L'ordre
        inverse laisserait une séance sans ses séries, c'est-à-dire une mesure incomplète.

        ## La durée

        **Proposée par l'estimation, corrigée avant l'appui** (**D4**). Sur une séance en
        répétitions personne ne connaît la durée réelle, et l'écrire en silence mettrait
        une valeur inventée dans le volume hebdomadaire.

        ## Et le même geste dans le monde tabata

        La même séance rejoint `circuit_sessions.csv` et ses séries
        `circuit_session_sets.csv` (`docs/refonte-activite.md` §3). C'est le monde qui
        restera quand la musculation historique sera supprimée ; d'ici là les deux sont
        remplis ensemble, ce qui est la seule façon de vérifier le second contre le
        premier avant de rebrancher quoi que ce soit.

        Les deux reçoivent le **même** nombre de séries — les rounds bornés — et le même
        jour. Ce n'est pas une coïncidence à espérer : le chiffre est calculé une fois,
        ici, et passé aux deux.
        """
        rows = await self._repo.read_all()
        if not 0 <= index < len(rows):
            raise StorageNotFoundError("Ce circuit n'existe pas.")

        circuit = rows[index].model
        items = await self._items_of(circuit.id)

        # **Les exercices sans nom sont écartés d'abord, une seule fois.** Le catalogue
        # les filtrait déjà, mais le journal les appariait ensuite par `zip(strict=True)` :
        # une ligne de `circuit_exercises.csv` corrigée à la main sans nom faisait donc un
        # `500` — après que la séance ait été écrite. Filtrer ici plutôt qu'à deux endroits
        # est ce qui garantit que les deux listes ont la même longueur.
        named = [item for item in items if item.name.strip()]

        # Le catalogue d'abord, et en entier : `ensure` peut écrire, et il vaut mieux
        # qu'il ait fini avant que la séance existe.
        catalogue = [await self._exercises.ensure(item.name, _group_of(item)) for item in named]

        day = today_local()
        workout = await self._workouts.create(
            WorkoutPayload(
                date=day,
                type=self.WORKOUT_TYPE,
                duration_min=payload.duration_min,
                rpe=payload.rpe,
                note=circuit.name,
            ),
            source=self.SOURCE,
        )

        rounds = circuit_link.normalise(self._to_link(circuit, items)).rounds
        entries = [
            await self._exercises.log_timed(
                workout.workout_id, day, exercise, sets=rounds, reps=item.reps
            )
            for item, exercise in zip(named, catalogue, strict=True)
        ]

        # Le monde tabata en dernier, et l'ancien inchangé devant lui. Il est encore la
        # seule source des sept consommateurs : une coupure ici doit laisser la séance
        # complète là où on la lit, pas l'inverse. Et si l'utilisateur redéclare après une
        # coupure, le doublon tombe dans le fichier que la phase 6 supprime — pas dans
        # celui qui reste.
        await self._sessions.record(
            circuit,
            items,
            day=day,
            rounds=rounds,
            duration_min=payload.duration_min,
            rpe=payload.rpe,
        )

        return workout.model_copy(update={"exercises": entries})


# ── Séances tabata — ce qui a eu lieu ─────────────────


class CircuitSessionService:
    """Les circuits **déclarés faits**, et les séries qu'ils ont produites.

    Le pendant mesuré de `CircuitService` : celui-là tient des patrons qui se rejouent,
    celui-ci tient ce qui a eu lieu, une fois, un jour donné. Deux fichiers, `paths.py`
    dit pourquoi ils ne fusionnent pas.

    ## Pourquoi ce service existe alors que `workouts.csv` fait déjà le travail

    Il ne le fera plus. Le plan de `docs/refonte-activite.md` supprime la musculation
    historique, et « j'ai fait ce circuit » n'a aujourd'hui **aucun autre endroit où
    s'écrire** : c'est par `workouts.csv` et `exercise_log.csv` qu'un tabata compte dans le
    tableau de bord, l'assiduité, le planning et les rappels. Supprimer ces fichiers sans
    ces deux-là couperait sept consommateurs d'un coup (§3 du plan).

    Pendant cette phase les deux mondes sont donc remplis ensemble, et c'est délibéré :
    tant que les consommateurs lisent l'ancien, le nouveau se vérifie ligne à ligne contre
    lui. Le rebranchement est la phase suivante, et il n'a rien à découvrir.

    ## Ce que ce service n'écrit pas

    **Aucune charge, aucun tonnage** (**C4**). `circuit_loads.csv` reste la seule autorité
    sur ce qu'on charge, et un exercice au temps porte `reps = -1` : le multiplier par une
    charge produirait un tonnage négatif. Ce qu'un tabata apporte aux statistiques, ce sont
    ses **séries par groupe**, et c'est exactement ce que ces deux fichiers portent.
    """

    #: La provenance écrite sur la session, sur le modèle de `WorkoutRow.source`. `IMP-05`
    #: s'applique : corriger une session venue d'ici ne la transformera pas en saisie
    #: manuelle le jour où l'écran laissera la corriger.
    SOURCE = "cadence"

    def __init__(self, store: FileStore) -> None:
        self._repo: CsvRepository[CircuitSessionRow] = CsvRepository(
            store, CIRCUIT_SESSIONS, CircuitSessionRow
        )
        self._sets: CsvRepository[CircuitSessionSetRow] = CsvRepository(
            store, CIRCUIT_SESSION_SETS, CircuitSessionSetRow
        )

    async def all(self) -> list[Row[CircuitSessionRow]]:
        """Les séances tabata, dans l'ordre du fichier.

        Rendu brut et non trié : les consommateurs à rebrancher — agrégats, assiduité,
        planning, rappels — groupent tous par jour et n'ont que faire de l'ordre des
        lignes. Trier ici coûterait un tri à chacun d'eux sans rien leur apporter.
        """
        return await self._repo.read_all()

    async def sets(self) -> list[Row[CircuitSessionSetRow]]:
        """Les séries de toutes les séances, dans l'ordre du fichier.

        Une seule lecture pour toute une fenêtre : l'assiduité compte des séries par groupe
        et par jour sur trois mois, et une lecture par séance ferait autant d'allers-retours
        vers Nextcloud qu'il y a de cases dans la grille.
        """
        return await self._sets.read_all()

    async def record(
        self,
        circuit: CircuitRow,
        items: Sequence[CircuitExerciseRow],
        *,
        day: date,
        rounds: int,
        duration_min: float,
        rpe: int | None = None,
    ) -> CircuitSessionRow:
        """Écrit une séance et ses séries.

        ## Ce que l'appelant fournit, et ce qu'il ne décide pas

        `day` et `rounds` **arrivent déjà décidés** : le jour vient du serveur, et les
        rounds sont ceux que `circuit_link.normalise` a bornés — les mêmes que Cadence
        jouera. Les recalculer ici ferait deux vérités pour un seul chiffre, et le
        symptôme serait quatre séries d'un côté et cent de l'autre pour la même séance.

        ## L'ordre, et ce qu'une panne laisse derrière

        La session d'abord, ses séries ensuite. Le stockage n'a pas de transaction : dans
        cet ordre, une coupure laisse une séance sans ses groupes — visible à l'écran,
        donc corrigeable. L'ordre inverse laisserait des séries rattachées à une séance qui
        n'existe pas, que l'assiduité compterait quand même et que personne ne verrait.

        ## L'identifiant est frappé ici

        `session_id` ne reprend pas le `workout_id` de la séance jumelle, alors que ce
        serait commode le temps de la transition. Il disparaîtrait avec le fichier qui le
        porte : ce monde-ci doit tenir debout seul le jour où l'autre est supprimé.
        """
        session = CircuitSessionRow(
            session_id=new_id(),
            circuit_id=circuit.id,
            date=day,
            name=circuit.name,
            rounds=rounds,
            duration_min=duration_min,
            rpe=rpe,
            source=self.SOURCE,
        )
        row = await self._repo.append(session)

        # Un exercice sans nom ne produit pas de ligne : `ACT-06` duplique le nom pour que
        # l'historique reste lisible sans son patron, et une ligne muette n'y répond pas.
        await self._sets.extend(
            [
                CircuitSessionSetRow(
                    session_id=session.session_id,
                    date=day,
                    exercise_name=item.name.strip(),
                    muscle_group=_group_of(item),
                    sets=rounds,
                    reps=item.reps,
                )
                for item in items
                if item.name.strip()
            ]
        )
        return row.model


# ── Charges des exercices de tabata (**C1**) ──────────


class CircuitLoadService:
    """Ce qu'on charge sur chaque exercice de tabata, et comment ça a bougé.

    ## Ce que ce service ne fait pas

    **Il n'écrit rien dans `exercise_log.csv`** (**C4**). Déclarer un circuit fait continue
    d'y poser `weight_kg = 0`, et la raison tient en un exemple : `stats.py` calcule
    `weight_kg × sets × reps` à quatre endroits, un exercice au temps porte `reps = -1`, et
    un gainage à 20 kg y produirait un tonnage de **-320 kg** — faux, négatif, et muet.

    La conséquence est assumée et écrite dans `docs/charges.md` §1 : le journal de
    `/activite` dira « poids du corps » pour un Rowing effectué à 12 kg. Rouvrir cette
    décision demande de garder `reps == -1` aux quatre endroits d'abord.

    ## Les deux fichiers, et pourquoi ils ne fusionnent pas

    `circuit_loads.csv` dit ce qu'on charge **aujourd'hui** et se corrige ;
    `circuit_load_log.csv` dit ce qu'on a décidé et ne se corrige jamais. Une seule table
    ferait porter à `weight_kg` deux sens selon la ligne — la valeur courante ou une valeur
    passée — ce qui est la façon la plus sûre de casser un CSV qu'on ouvre dans un tableur
    trois ans plus tard (`STO-02`).
    """

    #: La fenêtre de la ligne de points, en jours. Trente, comme le demande l'écran, et
    #: calculée **ici** : le client ne connaît ni sa longueur, ni le jour du serveur.
    WINDOW_DAYS = 30

    def __init__(self, store: FileStore) -> None:
        self._repo: CsvRepository[CircuitLoadRow] = CsvRepository(
            store, CIRCUIT_LOADS, CircuitLoadRow
        )
        self._history: CsvRepository[CircuitLoadLogRow] = CsvRepository(
            store, CIRCUIT_LOAD_LOG, CircuitLoadLogRow
        )
        self._items: CsvRepository[CircuitExerciseRow] = CsvRepository(
            store, CIRCUIT_EXERCISES, CircuitExerciseRow
        )
        self._circuits: CsvRepository[CircuitRow] = CsvRepository(store, CIRCUITS, CircuitRow)
        self._sessions_of = CircuitSessionService(store)

    @staticmethod
    def _state(row: CircuitLoadRow | None) -> LoadState:
        """L'état d'une charge — les trois cas de `CircuitLoadRow`, décidés au même endroit.

        L'écran groupe sur cette étiquette. La lui faire déduire d'un `null` reviendrait à
        lui confier la règle, et il y a exactement trois états à ne pas confondre : « pas
        encore renseigné » n'est pas « poids du corps ».
        """
        if row is None:
            return "unset"
        if row.bodyweight:
            return "bodyweight"
        return "weighted" if row.weight_kg is not None else "unset"

    async def _declared(self) -> dict[str, Row[CircuitLoadRow]]:
        """Les charges déclarées, indexées par nom **replié**.

        Sur doublon — deux lignes pour le même exercice, ce qu'une correction à la main
        peut produire — c'est la **dernière** qui l'emporte : c'est la plus récemment
        écrite, et le fichier se lit de haut en bas.
        """
        return {fold(row.model.name): row for row in await self._repo.read_all() if row.model.name}

    async def _in_circuits(self) -> dict[str, tuple[str, list[str]]]:
        """Les exercices employés par au moins un circuit → `(nom affiché, circuits)`.

        La page ne montre **que** ce qui est constitutif d'une séance tabata : la source
        est `circuit_exercises.csv` et rien d'autre. Un exercice de musculation n'y entre
        pas, sa charge est déjà journalisée série par série dans `exercise_log.csv`.
        """
        names = {row.model.id: row.model.name for row in await self._circuits.read_all()}

        found: dict[str, tuple[str, list[str]]] = {}
        for row in await self._items.read_all():
            item = row.model
            if not item.name.strip():
                continue
            key = fold(item.name)
            display, circuits = found.get(key, (item.name.strip(), []))
            circuit_name = names.get(item.circuit_id, "")
            if circuit_name and circuit_name not in circuits:
                circuits.append(circuit_name)
            found[key] = (display, circuits)
        return found

    async def _since_last_change(self) -> dict[str, tuple[int, int]]:
        """Par exercice replié : `(jours depuis le dernier changement, séances tenues depuis)`.

        Les deux chiffres de « quand monter » (`docs/refonte-activite.md` §5 bis). Le coach
        les **constate**, il n'en conclut rien : « trois séances tenues à 10 kg, dernier
        changement il y a 24 jours » est une mesure, la décision appartient à
        l'utilisateur (**R10**).

        ## Le journal et non `updated`

        `circuit_loads.updated` bouge à chaque enregistrement, y compris celui qui ne
        change rien ; `circuit_load_log.csv` ne retient que les changements **confirmés**
        (**C2**). Compter les jours depuis `updated` dirait « changée aujourd'hui » à qui
        vient de rouvrir une carte sans y toucher — exactement le contraire de ce que le
        chiffre annonce.

        ## Une séance du jour même compte

        La borne est `>=` et non `>`. La page Charges existe pour **remplir le 4ᵉ champ du
        lien avant la séance** (**C7**) : noter 12 kg puis jouer le tabata dans la foulée
        est le geste normal, et ces deux-là tombent le même jour. Les exclure ferait un
        compteur qui n'avance jamais pour qui note sa charge au bon moment. Le prix est
        l'inverse — une charge notée le soir d'une séance déjà faite compte cette séance —
        et il est plus petit.
        """
        last_change: dict[str, date] = {}
        for row in await self._history.read_all():
            item = row.model
            if not item.name.strip():
                continue
            key = fold(item.name)
            # La **dernière** date, jamais la dernière ligne : le fichier se trie dans un
            # tableur, et un journal réordonné ne doit pas rajeunir une charge.
            known = last_change.get(key)
            if known is None or item.date > known:
                last_change[key] = item.date

        if not last_change:
            return {}

        held: defaultdict[str, set[str]] = defaultdict(set)
        for serie in await self._sessions_of.sets():
            entry = serie.model
            key = fold(entry.exercise_name)
            since = last_change.get(key)
            if since is not None and entry.date >= since:
                held[key].add(entry.session_id)

        today = today_local()
        return {key: ((today - day).days, len(held[key])) for key, day in last_change.items()}

    async def list(self) -> LoadList:
        """Tous les exercices de tabata, et leur charge quand elle est déclarée.

        Une seule lecture de chaque fichier pour toute la liste : une par exercice ferait
        autant d'allers-retours Nextcloud qu'il y a de cartes à l'écran.

        L'ordre est celui de l'écran : ce qui reste à renseigner d'abord — c'est le seul
        endroit où il y a encore un geste à faire — puis les chargés, puis le poids du
        corps. À état égal, l'ordre alphabétique, qui ne bouge pas d'un affichage à l'autre.
        """
        declared = await self._declared()
        in_circuits = await self._in_circuits()
        progression = await self._since_last_change()

        order = {"unset": 0, "weighted": 1, "bodyweight": 2}
        loads = []
        for key, (display, circuits) in in_circuits.items():
            row = declared.get(key)
            state = self._state(row.model if row else None)
            loads.append(
                Load(
                    id=row.index if row else None,
                    token=row.token if row else None,
                    name=display,
                    state=state,
                    weight_kg=row.model.weight_kg if row and state == "weighted" else None,
                    updated=row.model.updated if row else None,
                    circuits=len(circuits),
                    days_since_change=progression.get(key, (None, None))[0],
                    sessions_since=progression.get(key, (None, None))[1],
                )
            )

        loads.sort(key=lambda load: (order[load.state], fold(load.name)))
        return LoadList(loads=loads)

    async def detail(self, name: str) -> LoadDetail:
        """La courbe des décisions et les trente derniers jours de séances.

        **Par nom et non par position** : une position se décale à la première suppression,
        et un exercice jamais renseigné n'a aucune ligne dont on pourrait donner la
        position. Le rapprochement passe par `fold`.
        """
        key = fold(name)
        in_circuits = await self._in_circuits()
        if key not in in_circuits:
            raise StorageNotFoundError("Cet exercice n'est dans aucune séance.")

        display, circuits = in_circuits[key]
        row = (await self._declared()).get(key)
        state = self._state(row.model if row else None)

        history = [
            LoadPoint(
                date=item.model.date,
                weight_kg=None if item.model.bodyweight else item.model.weight_kg,
            )
            for item in await self._history.read_all()
            if fold(item.model.name) == key
        ]
        # Trié ici et non supposé trié : le fichier peut être réordonné dans un tableur, et
        # une courbe qui repart en arrière ne se voit pas comme un défaut de lecture.
        history.sort(key=lambda point: point.date)

        return LoadDetail(
            name=display,
            state=state,
            weight_kg=row.model.weight_kg if row and state == "weighted" else None,
            history=history,
            sessions=await self._sessions(key),
            circuits=circuits,
        )

    # `Sequence` et non `list`, pour la raison écrite plus haut sur `CircuitService` :
    # cette classe porte une méthode `list`, qui masque le type dans toute annotation de
    # son corps, et mypy le signale sans jamais nommer la collision.
    async def _sessions(self, key: str) -> Sequence[LoadDay]:
        """Les trente derniers jours, un par entrée, séances comptées.

        **Exactement trente entrées**, y compris les jours à zéro. Ici zéro est une mesure
        et non une valeur inventée : on a compté, et il n'y en a pas eu — c'est même toute
        l'information que porte une ligne de points.

        Le compte est celui des **séances**, pas des lignes de journal : un circuit qui
        emploie deux fois le même exercice ne vaut pas deux séances.

        La source est `circuit_session_sets.csv` depuis le rebranchement du coach : c'est
        le seul historique de séances qui survivra à la suppression de `exercise_log.csv`,
        et il porte exactement ce qu'il faut — un `session_id`, un jour, un nom d'exercice.
        """
        last = today_local()
        first = last - timedelta(days=self.WINDOW_DAYS - 1)

        per_day: defaultdict[date, set[str]] = defaultdict(set)
        for row in await self._sessions_of.sets():
            entry = row.model
            if first <= entry.date <= last and fold(entry.exercise_name) == key:
                per_day[entry.date].add(entry.session_id)

        return [
            LoadDay(date=day, count=len(per_day.get(day, set())))
            for day in (first + timedelta(days=offset) for offset in range(self.WINDOW_DAYS))
        ]

    # ── Écriture ──────────────────────────────────────

    @staticmethod
    def _to_row(payload: LoadPayload, day: date) -> CircuitLoadRow:
        """La ligne à écrire. **Les deux champs s'excluent**, et c'est ici que ça se tient :
        déclarer le poids du corps efface la charge, poser une charge lève le drapeau."""
        return CircuitLoadRow(
            name=payload.name.strip(),
            weight_kg=None if payload.bodyweight else payload.weight_kg,
            bodyweight=payload.bodyweight,
            updated=day,
        )

    async def _remember(self, payload: LoadPayload, day: date) -> None:
        """Ajoute une ligne au journal des changements (**C2**).

        Appelée après l'écriture de la valeur courante, et non avant : le stockage n'a pas
        de transaction, et dans cet ordre une panne laisse au pire un journal en retard
        d'une ligne. L'ordre inverse laisserait un historique qui affirme une charge que le
        fichier courant ne porte pas.
        """
        await self._history.append(
            CircuitLoadLogRow(
                name=payload.name.strip(),
                date=day,
                weight_kg=None if payload.bodyweight else payload.weight_kg,
                bodyweight=payload.bodyweight,
            )
        )

    async def create(self, payload: LoadPayload) -> Load:
        """Déclare la première charge d'un exercice — une **addition**.

        Rien à garder : il n'y a pas encore de ligne, donc pas de jeton. C'est la correction
        suivante qui passe sous `If-Match` (`STO-05`).

        Un exercice déjà déclaré est un **conflit** et non une seconde ligne : deux lignes
        pour un même nom feraient deux charges, et la lecture n'en garderait qu'une sans
        rien dire de l'autre.
        """
        key = fold(payload.name)
        if key in await self._declared():
            raise StorageConflictError(detail=f"charge déjà déclarée pour {payload.name}")

        day = today_local()
        await self._repo.append(self._to_row(payload, day))
        await self._remember(payload, day)
        return await self._one(key)

    async def update(self, index: int, token: str, payload: LoadPayload) -> Load:
        """Corrige une charge, sous garde anti-conflit (`STO-05`).

        **Le journal ne s'écrit que si la valeur a changé.** Sans cette garde, réenregistrer
        une carte sans y toucher poserait un point de plus sur la courbe, au même niveau —
        une évolution qui n'a pas eu lieu.
        """
        rows = await self._repo.read_all(fresh=True)
        if not 0 <= index < len(rows):
            raise StorageConflictError(detail=f"charge {index} absente")

        before = rows[index].model
        day = today_local()
        await self._repo.replace_by_token(index, token, self._to_row(payload, day))

        changed = before.bodyweight != payload.bodyweight or before.weight_kg != payload.weight_kg
        if changed:
            await self._remember(payload, day)

        return await self._one(fold(payload.name))

    async def _one(self, key: str) -> Load:
        """La carte d'un exercice après écriture, relue depuis la liste.

        Relue et non reconstruite : c'est la même méthode qui décide de l'état, du nom
        affiché et du nombre de circuits, donc il n'y a qu'un endroit où ces trois règles
        vivent.
        """
        for load in (await self.list()).loads:
            if fold(load.name) == key:
                return load
        raise StorageNotFoundError("Cet exercice n'est dans aucune séance.")
