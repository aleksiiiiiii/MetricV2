"""Écriture et lecture du domaine Activité (`ACT-01` → `ACT-09`, `ACT-17`).

Les agrégats hebdomadaires et les progressions vivent dans `stats.py` : ce module ne
s'occupe que du cycle de vie des lignes.
"""

from __future__ import annotations

import secrets
from datetime import date

from app.core.exceptions import AiUnreadableError
from app.core.parsing import estimate_one_rep_max, pace_min_per_km
from app.core.text import fold
from app.domains.activity import notes, splits
from app.domains.activity.models import (
    ExerciseLogRow,
    ExerciseRow,
    RunRow,
    RunSplitRow,
    WorkoutRow,
)
from app.domains.activity.schemas import (
    Exercise,
    ExerciseEntry,
    ExerciseEntryPayload,
    ExercisePayload,
    NoteDraft,
    Run,
    RunContext,
    RunDetail,
    RunMark,
    RunPayload,
    RunSplit,
    RunSplits,
    Workout,
    WorkoutPayload,
)
from app.domains.ai.images import prepare_data_url
from app.domains.ai.service import AiService
from app.storage.csv_repo import CsvRepository, Row
from app.storage.errors import StorageConflictError, StorageNotFoundError
from app.storage.files import FileStore
from app.storage.paths import EXERCISE_LOG, EXERCISES, RUN_SPLITS, RUNS, WORKOUTS

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
