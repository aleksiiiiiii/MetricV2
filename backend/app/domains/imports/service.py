"""Import d'une capture Apple : analyser, avertir, puis — seulement — écrire.

Les deux moitiés de ce service ne se touchent pas, et c'est tout le contrat de `IMP-01` :

* `analyze` **ne connaît pas le dépôt en écriture**. Elle lit une image, interroge un
  modèle, relit sa réponse, et va chercher dans l'historique s'il existe déjà quelque
  chose qui y ressemble. Aucune ligne n'est créée, aucun fichier n'est touché.
* `confirm` n'a plus rien à voir avec l'IA. Elle reçoit ce que l'utilisateur a validé —
  souvent corrigé — et l'écrit par les services du domaine Activité, avec les mêmes
  bornes, la même normalisation et le même format de fichier qu'une saisie au clavier.

Entre les deux il y a un écran et un appui : c'est là que vit « rien n'est écrit sans
validation », et c'est pour cela que le pré-remplissage n'a pas de jeton — il ne désigne
aucune ligne, puisqu'il n'en existe encore aucune.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from app.core.dates import today_local
from app.core.exceptions import AiUnreadableError
from app.domains.activity.schemas import RunPayload, WorkoutPayload
from app.domains.activity.service import RunService, WorkoutService
from app.domains.ai.images import prepare_data_url
from app.domains.ai.service import AiService
from app.domains.imports.analysis import INSTRUCTION, PROMPT, is_unreadable, read_draft
from app.domains.imports.schemas import (
    AppleDraft,
    AppleImportPayload,
    DuplicateWarning,
    ImportResult,
)
from app.storage.files import FileStore

#: Tolérance de la détection de doublon (`IMP-04`) : « une durée proche à la minute près ».
#: Une même sortie relevée par la montre et par le téléphone diffère de quelques secondes ;
#: deux séances réellement distinctes du même jour diffèrent de bien plus.
DUPLICATE_TOLERANCE_MIN = 1.0


class AppleImportService:
    def __init__(self, store: FileStore) -> None:
        self._runs = RunService(store)
        self._workouts = WorkoutService(store)

    # ── Analyse (`IMP-01` → `IMP-04`, `IMP-06`) ───────

    async def analyze(
        self, ai: AiService, screenshots: Sequence[bytes], *, today: date | None = None
    ) -> AppleDraft:
        """Lit une ou plusieurs captures d'une **même** séance. **N'écrit rien.**

        Plusieurs images parce qu'Apple sépare ce qui va ensemble : le résumé sur un écran,
        les paliers derrière un appui. Les envoyer en un seul appel plutôt qu'un appel par
        image n'est pas une économie de requêtes — c'est ce qui permet au modèle de rendre
        **une** liste de paliers fusionnée plutôt que deux listes qu'il faudrait recoller
        ici, sans savoir laquelle recouvre l'autre.

        L'ordre est conservé jusqu'au corps de la requête : la consigne parle du résumé
        comme de la première capture.
        """
        payload = await ai.ask_json(
            instruction=INSTRUCTION,
            prompt=PROMPT,
            images=[prepare_data_url(shot) for shot in screenshots],
            # Neuf paliers pèsent près de mille caractères de JSON à eux seuls. Le plafond
            # d'avant — 600 jetons, posé pour un résumé — tronquait la liste en plein objet,
            # et une réponse tronquée n'est pas une réponse partielle : elle n'a plus de
            # JSON du tout, donc plus de course non plus.
            max_tokens=2000,
        )

        draft = read_draft(payload, today=today or today_local())
        if is_unreadable(payload, draft):
            raise AiUnreadableError

        draft.duplicate = await self.find_duplicate(draft)
        return draft

    async def find_duplicate(self, draft: AppleDraft) -> DuplicateWarning | None:
        """Activité déjà enregistrée qui ressemble au brouillon (`IMP-04`).

        Sans date ni durée, la question n'a pas de sens : on ne cherche pas. Annoncer
        « aucun doublon » quand on n'a rien pu comparer serait une fausse assurance.
        """
        if draft.date is None or draft.duration_min is None:
            return None

        if draft.kind == "run":
            for run in await self._runs.all():
                if run.model.date == draft.date and self._close(
                    run.model.duration_min, draft.duration_min
                ):
                    return DuplicateWarning(
                        kind="run",
                        id=run.index,
                        date=run.model.date,
                        label=f"Course de {run.model.distance_km:.2f} km".replace(".", ","),
                        duration_min=run.model.duration_min,
                    )
            return None

        for workout in await self._workouts.all():
            if workout.model.date == draft.date and self._close(
                workout.model.duration_min, draft.duration_min
            ):
                return DuplicateWarning(
                    kind="workout",
                    id=workout.index,
                    date=workout.model.date,
                    label=workout.model.type,
                    duration_min=workout.model.duration_min,
                )
        return None

    @staticmethod
    def _close(existing: float, proposed: float) -> bool:
        return abs(existing - proposed) <= DUPLICATE_TOLERANCE_MIN

    # ── Écriture, après validation (`IMP-01`, `IMP-05`) ──

    async def confirm(self, payload: AppleImportPayload) -> ImportResult:
        """Écrit ce que l'utilisateur a validé, marqué `source=apple` (`IMP-05`).

        Passe par les services du domaine Activité et non par le dépôt : l'allure, les
        identifiants de séance et l'ordre des colonnes sont leur affaire, et un import qui
        écrirait lui-même finirait par produire des lignes légèrement différentes de
        celles du formulaire.
        """
        if payload.kind == "run":
            # Distance **ou** allure, garanti par le schéma. Les deux passent telles
            # quelles : c'est `RunPayload` qui tranche laquelle fait foi, en un seul
            # endroit — la dupliquer ici la ferait diverger au premier cas limite.
            run = await self._runs.create(
                RunPayload(
                    date=payload.date,
                    distance_km=payload.distance_km,
                    pace_min_km=payload.pace_min_km,
                    duration_min=payload.duration_min,
                    avg_hr=payload.avg_hr,
                    elevation_m=payload.elevation_m,
                    cadence_spm=payload.cadence_spm,
                    note=payload.note,
                    active_calories=payload.calories,
                    total_calories=payload.total_calories,
                    start_time=payload.start_time,
                    end_time=payload.end_time,
                    split_length_km=payload.split_length_km,
                    splits=payload.splits,
                ),
                source="apple",
            )
            return ImportResult(
                kind="run",
                id=run.id,
                date=run.date,
                label=payload.type,
                duration_min=run.duration_min,
                distance_km=run.distance_km,
                source=run.source,
            )

        workout = await self._workouts.create(
            WorkoutPayload(
                date=payload.date,
                type=payload.type,
                duration_min=payload.duration_min,
                calories=payload.calories,
                # L'effort perçu appartient à celui qui l'a vécu : aucune capture ne le
                # porte, et le déduire d'une fréquence cardiaque serait l'inventer.
                rpe=None,
                note=payload.note,
            ),
            source="apple",
        )
        return ImportResult(
            kind="workout",
            id=workout.id,
            date=workout.date,
            label=workout.type,
            duration_min=workout.duration_min,
            source=workout.source,
        )
