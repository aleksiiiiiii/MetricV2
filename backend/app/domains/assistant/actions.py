"""Ce que l'assistant a le droit de faire dans les données (`IA-15`).

Une table, et **elle est la seule autorité**. Le modèle nomme une intention ; c'est ici
qu'on décide si elle existe, ce qu'elle exige, et si elle s'exécute ou si elle attend un
appui.

## Trois garanties, et elles tiennent toutes les trois à la même ligne de code

**L'IA ne peut rien faire que l'API ne permettrait.** Chaque action réutilise le schéma de
charge utile du domaine — `WeightPayload`, `PlanPayload`, `MealPayload` — et appelle son
service. Pas une validation parallèle, pas un chemin d'écriture parallèle : le même. Une
borne de vraisemblance ajoutée un jour au domaine protégera l'assistant le jour même,
sans que personne y pense.

**Un nom inconnu ne fait rien.** Le modèle rend du texte ; s'il invente `weight.update` là
où la table dit `weight.edit`, l'action est écartée. Elle n'échoue pas l'échange — la
réponse reste lisible — mais rien ne s'écrit.

**Deux niveaux, et le niveau n'est pas dans la main du modèle.** Il est écrit dans la
table, ici, et un modèle ne peut pas demander à ce qu'une suppression passe pour un ajout.

## Les deux niveaux

`AJOUT` s'exécute tout de suite et s'annule d'un appui : la ligne créée est rendue avec son
identifiant et son jeton, et l'écran n'a qu'à appeler la suppression du domaine. Aucune
machinerie d'annulation n'a été inventée — c'est le geste que l'utilisateur ferait.

`CHANGEMENT` n'écrit rien. L'action revient **en attente**, avec ce qu'elle changerait dit
en clair, et c'est un second appel qui l'exécute. Le projet n'a pas de corbeille : écraser
une mesure ou effacer une ligne se demande.

## Ce qui n'est pas ici

La provenance. `weight.csv`, `meals.csv`, `runs.csv`, `workouts.csv` et `plan.csv` portent
une colonne `source`, et tout ce que l'assistant y écrit est marqué `ia` (`IMP-05`).
`hydration/intake_log.csv` et `body/measurements.csv` n'en ont pas : un verre d'eau et un
tour de taille notés par l'assistant y sont donc indistinguables d'une saisie. Ajouter la
colonne est une décision de schéma, pas un détail d'implémentation — elle est notée, pas
prise.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ValidationError

from app.storage.files import FileStore

if TYPE_CHECKING:  # pragma: no cover - annotations seulement, jamais exécuté
    # Les annotations sont des chaînes (`from __future__ import annotations`) : les
    # importer ici donne des types à mypy sans rien charger à l'exécution, donc sans
    # rouvrir le cycle.
    from app.domains.activity.schemas import ExercisePayload, RunPayload, WorkoutPayload
    from app.domains.body.schemas import WeightPayload
    from app.domains.hydration.schemas import IntakePayload
    from app.domains.nutrition.schemas import MealPayload
    from app.domains.planning.schemas import PlanPayload

# **Aucun import de domaine en tête de module**, ni service ni schéma.
#
# C'est le piège que documente l'en-tête de `router.py`, et il se referme exactement comme
# annoncé : importer `planning.service` fait exécuter le paquet `planning`, donc son
# routeur, qui réimporte `planning.service` — un cycle que seul l'ordre de
# `app/domains/api.py` empêchait de se voir. Ce module est chargé plus tôt que le routeur,
# et l'ordre ne le sauve pas.
#
# Les schémas n'y échappent pas : `app.domains.planning.schemas` fait exécuter
# `planning/__init__.py`, qui importe le routeur. Le paquet entier part, pour deux
# modèles Pydantic.
#
# Le report est le même remède qu'au socle de stockage, où `_local_day` importe
# `app.core.dates` dans son corps pour la même raison. Python met les modules en cache :
# le coût est nul après le premier appel, et la table n'est construite qu'une fois.

#: La provenance écrite dans la colonne `source` des fichiers qui en ont une.
SOURCE = "ia"


class Level(StrEnum):
    """Ce qu'il en coûte de se tromper, et donc ce qu'on demande avant d'écrire."""

    #: Ajoute une ligne. S'exécute, et s'annule d'un appui.
    ADD = "add"
    #: Écrase ou efface. N'écrit rien sans confirmation.
    CHANGE = "change"


