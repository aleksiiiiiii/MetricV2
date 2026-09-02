"""Endpoints du domaine Activité (`ACT-01` → `ACT-18`).

Même garde qu'ailleurs : les lectures rendent un `token` par ligne, les écritures
destructrices l'exigent en `If-Match` (`STO-05`, voir `docs/patron-domaine.md`).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, File, Form, Header, Path, Query, UploadFile, status

from app.core.deps import StoreDep
from app.core.exceptions import ValidationFailedError
from app.core.validation import today_local
from app.domains.activity.models import WORKOUT_TYPES, MuscleGroup
from app.domains.activity.schemas import (
    ActivityOverview,
    Circuit,
    CircuitDonePayload,
    CircuitImportPayload,
    CircuitList,
    CircuitPayload,
    CircuitProposal,
    CircuitSuggestion,
    ComposeRequest,
    Exercise,
    ExerciseEntry,
    ExerciseEntryPayload,
    ExercisePayload,
    ExerciseProgress,
    Load,
    LoadDetail,
    LoadList,
    LoadPayload,
    NoteDraft,
    Run,
    RunDetail,
    RunPayload,
    RunProgress,
    Workout,
    WorkoutPayload,
)
from app.domains.activity.service import (
    CircuitLoadService,
    CircuitService,
    ExerciseService,
    RunService,
    WorkoutService,
)
from app.domains.activity.stats import ActivityStats
from app.domains.ai.deps import AiServiceDep
from app.storage.errors import StorageConflictError

router = APIRouter(prefix="/activity", tags=["activité"])

RowId = Annotated[int, Path(ge=0, description="Position de la ligne dans le fichier")]
IfMatch = Annotated[
    str | None, Header(alias="If-Match", description="Jeton de la ligne, tel que rendu")
]


def _token(value: str | None) -> str:
    if not value:
        raise StorageConflictError(
            "Recharge la donnée avant de la modifier.", detail="en-tête If-Match absent"
        )
    return value.strip('"')


# ── Vue d'ensemble ────────────────────────────────────


@router.get("", response_model=ActivityOverview, summary="Semaine, volumes et historique")
async def overview(
    store: StoreDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 30,
) -> ActivityOverview:
    """Totaux de la semaine, volume par jour, huit semaines, tonnage, groupes négligés
    et historique fusionné — en une requête."""
    return await ActivityStats(store).overview(today_local(), limit=limit)


@router.get("/progress", response_model=list[ExerciseProgress], summary="Progression des charges")
async def progress(store: StoreDep) -> list[ExerciseProgress]:
    return await ActivityStats(store).progress()


@router.get("/types", response_model=list[str], summary="Types de séance suggérés")
def workout_types() -> list[str]:
    """Suggestions et non contrainte : le champ reste libre (`ACT-03`)."""
    return list(WORKOUT_TYPES)


@router.get("/muscle-groups", response_model=list[str], summary="Groupes musculaires")
def muscle_groups() -> list[str]:
    """La taxonomie de saisie (`ACT-06`), pour que le client ne la duplique pas."""
    return [group.value for group in MuscleGroup]


# ── Courses ───────────────────────────────────────────


@router.post(
    "/runs",
    response_model=Run,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer une course",
)
async def create_run(payload: RunPayload, store: StoreDep) -> Run:
    return await RunService(store).create(payload)


@router.get(
    "/runs/latest",
    response_model=RunDetail,
    summary="La dernière course, paliers compris",
)
async def latest_run(store: StoreDep) -> RunDetail:
    """La course la plus récente et ses paliers (`ACT-19`).

    **Déclarée avant `/runs/{row_id}`**, et ce n'est pas une préférence de lecture :
    FastAPI essaie les routes dans l'ordre, et `latest` se ferait sinon happer par le
    motif d'identifiant, qui n'accepte qu'un entier — donc un `422` sur une adresse
    parfaitement valide.

    Un historique vide rend un détail vide et non un `404` : l'écran en tire son état
    « aucune course » plutôt qu'une erreur.
    """
    return await RunService(store).latest()


@router.get(
    "/runs/progress",
    response_model=RunProgress,
    summary="Toutes les courses et leur progression",
)
async def run_progress(store: StoreDep) -> RunProgress:
    """La liste complète des courses et ce qu'elles racontent (`ACT-20`).

    **Déclarée avant `/runs/{row_id}`** pour la même raison que `latest` : le motif
    d'identifiant n'accepte qu'un entier et rendrait un `422` sur une adresse valide.

    Une seule requête pour la liste **et** les agrégats. En scinder deux aurait laissé
    l'écran assembler deux réponses de fraîcheurs différentes, et recoller des chiffres
    est exactement ce que le tableau de bord vient d'abandonner.
    """
    return await RunService(store).progress()


@router.get("/runs/{row_id}", response_model=Run, summary="Détail d'une course")
async def read_run(row_id: RowId, store: StoreDep) -> Run:
    return await RunService(store).get(row_id)


@router.get(
    "/runs/{row_id}/splits",
    response_model=RunDetail,
    summary="Une course et ses paliers",
)
async def read_run_splits(row_id: RowId, store: StoreDep) -> RunDetail:
    """Les paliers d'une course, et ce qu'ils disent d'elle (`ACT-19`).

    Une course sans paliers — toute saisie au clavier l'est — rend une liste vide, pas une
    erreur : ne pas avoir de détail n'est pas un défaut de la course.
    """
    return await RunService(store).detail(row_id)


@router.patch("/runs/{row_id}", response_model=Run, summary="Corriger une course")
async def update_run(
    row_id: RowId, payload: RunPayload, store: StoreDep, if_match: IfMatch = None
) -> Run:
    return await RunService(store).update(row_id, _token(if_match), payload)


@router.delete(
    "/runs/{row_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer une course"
)
async def delete_run(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    await RunService(store).delete(row_id, _token(if_match))


# ── Séances ───────────────────────────────────────────


@router.post(
    "/workouts",
    response_model=Workout,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer une séance",
)
async def create_workout(payload: WorkoutPayload, store: StoreDep) -> Workout:
    return await WorkoutService(store).create(payload)


@router.get("/workouts/{row_id}", response_model=Workout, summary="Détail d'une séance")
async def read_workout(row_id: RowId, store: StoreDep) -> Workout:
    return await WorkoutService(store).get(row_id)


@router.patch("/workouts/{row_id}", response_model=Workout, summary="Corriger une séance")
async def update_workout(
    row_id: RowId, payload: WorkoutPayload, store: StoreDep, if_match: IfMatch = None
) -> Workout:
    return await WorkoutService(store).update(row_id, _token(if_match), payload)


@router.delete(
    "/workouts/{row_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer une séance"
)
async def delete_workout(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    """Supprime la séance **et purge ses exercices** (`ACT-04`)."""
    await WorkoutService(store).delete(row_id, _token(if_match))


@router.post(
    "/workouts/{row_id}/duplicate",
    response_model=Workout,
    status_code=status.HTTP_201_CREATED,
    summary="Dupliquer une séance",
)
async def duplicate_workout(
    row_id: RowId,
    store: StoreDep,
    day: Annotated[date | None, Body(embed=True, alias="date")] = None,
) -> Workout:
    """Recrée une séance passée, exercices compris (`ACT-17`)."""
    return await WorkoutService(store).duplicate(row_id, day or today_local())


# ── Exercices ─────────────────────────────────────────


@router.get("/exercises", response_model=list[Exercise], summary="Catalogue d'exercices")
async def list_exercises(store: StoreDep) -> list[Exercise]:
    """Catalogue enrichi de la dernière performance de chaque exercice (`ACT-08`)."""
    return await ExerciseService(store).catalogue()


@router.post(
    "/exercises",
    response_model=Exercise,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter un exercice",
)
async def create_exercise(payload: ExercisePayload, store: StoreDep) -> Exercise:
    return await ExerciseService(store).create(payload)


@router.patch("/exercises/{row_id}", response_model=Exercise, summary="Corriger un exercice")
async def update_exercise(
    row_id: RowId, payload: ExercisePayload, store: StoreDep, if_match: IfMatch = None
) -> Exercise:
    """Corrige le nom ou le groupe, et répercute la correction sur les séries (`ACT-06`).

    L'identifiant de l'exercice ne change pas : c'est lui qui porte tout l'historique.
    """
    return await ExerciseService(store).update(row_id, _token(if_match), payload)


@router.delete(
    "/exercises/{row_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Retirer un exercice"
)
async def delete_exercise(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    """Retire du catalogue sans toucher au journal : l'historique survit (`ACT-06`)."""
    await ExerciseService(store).delete(row_id, _token(if_match))


