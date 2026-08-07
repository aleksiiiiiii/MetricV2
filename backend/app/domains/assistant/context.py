"""Le condensé envoyé à l'assistant (`IA-09`).

**Ce module est la promesse du lot.** « Récupérer toutes les infos » ne veut pas dire
envoyer les fichiers : cela veut dire rassembler, en une trentaine de lignes, tout ce qui
permet de répondre — et rien de plus. La règle vient de `GOAL-02` et elle vaut ici avec
plus de force, parce qu'une conversation invite à tout joindre « au cas où ».

Rien n'est calculé ici. Chaque ligne vient du service qui détient sa règle : les cinq
métriques et leurs fenêtres du domaine Objectifs, la série d'assiduité de `AGG-03`, le
respect du planning de `PLAN-06`. Recalculer une moyenne à cet endroit serait le plus sûr
moyen que l'assistant annonce un chiffre que l'écran d'à côté contredit.

Le condensé est **publié** avec la réponse (`ChatReply.context`) : c'est ce qui rend la
promesse vérifiable à l'écran plutôt que déclarative dans un commentaire.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import TYPE_CHECKING

from app.core.dates import today_local
from app.domains.aggregates.service import DashboardService
from app.domains.goals.progress import fr
from app.domains.goals.service import GoalService, WeeklyInsightService
from app.storage.files import FileStore

if TYPE_CHECKING:  # pragma: no cover - import de typage seulement
    # Même arrangement qu'au lot L14, et pour la même raison : importer quoi que ce soit
    # de `app.domains.planning` exécute le `__init__` du paquet, donc son routeur. Le taux
    # de respect arrive **construit par le routeur**, jamais recalculé (`PLAN-06`).
    from app.domains.planning.schemas import AdherenceView

#: Bilans hebdomadaires rappelés. Deux suffisent à situer une tendance ; au-delà, ils
#: prennent la place des chiffres qu'ils commentaient.
RECENT_INSIGHTS = 2

#: Notes de mémoire envoyées au maximum. Le carnet part **entier** dans chaque question :
#: c'est ce qui rend l'assistant utile au dixième tour, et ce qui impose une borne.
MAX_MEMORY_LINES = 40

_WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


async def build(
    store: FileStore, *, adherence: AdherenceView, today: date | None = None
) -> list[str]:
    """Rassemble le condensé. `adherence` est **fourni**, jamais recalculé.

    L'ordre des lignes n'est pas indifférent : la date d'abord — un modèle n'a pas de
    calendrier et « cette semaine » ne veut rien dire sans elle —, puis ce qu'on vise, puis
    ce qu'on fait, puis ce qu'on a dit de la semaine passée.
    """
    current = today or today_local()
    goals = GoalService(store)

    lines: list[str] = [f"Nous sommes le {_WEEKDAYS[current.weekday()]} {current:%d/%m/%Y}"]

    view = await goals.view(today=current)
    if view.active is not None:
        active = view.active
        progress = active.progress
        share = "" if progress.ratio is None else f", {fr(progress.ratio * 100)} % du chemin"
        lines.append(
            f"Objectif en cours : {active.goal.title} — {progress.summary}{share} "
            f"({progress.basis}), échéance dans {active.days_left} jour(s)"
        )
    else:
        lines.append("Objectif en cours : aucun")

    # Les cinq métriques, leurs fenêtres, l'amplitude du poids, les cibles réglées et les
    # suppléments suivis — le même condensé que celui d'une proposition d'objectif, à la
    # ligne près. Deux versions divergeraient au premier ajout.
    facts, _ = await goals.summary_lines(current)
    lines.extend(facts)

    streak = await DashboardService(store).streak(current)
    lines.append(
        f"Assiduité de suivi : {streak.current} jour(s) d'affilée, "
        f"record {streak.longest}, {streak.active_days} jour(s) relevés au total"
    )

    if adherence.planned:
        share = "" if adherence.rate is None else f" ({fr(adherence.rate * 100)} %)"
        lines.append(
            f"Respect du planning sur {len(adherence.weeks)} semaines : "
            f"{adherence.honoured} séance(s) honorée(s) sur {adherence.planned} prévue(s){share}"
        )
    else:
        lines.append("Respect du planning : rien n'était prévu sur la période")

    weekly = await WeeklyInsightService(store).view(today=current)
    for entry in weekly.entries[:RECENT_INSIGHTS]:
        lines.append(f"Bilan de la semaine du {entry.week:%d/%m} : {entry.summary}")

    if len(view.history) > 0:
        outcomes = ", ".join(
            f"« {item.title} » {item.outcome_label or 'sans résultat noté'}"
            for item in view.history[:3]
        )
        lines.append(f"Objectifs passés : {outcomes}")

    return lines


def memory_lines(entries: list[tuple[str, str]]) -> list[str]:
    """Le carnet, mis en phrases. `(sujet, note)` → « sujet — note ».

    Séparé du condensé de données, et pas seulement pour la mise en page : ce sont deux
    natures d'information. Le condensé est **mesuré** et recalculé à chaque question ; le
    carnet est **dit** et ne change que lorsqu'on le corrige. Les mélanger inviterait le
    modèle à traiter une phrase de mars comme un chiffre d'aujourd'hui.
    """
    return [f"{topic} — {note}" for topic, note in entries[:MAX_MEMORY_LINES]]


# ── Les tranches demandées à la volée (`IA-16`) ───────
#
# Le condensé de `build` répond aux questions ; il ne suffit pas à **agir**. Supprimer le
# repas de midi demande son identifiant, ajouter une série demande l'exercice au
# catalogue — et charger tout cela dans chaque question reviendrait à envoyer les fichiers,
# ce que `IA-09` interdit précisément.
#
# D'où ces tranches, nommées et demandées par le modèle quand il en a besoin. Deux
# propriétés les rendent sûres :
#
# **Le modèle choisit dans une liste, il ne nomme pas un fichier.** `read_need` filtre sur
# les clés de cette table ; un nom inventé ne devient jamais une lecture.
#
# **Elles portent les identifiants et les jetons.** C'est ce qui referme la boucle : une
# suppression exige un jeton (`STO-05`), et le seul endroit où le modèle peut l'obtenir est
# une tranche qu'on lui a servie. Il ne peut donc pas effacer une ligne qu'il n'a pas lue.


async def _exercises(store: FileStore, _today: date) -> list[str]:
    from app.domains.activity.service import ExerciseService

    catalogue = await ExerciseService(store).catalogue()
    if not catalogue:
        return ["Catalogue d'exercices : vide"]
    return [
        f"Exercice « {item.name} » (exercise_id={item.exercise_id}, {item.muscle_group})"
        for item in catalogue
    ]


async def _meals_today(store: FileStore, today: date) -> list[str]:
    from app.domains.nutrition.service import NutritionService

    view = await NutritionService(store).view(today)
    if not view.meals:
        return ["Repas du jour : aucun"]
    return [
        f"Repas {meal.meal_type} à {meal.datetime:%H:%M} (row_id={meal.id}, token={meal.token})"
        for meal in view.meals
    ]


async def _weights_recent(store: FileStore, _today: date) -> list[str]:
    from app.domains.body.service import WeightService

    view = await WeightService(store).view(limit=10, offset=0)
    if not view.entries:
        return ["Pesées récentes : aucune"]
    return [
        f"Pesée du {entry.date:%d/%m/%Y} : {entry.weight_kg:g} kg "
        f"(row_id={entry.id}, token={entry.token})"
        for entry in view.entries
    ]


async def _supplements_today(store: FileStore, today: date) -> list[str]:
    from app.domains.supplements.service import SupplementService

    view = await SupplementService(store).checklist(today)
    if not view.items:
        return ["Suppléments du jour : aucun au programme"]
    return [
        f"Supplément « {item.name} » à {item.time} — "
        f"{'déjà pris' if item.taken else 'pas encore pris'} "
        f"(schedule_id={item.schedule_id})"
        for item in view.items
    ]


async def _plan_ahead(store: FileStore, today: date) -> list[str]:
    from datetime import timedelta

    from app.domains.planning.service import PlanningService

    sessions = await PlanningService(store).between(today, today + timedelta(days=28))
    if not sessions:
        return ["Séances prévues : aucune dans les quatre semaines"]
    return [
        f"Prévu le {item.date:%d/%m/%Y} à {item.time} : {item.title} "
        f"(row_id={item.id}, token={item.token})"
        for item in sessions
    ]


async def _activity_recent(store: FileStore, _today: date) -> list[str]:
    from app.domains.activity.service import RunService, WorkoutService

    runs = [RunService.to_schema(row) for row in (await RunService(store).all())[-5:]]
    workouts = (await WorkoutService(store).all())[-5:]

    lines = [
        f"Course du {run.date:%d/%m/%Y} : {run.distance_km:g} km "
        f"(row_id={run.id}, token={run.token})"
        for run in runs
    ]
    lines += [
        f"Séance du {row.model.date:%d/%m/%Y} : {row.model.type} "
        f"(row_id={row.index}, token={row.token})"
        for row in workouts
    ]
    return lines or ["Activités récentes : aucune"]


#: Les tranches, par nom. **La liste des clés est ce que le modèle a le droit de demander.**
SLICES: dict[str, Callable[[FileStore, date], Awaitable[list[str]]]] = {
    "exercices": _exercises,
    "repas_du_jour": _meals_today,
    "pesees_recentes": _weights_recent,
    "supplements_du_jour": _supplements_today,
    "planning_a_venir": _plan_ahead,
    "activites_recentes": _activity_recent,
}


async def slices(store: FileStore, names: list[str], *, today: date | None = None) -> list[str]:
    """Rend les tranches demandées, dans l'ordre où elles ont été nommées.

    `names` est **déjà filtré** par `read_need` sur les clés de `SLICES` : cette fonction
    n'a donc aucun nom inconnu à refuser, et c'est voulu — le filtre vit à un seul endroit.
    """
    current = today or today_local()
    lines: list[str] = []
    for name in names:
        loader = SLICES.get(name)
        if loader is None:  # pragma: no cover - `read_need` a déjà filtré
            continue
        lines.extend(await loader(store, current))
    return lines


__all__ = ["MAX_MEMORY_LINES", "RECENT_INSIGHTS", "SLICES", "build", "memory_lines", "slices"]