@dataclass(frozen=True)
class Undo:
    """De quoi défaire un ajout : c'est la suppression que l'utilisateur ferait lui-même.

    `domain` est **le chemin exact de la ressource**, sans le préfixe `/api/` ni la ligne :
    l'annulation est donc un `DELETE /api/{domain}/{row_id}` avec la garde `If-Match`, et
    l'écran n'a aucune table de correspondance à tenir. Un nom qui ne serait pas une route
    réelle se verrait au premier essai plutôt qu'à la lecture d'un `switch`.
    """

    domain: str
    row_id: int
    token: str


@dataclass(frozen=True)
class Outcome:
    """Ce qu'une action a fait, dit en français."""

    summary: str
    undo: Undo | None = None


Runner = Callable[[FileStore, Any], Awaitable[Outcome]]


def _field_doc(name: str, schema: dict[str, Any], required: bool) -> str:
    """Un argument, décrit depuis son schéma."""
    branches = schema.get("anyOf") or [schema]
    main = next((b for b in branches if b.get("type") != "null"), branches[0])
    nullable = any(b.get("type") == "null" for b in branches)

    enum = main.get("enum")
    if enum:
        kind = " | ".join(f'"{value}"' for value in enum)
    elif main.get("format") == "date":
        kind = '"AAAA-MM-JJ"'
    elif main.get("pattern") == "^([01]\\d|2[0-3]):[0-5]\\d$":
        kind = '"HH:MM"'
    elif main.get("type") in {"number", "integer"}:
        low, high = main.get("minimum", main.get("exclusiveMinimum")), main.get("maximum")
        span = f" {low}–{high}" if low is not None and high is not None else ""
        kind = f"nombre{span}"
    else:
        kind = "texte"

    if required:
        return f"{name} ({kind}, requis)"
    default = schema.get("default")
    if default not in (None, ""):
        return f'{name} ({kind}, défaut "{default}")'
    return f"{name} ({kind}{', ou null' if nullable else ''})"


#: Champs qu'un schéma de domaine porte mais que le modèle ne doit **ni voir ni fournir**.
#:
#: Deux trous, découverts en lisant le catalogue rendu :
#:
#: * `source` — `MealPayload` le porte, et l'exposer laissait le modèle écrire
#:   `"source": "manual"` sur un repas qu'il venait de créer. `IMP-05` défait par un
#:   argument. L'exécuteur force `ia`, et c'est à lui seul de le décider.
#: * `datetime` — l'horodatage vient du serveur, dans le fuseau local. Le laisser au
#:   modèle, c'est l'inviter à dater une prise d'hier avec l'heure d'aujourd'hui.
#:
#: Ils sont retirés de la description **et** des arguments reçus : cacher sans filtrer
#: n'aurait protégé que du modèle honnête.
HIDDEN_ARGS = frozenset({"source", "datetime"})


def _args_doc(payload: type[BaseModel]) -> str:
    """Les arguments d'une action, **rendus depuis le schéma** et jamais à la main.

    C'est un correctif, et il vaut d'être expliqué. La description était écrite à côté du
    schéma : `plan.add` annonçait `"kind": texte` alors que le champ n'accepte que
    `course`, `muscu` ou `autre`. Le modèle envoyait « abdos/pecs/bras », Pydantic
    refusait, et l'action échouait — cinq fois de suite, parce qu'une consigne fausse ne
    s'améliore pas en la répétant. La seule spécification que le modèle ait jamais est
    cette ligne : elle doit venir de la même source que la validation.
    """
    schema = payload.model_json_schema()
    required = set(schema.get("required", ()))
    return ", ".join(
        _field_doc(name, field, name in required)
        for name, field in schema.get("properties", {}).items()
        if name not in HIDDEN_ARGS
    )