# ── Lecture d'une séance écrite en clair (`C07`) ──────


@router.post("/notes/read", response_model=NoteDraft, summary="Lire une séance en notes libres")
async def read_notes(
    ai: AiServiceDep,
    store: StoreDep,
    text: Annotated[str | None, Form(max_length=4000)] = None,
    photo: Annotated[UploadFile | None, File()] = None,
) -> NoteDraft:
    """Traduit « développé couché 4x8 60kg / tractions 3xmax » en lignes relisables.

    **Rien n'est écrit** : ni séance, ni série, ni entrée de catalogue. Ce qui sort d'ici
    est un tableau que l'écran fait valider ligne par ligne — une fusion de deux noms est
    difficile à défaire et pollue l'historique, elle ne peut pas se faire en silence.

    Texte ou photo, jamais rien : une photo passe par le **même modèle** que le reste,
    avec la même consigne. L'OCR n'est pas une brique à part.
    """
    data = await photo.read() if photo is not None else None
    if photo is not None:
        await photo.close()

    written = (text or "").strip()
    if not data and not written:
        raise ValidationFailedError("Colle tes notes, ou choisis une photo.")

    return await ExerciseService(store).read_notes(ai, written, data)


@router.post(
    "/exercises/{exercise_id}/aliases",
    response_model=Exercise,
    summary="Reconnaître une autre écriture d'un exercice",
)
async def add_alias(
    exercise_id: Annotated[str, Path(min_length=1, max_length=40)],
    store: StoreDep,
    alias: Annotated[str, Body(embed=True, max_length=80)],
) -> Exercise:
    """Ajoute une graphie reconnue à un exercice existant (`C07`).

    C'est ce qui rend la lecture de notes de plus en plus silencieuse : « dev couché »
    validé une fois est reconnu tout seul les fois suivantes. **Le nom du catalogue ne
    change pas** — un alias s'ajoute à côté de lui, il ne le remplace jamais.

    Sans garde `If-Match`, comme le renommage d'un fil : l'exercice se désigne par son
    identifiant stable et non par sa position, et l'opération est sûre à rejouer — un
    alias déjà connu ne se réécrit pas.
    """
    return await ExerciseService(store).add_alias(exercise_id, alias)