@dataclass(frozen=True)
class ActionSpec:
    """Une action du catalogue."""

    name: str
    level: Level
    #: La phrase française de l'action — « supprimer une pesée ». Montrée au modèle **et**
    #: à l'utilisateur : deux libellés différents pour un même geste seraient une trace
    #: qu'on ne peut pas relire.
    label: str
    payload: type[BaseModel]
    run: Runner

    @property
    def describe(self) -> str:
        """La ligne montrée au modèle : le nom, l'effet, et les arguments du schéma."""
        return f"{self.name} — {self.label}. args : {{{_args_doc(self.payload)}}}"


# ── Les charges utiles propres à l'assistant ──────────
#
# Trois actions ne correspondent à aucun schéma de domaine : le geste existe à l'API sous
# forme de chemin (`/supplements/today/{id}`) et non de corps. On les déclare ici, au plus
# près de la table, plutôt que d'alourdir le domaine d'un schéma qu'il n'emploie pas.


class TakeSupplementArgs(BaseModel):
    schedule_id: str = Field(min_length=1, max_length=64)


class DeleteByRowArgs(BaseModel):
    """Désigne une ligne par sa position et son jeton, tels que le condensé les a donnés.

    Le jeton est **exigé**, exactement comme pour une suppression depuis un écran : c'est
    la garde anti-conflit (`STO-05`), et l'assistant n'y échappe pas. Une action fabriquée
    sur une ligne lue il y a dix minutes échoue au lieu d'effacer la mauvaise.
    """

    row_id: int = Field(ge=0)
    token: str = Field(min_length=1, max_length=128)


# ── Ce que chaque action fait ─────────────────────────


async def _add_weight(store: FileStore, payload: WeightPayload) -> Outcome:
    from app.domains.body.service import (
        WeightService,
    )

    entry = await WeightService(store).create(payload, source=SOURCE)
    return Outcome(
        summary=f"Pesée de {entry.weight_kg:g} kg notée le {entry.date:%d/%m/%Y}.",
        undo=Undo("body/weight", entry.id, entry.token),
    )


async def _add_water(store: FileStore, payload: IntakePayload) -> Outcome:
    from app.domains.hydration.service import (
        HydrationService,
    )

    entry = await HydrationService(store).create(payload)
    return Outcome(
        summary=f"{entry.volume_ml} ml ajoutés à l'hydratation du jour.",
        undo=Undo("hydration", entry.id, entry.token),
    )


async def _take_supplement(store: FileStore, payload: TakeSupplementArgs) -> Outcome:
    from app.domains.supplements.service import (
        SupplementService,
    )

    view = await SupplementService(store).take(payload.schedule_id)
    taken = next(
        (item.name for item in view.items if item.schedule_id == payload.schedule_id),
        payload.schedule_id,
    )
    # Pas d'annulation par jeton : décocher est un geste du domaine, et l'écran l'a déjà.
    return Outcome(summary=f"{taken} coché pour aujourd'hui.")


async def _add_meal(store: FileStore, payload: MealPayload) -> Outcome:
    from app.domains.nutrition.service import (
        NutritionService,
    )

    meal = await NutritionService(store).create(
        meal_type=payload.meal_type,
        comment=payload.comment,
        photo=None,
        protein_g=payload.protein_g,
        added_sugar_g=payload.added_sugar_g,
        calories=payload.calories,
        source=SOURCE,
    )
    return Outcome(
        summary=f"Repas « {meal.meal_type} » ajouté au journal du jour.",
        undo=Undo("nutrition", meal.id, meal.token),
    )


async def _add_run(store: FileStore, payload: RunPayload) -> Outcome:
    from app.domains.activity.service import (
        RunService,
    )

    run = await RunService(store).create(payload, source=SOURCE)
    return Outcome(
        summary=f"Course de {run.distance_km:g} km notée le {run.date:%d/%m/%Y}.",
        undo=Undo("activity/runs", run.id, run.token),
    )


async def _add_workout(store: FileStore, payload: WorkoutPayload) -> Outcome:
    from app.domains.activity.service import (
        WorkoutService,
    )

    workout = await WorkoutService(store).create(payload, source=SOURCE)
    return Outcome(
        summary=f"Séance « {workout.type} » notée le {workout.date:%d/%m/%Y}.",
        undo=Undo("activity/workouts", workout.id, workout.token),
    )


async def _create_exercise(store: FileStore, payload: ExercisePayload) -> Outcome:
    from app.domains.activity.service import (
        ExerciseService,
    )

    exercise = await ExerciseService(store).create(payload)
    return Outcome(
        summary=f"Exercice « {exercise.name} » ajouté au catalogue ({exercise.muscle_group}).",
        undo=Undo("activity/exercises", exercise.id, exercise.token),
    )


async def _add_plan(store: FileStore, payload: PlanPayload) -> Outcome:
    from app.domains.planning.service import (
        PlanningService,
    )

    session = await PlanningService(store).create(payload, source=SOURCE)
    return Outcome(
        summary=f"« {session.title} » prévu le {session.date:%d/%m/%Y} à {session.time}.",
        undo=Undo("planning/sessions", session.id, session.token),
    )


async def _delete_weight(store: FileStore, payload: DeleteByRowArgs) -> Outcome:
    from app.domains.body.service import (
        WeightService,
    )

    await WeightService(store).delete(payload.row_id, payload.token)
    return Outcome(summary="Pesée supprimée.")


async def _delete_meal(store: FileStore, payload: DeleteByRowArgs) -> Outcome:
    from app.domains.nutrition.service import (
        NutritionService,
    )

    await NutritionService(store).delete(payload.row_id, payload.token)
    return Outcome(summary="Repas supprimé.")


async def _delete_plan(store: FileStore, payload: DeleteByRowArgs) -> Outcome:
    from app.domains.planning.service import (
        PlanningService,
    )

    await PlanningService(store).remove(payload.row_id, payload.token)
    return Outcome(summary="Séance prévue retirée du planning.")


async def _delete_run(store: FileStore, payload: DeleteByRowArgs) -> Outcome:
    from app.domains.activity.service import (
        RunService,
    )

    await RunService(store).delete(payload.row_id, payload.token)
    return Outcome(summary="Course supprimée.")


async def _delete_workout(store: FileStore, payload: DeleteByRowArgs) -> Outcome:
    from app.domains.activity.service import (
        WorkoutService,
    )

    await WorkoutService(store).delete(payload.row_id, payload.token)
    return Outcome(summary="Séance supprimée.")


# ── La table ──────────────────────────────────────────


def _spec(name: str, level: Level, label: str, payload: type[BaseModel], run: Any) -> ActionSpec:
    return ActionSpec(name=name, level=level, label=label, payload=payload, run=run)