# ── Journal d'exercices ───────────────────────────────


@router.post(
    "/workouts/{row_id}/exercises",
    response_model=ExerciseEntry,
    status_code=status.HTTP_201_CREATED,
    summary="Consigner une performance",
)
async def log_exercise(
    row_id: RowId, payload: ExerciseEntryPayload, store: StoreDep
) -> ExerciseEntry:
    workout = await WorkoutService(store).get(row_id)
    return await ExerciseService(store).log(workout.workout_id, workout.date, payload)


@router.patch(
    "/exercise-log/{row_id}", response_model=ExerciseEntry, summary="Corriger une performance"
)
async def update_exercise_entry(
    row_id: RowId, payload: ExerciseEntryPayload, store: StoreDep, if_match: IfMatch = None
) -> ExerciseEntry:
    return await ExerciseService(store).update_entry(row_id, _token(if_match), payload)


@router.delete(
    "/exercise-log/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une performance",
)
async def delete_exercise_entry(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    await ExerciseService(store).delete_entry(row_id, _token(if_match))


# ── Circuits ouverts dans Cadence Tabata (**D2**) ─────


@router.get("/circuits", response_model=CircuitList, summary="Circuits enregistrés")
async def list_circuits(store: StoreDep) -> CircuitList:
    """Les circuits, du plus récent au plus ancien, avec leur lien déjà construit.

    Le client ne fabrique aucune adresse : l'échappement, le bornage et le suffixe `x` qui
    distingue quinze répétitions de quinze secondes sont des règles, pas du formatage
    (**D7**). `url` vaut `null` tant que `cadence_base_url` n'est pas réglée, et `linkable`
    dit lequel des deux états vides l'écran doit annoncer.
    """
    return await CircuitService(store).list()


@router.post(
    "/circuits",
    response_model=Circuit,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer un circuit",
)
async def create_circuit(payload: CircuitPayload, store: StoreDep) -> Circuit:
    return await CircuitService(store).create(payload)


@router.post(
    "/circuits/import",
    response_model=Circuit,
    status_code=status.HTTP_201_CREATED,
    summary="Relire un lien Cadence",
)
async def import_circuit(payload: CircuitImportPayload, store: StoreDep) -> Circuit:
    """Décode un lien collé et l'enregistre. Un lien illisible est refusé avec son code."""
    return await CircuitService(store).import_link(payload.url)


@router.get(
    "/circuits/exercises",
    response_model=list[CircuitSuggestion],
    summary="Noms d'exercices proposés",
)
async def list_circuit_exercises(
    store: StoreDep,
    q: Annotated[str, Query(max_length=80, description="Recherche par nom")] = "",
    body_part: Annotated[str | None, Query(description="Zone du corps du catalogue")] = None,
    equipment: Annotated[str | None, Query(description="Matériel du catalogue")] = None,
) -> Sequence[CircuitSuggestion]:
    """Les noms à proposer à la saisie : ceux du catalogue de Metric, puis ceux de Cadence.

    **Déclarée avant `/circuits/{row_id}`**, et ce n'est pas cosmétique : `row_id` est un
    entier, mais une route déclarée plus tôt gagne, et l'ordre inverse ferait répondre
    `422` à « exercises » plutôt que cette liste.

    Une recherche vide est légitime et rend le début du catalogue : c'est ce qui permet à
    « je n'ai que des haltères » d'être une question sans mot-clé.
    """
    return await CircuitService(store).suggestions(q, body_part=body_part, equipment=equipment)


@router.get("/circuits/{row_id}", response_model=Circuit, summary="Détail d'un circuit")
async def read_circuit(row_id: RowId, store: StoreDep) -> Circuit:
    return await CircuitService(store).get(row_id)


@router.patch("/circuits/{row_id}", response_model=Circuit, summary="Corriger un circuit")
async def update_circuit(
    row_id: RowId, payload: CircuitPayload, store: StoreDep, if_match: IfMatch = None
) -> Circuit:
    """Corrige un circuit. Son identifiant stable et sa date de création ne bougent pas ;
    ses exercices sont remplacés en bloc."""
    return await CircuitService(store).update(row_id, _token(if_match), payload)


@router.delete(
    "/circuits/{row_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer un circuit"
)
async def delete_circuit(row_id: RowId, store: StoreDep, if_match: IfMatch = None) -> None:
    """Supprime le circuit et ses exercices. Les liens déjà collés ailleurs survivent :
    une URL Cadence porte la séance entière."""
    await CircuitService(store).delete(row_id, _token(if_match))


@router.post(
    "/circuits/propose",
    response_model=CircuitProposal,
    summary="Composer une séance assistée",
)
async def compose_circuit(
    payload: ComposeRequest, store: StoreDep, ai: AiServiceDep
) -> CircuitProposal:
    """Une phrase, un circuit **proposé**. Rien n'est écrit (**R5**).

    Le matériel possédé, les contraintes et les groupes négligés partent avec la demande
    sans qu'on ait à les taper : c'est ce qui rend « fais-moi 30 minutes » répondable.

    Sans clé OpenRouter, `AiServiceDep` fait échouer l'endpoint avec un code du catalogue
    avant même d'entrer ici (`IA-07`) — le formulaire manuel de `/activite/seances`, lui,
    reste entier.

    **Aucun lien n'est fabriqué ici** (**D7**). Le modèle nomme des exercices ; l'URL naît
    à la lecture du circuit, une fois enregistré.
    """
    return await CircuitService(store).compose(ai, payload)


@router.post(
    "/circuits/{row_id}/done",
    response_model=Workout,
    status_code=status.HTTP_201_CREATED,
    summary="Déclarer un circuit fait",
)
async def complete_circuit(row_id: RowId, payload: CircuitDonePayload, store: StoreDep) -> Workout:
    """Écrit une séance `HIIT` marquée `cadence`, et **rien d'autre** (**D3**).

    Aucun `If-Match` : c'est une **addition**, pas une modification. Elle se défait par la
    suppression que l'utilisateur ferait de toute façon, et l'invariant est explicite —
    demander confirmation partout finit par la faire ignorer là où elle compte.

    Cadence ne peut pas dire à Metric qu'une séance a eu lieu (**D6**) : rien n'empêche
    donc de la déclarer deux fois, et rien ne rappellera de la déclarer. C'est assumé.
    """
    return await CircuitService(store).mark_done(row_id, payload)


# ── Charges des exercices de tabata (**C1**) ──────────


@router.get("/loads", response_model=LoadList, summary="Charges des exercices de tabata")
async def list_loads(store: StoreDep) -> LoadList:
    """Les exercices constitutifs d'une séance tabata, et leur charge quand elle existe.

    La liste vient de `circuit_exercises.csv` et d'elle seule : un exercice de musculation
    n'y entre pas, sa charge est déjà journalisée série par série.

    `id` et `token` sont à `null` tant qu'aucune charge n'a été déclarée — il n'y a alors
    aucune ligne. C'est ce couple qui dit à l'écran de poster plutôt que de corriger.
    """
    return await CircuitLoadService(store).list()


@router.get("/loads/detail", response_model=LoadDetail, summary="Détail d'une charge")
async def read_load(
    store: StoreDep,
    name: Annotated[str, Query(min_length=1, max_length=80, description="Nom de l'exercice")],
) -> LoadDetail:
    """La courbe des décisions de charge, et les trente derniers jours de séances.

    **Par nom et non par position**, et ce n'est pas un écart au patron : une position se
    décale à la première suppression, et un exercice jamais renseigné n'a aucune ligne dont
    on pourrait donner la position. Le rapprochement passe par `fold`.

    **Déclarée avant `/loads/{row_id}`** pour la même raison que `/circuits/exercises` :
    une route déclarée plus tôt gagne, et l'ordre inverse ferait répondre `422`.
    """
    return await CircuitLoadService(store).detail(name)


@router.post(
    "/loads",
    response_model=Load,
    status_code=status.HTTP_201_CREATED,
    summary="Déclarer une charge",
)
async def create_load(payload: LoadPayload, store: StoreDep) -> Load:
    """Déclare la première charge d'un exercice, ou son poids du corps.

    Aucun `If-Match` : il n'y a pas encore de ligne, donc pas de jeton à garder. C'est une
    **addition**, et la correction suivante passe sous la garde (`STO-05`).
    """
    return await CircuitLoadService(store).create(payload)


@router.patch("/loads/{row_id}", response_model=Load, summary="Corriger une charge")
async def update_load(
    row_id: RowId, payload: LoadPayload, store: StoreDep, if_match: IfMatch = None
) -> Load:
    """Corrige une charge, sous garde anti-conflit (`STO-05`).

    Le journal des changements n'accueille une ligne que si la valeur a **réellement**
    bougé : réenregistrer une carte sans y toucher ne pose pas un point de plus sur la
    courbe (**C2**).
    """
    return await CircuitLoadService(store).update(row_id, _token(if_match), payload)