@cache
def catalogue() -> dict[str, ActionSpec]:
    """La table, construite au premier usage.

    Différée pour la raison dite en tête : la construire au chargement du module ferait
    partir les paquets de domaine dans le mauvais ordre. `@cache` la rend équivalente à
    une constante après le premier appel.
    """
    from app.domains.activity.schemas import ExercisePayload, RunPayload, WorkoutPayload
    from app.domains.body.schemas import WeightPayload
    from app.domains.hydration.schemas import IntakePayload
    from app.domains.nutrition.schemas import MealPayload
    from app.domains.planning.schemas import PlanPayload

    specs = (
        # ── Ce qui s'exécute et s'annule ──
        _spec(
            "weight.add",
            Level.ADD,
            "noter une pesée",
            WeightPayload,
            _add_weight,
        ),
        _spec(
            "water.add",
            Level.ADD,
            "noter une boisson",
            IntakePayload,
            _add_water,
        ),
        _spec(
            "supplement.take",
            Level.ADD,
            "cocher un supplément du jour (schedule_id vu dans le condensé)",
            TakeSupplementArgs,
            _take_supplement,
        ),
        _spec(
            "meal.add",
            Level.ADD,
            "noter un repas du jour",
            MealPayload,
            _add_meal,
        ),
        _spec(
            "run.add",
            Level.ADD,
            "noter une course",
            RunPayload,
            _add_run,
        ),
        _spec(
            "workout.add",
            Level.ADD,
            "noter une séance",
            WorkoutPayload,
            _add_workout,
        ),
        _spec(
            "exercise.create",
            Level.ADD,
            "ajouter un exercice au catalogue",
            ExercisePayload,
            _create_exercise,
        ),
        _spec(
            "plan.add",
            Level.ADD,
            "prévoir une séance",
            PlanPayload,
            _add_plan,
        ),
        # ── Ce qui demande un appui ──
        _spec(
            "weight.delete",
            Level.CHANGE,
            "supprimer une pesée",
            DeleteByRowArgs,
            _delete_weight,
        ),
        _spec(
            "meal.delete",
            Level.CHANGE,
            "supprimer un repas",
            DeleteByRowArgs,
            _delete_meal,
        ),
        _spec(
            "run.delete",
            Level.CHANGE,
            "supprimer une course",
            DeleteByRowArgs,
            _delete_run,
        ),
        _spec(
            "workout.delete",
            Level.CHANGE,
            "supprimer une séance",
            DeleteByRowArgs,
            _delete_workout,
        ),
        _spec(
            "plan.delete",
            Level.CHANGE,
            "retirer une séance prévue",
            DeleteByRowArgs,
            _delete_plan,
        ),
    )
    return {spec.name: spec for spec in specs}


def describe_catalogue() -> list[str]:
    """Les lignes montrées au modèle, dans l'ordre de la table.

    Rendues ici et insérées telles quelles par `conversation.py`, qui ne connaît donc aucun
    nom d'action : un nom qui change ne se retrouve jamais à deux endroits.
    """
    return [spec.describe for spec in catalogue().values()]


def validate(name: str, args: dict[str, Any]) -> tuple[ActionSpec, BaseModel] | str:
    """Rend `(spec, charge utile)` si l'action est recevable, sinon la raison en français.

    La raison est destinée à être **lue par l'utilisateur**, pas seulement journalisée : si
    l'assistant a compris « ajoute ma séance » sans savoir combien de temps elle a duré, le
    dire vaut mieux que de laisser croire que c'est fait.
    """
    spec = catalogue().get(name)
    if spec is None:
        return f"« {name} » n'est pas quelque chose que je sais faire."

    try:
        payload = spec.payload.model_validate(
            {key: value for key, value in args.items() if key not in HIDDEN_ARGS}
        )
    except ValidationError as error:
        return _refusal(error)

    return spec, payload


def _refusal(error: ValidationError) -> str:
    """Dit **pourquoi** en français, et sans confondre deux causes.

    « Il me manque de quoi le faire : kind » s'affichait alors que `kind` était fourni —
    avec une valeur hors de la liste. Un message qui désigne la mauvaise cause envoie
    corriger la mauvaise chose, et c'est celui-là que l'utilisateur lit cinq fois de suite.
    """
    problems = error.errors()

    missing = sorted({str(item["loc"][0]) for item in problems if item["type"] == "missing"})
    if missing:
        return f"Il me manque de quoi le faire : {', '.join(missing)}."

    if not problems:  # pragma: no cover - Pydantic ne lève jamais sans détail
        return "Cette action n'est pas recevable."
    first = problems[0]
    location = first["loc"]
    field = str(location[0]) if location else "un argument"
    expected = (first.get("ctx") or {}).get("expected")
    if expected:
        # Pydantic énumère en anglais — « 'a', 'b' or 'c' ». Le message est lu par
        # l'utilisateur, et la moitié du projet existe pour qu'il soit en français.
        return f"« {field} » n'accepte que {str(expected).replace(' or ', ' ou ')}."
    return f"La valeur donnée pour « {field} » n'est pas acceptable."


__all__ = [
    "HIDDEN_ARGS",
    "SOURCE",
    "ActionSpec",
    "DeleteByRowArgs",
    "Level",
    "Outcome",
    "TakeSupplementArgs",
    "Undo",
    "catalogue",
    "describe_catalogue",
    "validate",
]
