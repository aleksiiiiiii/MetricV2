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
from datetime import date, timedelta
from typing import TYPE_CHECKING, NamedTuple

from app.core.dates import today_local, week_start
from app.domains.aggregates.service import DashboardService
from app.domains.assistant.conversation import Need
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

#: Lignes qu'une seule tranche réclamée peut rendre, périodes déroulées comprises.
#:
#: Sept jours de repas détaillés dépassent à eux seuls tout le reste du condensé, et
#: `IA-09` existe pour empêcher exactement cela — « rassembler en une trentaine de lignes,
#: et rien de plus ». La borne ne refuse pas la demande, elle la coupe **en le disant**.
MAX_PERIOD_LINES = 40

_WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


class MemoryNote(NamedTuple):
    """Une note du carnet, telle que la consigne a besoin de la lire.

    Un tuple nommé plutôt qu'un `(sujet, note)` élargi : ce module recevait déjà une paire,
    et lui en passer une de quatre éléments rendrait chaque appel illisible au premier coup
    d'œil. C'est aussi ce qui a permis d'ajouter la date sans toucher aux appelants qui
    n'en veulent pas — `read_reply` ne lit toujours que les notes.
    """

    topic: str
    note: str
    created: date | None = None
    resolved: date | None = None


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

    # **Demain est nommé, pas laissé à dériver.** La date seule obligeait le modèle à
    # calculer le lendemain — et « je charge combien demain ? » est une des questions les
    # plus fréquentes. C'est la même règle que partout : ce qui se dérive se sert.
    tomorrow = current + timedelta(days=1)
    lines: list[str] = [
        f"Nous sommes le {_WEEKDAYS[current.weekday()]} {current:%d/%m/%Y} — "
        f"demain sera le {_WEEKDAYS[tomorrow.weekday()]} {tomorrow:%d/%m/%Y}"
    ]

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

    lines.extend(await today_lines(store, current))

    return lines


async def today_lines(store: FileStore, today: date) -> list[str]:
    """Les chiffres du jour — eau, nutrition, séance, suppléments, pesée (lot 12.A).

    ## Pourquoi ils sont ici et non dans une tranche

    Ils l'étaient. « J'ai assez bu ? » réclamait `hydratation_du_jour`, donc une seconde
    passe, donc **un appel modèle entier** — sur ce qui est la question la plus banale de
    l'application. Les servir d'office coûte une centaine de jetons et économise un appel
    complet sur les questions les plus fréquentes : c'est un gain de latence autant que de
    couverture, et c'est ce qui distingue ce lot des autres élargissements du condensé.

    ## Ce que ces lignes ne remplacent pas

    **Les tranches du jour restent**, et la raison est structurelle : ici on sert les
    **chiffres**, là-bas les **identifiants et les jetons**. Supprimer le repas de midi
    continue d'exiger `repas_du_jour` — c'est `STO-05`, et rien ne l'assouplit. Deux
    rubriques, deux usages, et le modèle n'obtient pas ici de quoi écrire.

    ## Aucun zéro pour une absence

    Un jour sans repas rend « aucun repas noté » et non « 0 g de protéines ». Le plan le
    signalait au lot 2 : un zéro qui passerait pour une mesure est exactement ce que
    l'invariant interdit, et il s'applique au prompt autant qu'à l'écran — avec moins de
    chances d'être vu, puisque personne ne relit une consigne.

    Rien n'est calculé ici : chaque chiffre vient du service qui détient sa règle, comme
    partout dans ce module.
    """
    from app.domains.body.service import WeightService
    from app.domains.hydration.service import HydrationService
    from app.domains.nutrition.service import NutritionService
    from app.domains.supplements.service import SupplementService

    lines: list[str] = []

    stats = (await HydrationService(store).view(today)).stats
    if stats.today_ml:
        lines.append(
            f"Aujourd'hui — hydratation : {stats.today_ml} ml sur une cible de "
            f"{stats.target_ml} ml, il reste {stats.remaining_ml} ml à boire"
        )
    else:
        lines.append(f"Aujourd'hui — hydratation : rien de noté, cible {stats.target_ml} ml")

    totals = await NutritionService(store).totals(today)
    if totals.meals:
        lines.append(
            f"Aujourd'hui — nutrition : {fr(totals.protein_g)} g de protéines sur "
            f"{fr(totals.protein_target_g)} g visés (il reste "
            f"{fr(totals.protein_remaining_g)} g), {totals.calories} kcal, sucres ajoutés "
            f"{fr(totals.added_sugar_g)} g sur un plafond de {fr(totals.added_sugar_max_g)} g, "
            f"{totals.meals} repas noté(s)"
        )
    else:
        lines.append(
            f"Aujourd'hui — nutrition : aucun repas noté, cibles {fr(totals.protein_target_g)} g "
            f"de protéines et {fr(totals.added_sugar_max_g)} g de sucres ajoutés au plus"
        )

    checklist = await SupplementService(store).checklist(today)
    if checklist.items:
        taken = [item.name for item in checklist.items if item.taken]
        left = [item.name for item in checklist.items if not item.taken]
        lines.append(
            f"Aujourd'hui — suppléments : {', '.join(taken) or 'aucun'} pris, "
            f"{', '.join(left) or 'aucun'} restant(s)"
        )

    lines.extend(await _training_today(store, today))

    weighed = await WeightService(store).view(limit=1, offset=0)
    first = weighed.entries[0] if weighed.entries else None
    if first is not None and first.date == today:
        lines.append(f"Aujourd'hui — pesée : {first.weight_kg:g} kg")

    return lines


async def _training_today(store: FileStore, today: date) -> list[str]:
    """Ce qui a été fait aujourd'hui — séances, courses, et les charges soulevées.

    Séparé pour une raison pratique : c'est la seule partie du bloc qui lit trois fichiers,
    et la seule qui rende plusieurs lignes. Une séance du jour porte ses exercices, parce
    que c'est la question suivante — « j'ai fait combien au développé ? » ne doit pas
    coûter une seconde passe le jour même.
    """
    from app.domains.activity.service import ExerciseService, RunService, WorkoutService

    lines: list[str] = []

    for row in await WorkoutService(store).all():
        seance = row.model
        if seance.date != today:
            continue
        details = [f"{fr(seance.duration_min)} min"]
        if seance.rpe is not None:
            details.append(f"effort perçu {seance.rpe}/10")
        lines.append(f"Aujourd'hui — séance : {seance.type}, {', '.join(details)}")

    # Les séries du jour, rendues **exactement** comme `detail_seances` les rend : deux
    # formulations pour la même chose finiraient par diverger, et un coach lirait deux
    # charges différentes selon la rubrique qu'il regarde. `_charge` porte `ACT-07` — « 0 »
    # est le poids du corps, jamais une absence.
    entries = [
        ExerciseService.entry_to_schema(row) for row in await ExerciseService(store).log_entries()
    ]
    du_jour = [entry for entry in entries if entry.date == today]
    if du_jour:
        rendu = " · ".join(
            f"{entry.exercise_name} {entry.sets}×{entry.reps} à {_charge(entry.weight_kg)}"
            for entry in sorted(du_jour, key=lambda e: e.id)
        )
        lines.append(f"Aujourd'hui — exercices : {rendu}")

    for sortie in await RunService(store).all():
        run = RunService.to_schema(sortie)
        if run.date != today:
            continue
        details = [f"{fr(run.distance_km)} km", f"{fr(run.duration_min)} min"]
        if run.pace_min_km is not None:
            details.append(f"allure {fr(run.pace_min_km)} min/km")
        lines.append(f"Aujourd'hui — course : {', '.join(details)}")

    return lines


def memory_lines(entries: list[MemoryNote]) -> list[str]:
    """Le carnet, mis en phrases. « sujet — note (noté le 12/03/2026) ».

    Séparé du condensé de données, et pas seulement pour la mise en page : ce sont deux
    natures d'information. Le condensé est **mesuré** et recalculé à chaque question ; le
    carnet est **dit** et ne change que lorsqu'on le corrige. Les mélanger inviterait le
    modèle à traiter une phrase de mars comme un chiffre d'aujourd'hui.

    ## La date, et pourquoi elle vaut une ligne de code

    Elle était **perdue** : la colonne existait dans le fichier et n'arrivait pas au modèle.
    Une contrainte notée en mars pesait donc autant qu'une note d'hier, alors que c'est
    exactement l'inverse qui est vrai — plus une note est vieille, plus elle a pu cesser
    d'être vraie sans que personne ne l'ait corrigée. Un carnet sans dates est un carnet
    dont on ne peut rien périmer.

    **Une note sans date reste servie, sans parenthèse.** Inventer « noté le » sur une ligne
    qui n'en porte pas serait une valeur inventée dans la consigne — la même faute qu'un
    zéro affiché pour une mesure absente, et elle s'attrape moins bien parce que personne ne
    regarde un prompt.

    ## Ce qui est résolu le reste

    Une note résolue part avec sa date de résolution. Elle n'est ni retirée ni reléguée :
    « genou droit sensible, résolu le 12/05 » dit à un coach ce qui a déjà lâché — donc quoi
    surveiller — sans lui faire ménager une articulation qui va bien depuis un an. La
    retirer perdrait le premier ; l'envoyer sans statut causerait le second.
    """
    lines: list[str] = []
    for note in entries[:MAX_MEMORY_LINES]:
        suffix = ""
        if note.resolved is not None:
            suffix = f" (noté le {note.created:%d/%m/%Y}, résolu le {note.resolved:%d/%m/%Y})"
            if note.created is None:
                suffix = f" (résolu le {note.resolved:%d/%m/%Y})"
        elif note.created is not None:
            suffix = f" (noté le {note.created:%d/%m/%Y})"
        lines.append(f"{note.topic} — {note.note}{suffix}")
    return lines


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


#: Exercices rendus par `progression_charges`. Au-delà, la tranche pèse plus que ce qu'elle
#: apprend — un catalogue de trente exercices noierait les trois qui progressent.
MAX_PROGRESS = 12

#: Séances détaillées par `detail_seances`, et charges rappelées par exercice. Cinq séances
#: couvrent un mois d'entraînement à deux par semaine : de quoi voir une tendance sans
#: renvoyer le fichier.
MAX_SESSIONS = 5
MAX_SERIES = 6


def _charge(kg: float) -> str:
    """Une charge, en français. **`0` n'est pas une absence : c'est le poids du corps.**

    `ACT-07` le pose au niveau du fichier — « `weight_kg = 0` signifie poids du corps,
    c'est une valeur légitime, pas une absence de donnée ». Rendre « 0 kg » inviterait le
    modèle à lire une charge nulle là où il y a eu des tractions.
    """
    return "poids du corps" if kg == 0 else f"{fr(kg)} kg"


async def _exercises(store: FileStore, _today: date) -> list[str]:
    from app.domains.activity.service import ExerciseService

    catalogue = await ExerciseService(store).catalogue()
    if not catalogue:
        return ["Catalogue d'exercices : vide"]
    return [
        f"Exercice « {item.name} » (exercise_id={item.exercise_id}, {item.muscle_group})"
        for item in catalogue
    ]


async def _lift_progress(store: FileStore, _today: date) -> list[str]:
    """Charges, écarts et records par exercice — **le trou que ce lot comble**.

    Sans cette tranche, l'assistant voyait « Séance du 12/08 : muscu » et rien d'autre : il
    pouvait constater qu'on s'était entraîné, jamais dire quoi charger la fois suivante.

    **Rien n'est calculé ici.** `ActivityStats.progress()` détient la règle — la charge du
    jour est la plus lourde de la séance et non la dernière consignée, le 1RM vient de
    `estimate_one_rep_max`. Recalculer un écart à cet endroit serait le plus sûr moyen que
    l'assistant annonce un chiffre que `/activite` contredit.
    """
    from app.domains.activity.stats import ActivityStats

    rows = await ActivityStats(store).progress()
    if not rows:
        return ["Progression des charges : aucun exercice relevé"]

    lines: list[str] = []
    for item in rows[:MAX_PROGRESS]:
        details: list[str] = []
        if item.last_weight_kg is not None and item.last_date is not None:
            details.append(f"{_charge(item.last_weight_kg)} le {item.last_date:%d/%m/%Y}")
        if item.delta_kg is not None:
            # Le signe porte l'information : « +2,5 » et « -2,5 » ne se coachent pas pareil.
            details.append(f"{item.delta_kg:+g} kg depuis la fois d'avant")
        if item.best_weight_kg is not None:
            details.append(f"record {_charge(item.best_weight_kg)}")
        if item.best_one_rep_max_kg is not None:
            details.append(f"1RM estimé {fr(item.best_one_rep_max_kg)} kg")
        if item.max_series:
            serie = ", ".join(_charge(kg) for kg in item.max_series[-MAX_SERIES:])
            details.append(f"charges par séance : {serie}")
        lines.append(
            f"« {item.name} » ({item.muscle_group}, exercise_id={item.exercise_id}) : "
            + " — ".join(details or ["jamais chargé"])
        )
    return lines


async def _session_detail(store: FileStore, _today: date) -> list[str]:
    """Les séries des dernières séances : exercice, charge, séries, répétitions, volume.

    Complémentaire de `progression_charges`, qui agrège par exercice : ici on voit ce
    qu'une séance a réellement contenu, donc ce qui a été négligé.
    """
    from app.domains.activity.service import ExerciseService

    rows = await ExerciseService(store).log_entries()
    if not rows:
        return ["Détail des séances : aucune série relevée"]

    entries = [ExerciseService.entry_to_schema(row) for row in rows]
    par_seance: dict[tuple[date, str], list[str]] = {}
    for entry in sorted(entries, key=lambda e: (e.date, e.id)):
        rendu = f"{entry.exercise_name} {entry.sets}×{entry.reps} à {_charge(entry.weight_kg)}"
        # Au poids du corps, `volume_kg` vaut zéro — le domaine le calcule ainsi et il a
        # raison, un tonnage sans charge n'existe pas. Mais écrire « volume 0 kg » dirait à
        # un coach que la séance n'a rien produit, alors qu'elle a produit 32 répétitions.
        # Ce qui se compte alors, ce sont les répétitions.
        if entry.weight_kg:
            rendu += f" (volume {fr(entry.volume_kg)} kg)"
        else:
            rendu += f" ({entry.sets * entry.reps} répétitions)"
        par_seance.setdefault((entry.date, entry.workout_id), []).append(rendu)

    dernieres = sorted(par_seance)[-MAX_SESSIONS:]
    return [
        f"Séance du {jour:%d/%m/%Y} : " + " · ".join(par_seance[(jour, workout_id)])
        for jour, workout_id in dernieres
    ]


async def _meals_today(store: FileStore, today: date) -> list[str]:
    """Les repas du jour **et leurs totaux**.

    Les identifiants seuls permettaient de supprimer un repas et rien d'autre : « il me
    reste combien de protéines ? » restait sans réponse alors que `NutritionService.totals`
    la calcule déjà pour l'écran. C'est la moitié lecture de `meal.add`, qui était au
    catalogue sans elle.
    """
    from app.domains.nutrition.service import NutritionService

    service = NutritionService(store)
    view = await service.view(today)
    totals = await service.totals(today)

    # Le restant est **servi**, pas laissé à soustraire. Mesuré au jeu d'évaluation : sans
    # lui, tout modèle répond « 62 g » à « il me reste combien ? » — un écart qu'aucun
    # service n'a calculé, donc invérifiable. Le servir range la question du bon côté de
    # l'invariant sans priver l'utilisateur de sa réponse.
    lines = [
        f"Nutrition du {today:%d/%m/%Y} : {fr(totals.protein_g)} g de protéines sur "
        f"{fr(totals.protein_target_g)} g visés, il reste "
        f"{fr(totals.protein_remaining_g)} g à prendre, {totals.calories} kcal "
        f"({totals.calories_known} repas sur {totals.meals} avec les calories renseignées), "
        f"sucres ajoutés {fr(totals.added_sugar_g)} g sur un plafond de "
        f"{fr(totals.added_sugar_max_g)} g"
    ]
    if not view.meals:
        return [*lines, f"Repas du {today:%d/%m/%Y} : aucun"]
    lines += [
        f"Repas {meal.meal_type} le {meal.datetime:%d/%m à %H:%M} "
        f"(row_id={meal.id}, token={meal.token})"
        for meal in view.meals
    ]
    return lines


async def _hydration_today(store: FileStore, today: date) -> list[str]:
    """Ce qui a été bu aujourd'hui.

    `water.add` était au catalogue sans tranche de lecture : l'assistant savait écrire dans
    une donnée qu'il ne pouvait pas lire, et « j'ai assez bu ? » n'avait pas de réponse
    possible. La règle que ce lot pose — **toute action d'écriture a sa tranche de
    lecture** — se vérifie en comparant les deux tables.
    """
    from app.domains.hydration.service import HydrationService

    view = await HydrationService(store).view(today)
    stats = view.stats
    lines = [
        f"Hydratation du {today:%d/%m/%Y} : {stats.today_ml} ml sur une cible de {stats.target_ml} ml"
        f" ({fr(stats.ratio * 100)} %), il reste {stats.remaining_ml} ml à boire"
    ]
    if stats.average_7d_ml is not None:
        lines.append(f"Moyenne d'hydratation sur 7 jours : {stats.average_7d_ml} ml")
    if not view.today:
        lines.append(f"Prises du {today:%d/%m/%Y} : aucune")
        return lines
    lines += [
        f"Prise de {intake.volume_ml} ml le {intake.datetime:%d/%m à %H:%M} "
        f"(row_id={intake.id}, token={intake.token})"
        for intake in view.today
    ]
    return lines


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
        return [f"Suppléments du {today:%d/%m/%Y} : aucun au programme"]
    return [
        f"Supplément « {item.name} » le {today:%d/%m} à {item.time} — "
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
    """Courses et séances récentes, **avec ce qui les distingue**.

    Ne rendait que la distance et le type. Or `RunPayload` porte l'allure, la fréquence
    cardiaque, le dénivelé et la cadence, et `WorkoutRow.rpe` est documenté comme « transmis
    à l'IA comme signal de charge et de fatigue » — ce qu'il n'était pas. Une course de 8 km
    à 4'30 avec 140 de moyenne et une course de 8 km à 6'00 avec 165 ne se coachent pas
    pareil, et l'assistant lisait la même ligne pour les deux.
    """
    from app.domains.activity.service import RunService, WorkoutService

    runs = [RunService.to_schema(row) for row in (await RunService(store).all())[-5:]]
    workouts = (await WorkoutService(store).all())[-5:]

    lines: list[str] = []
    for run in runs:
        details = [f"{fr(run.distance_km)} km", f"{fr(run.duration_min)} min"]
        # Chaque détail n'est ajouté que s'il a été relevé : une allure absente ne devient
        # pas « 0 », elle ne s'écrit pas.
        if run.pace_min_km is not None:
            details.append(f"allure {fr(run.pace_min_km)} min/km")
        if run.avg_hr is not None:
            details.append(f"FC moyenne {run.avg_hr}")
        if run.elevation_m is not None:
            details.append(f"dénivelé {run.elevation_m} m")
        if run.cadence_spm is not None:
            details.append(f"cadence {run.cadence_spm} ppm")
        lines.append(
            f"Course du {run.date:%d/%m/%Y} : {', '.join(details)} "
            f"(row_id={run.id}, token={run.token})"
        )

    for row in workouts:
        seance = row.model
        details = [f"{fr(seance.duration_min)} min"]
        if seance.rpe is not None:
            details.append(f"effort perçu {seance.rpe}/10")
        if seance.calories is not None:
            details.append(f"{seance.calories} kcal")
        lines.append(
            f"Séance du {seance.date:%d/%m/%Y} : {seance.type}, {', '.join(details)} "
            f"(row_id={row.index}, token={row.token})"
        )
    return lines or ["Activités récentes : aucune"]


#: Les tranches, par nom. **La liste des clés est ce que le modèle a le droit de demander.**
SLICES: dict[str, Callable[[FileStore, date], Awaitable[list[str]]]] = {
    "exercices": _exercises,
    "progression_charges": _lift_progress,
    "detail_seances": _session_detail,
    "repas_du_jour": _meals_today,
    "hydratation_du_jour": _hydration_today,
    "pesees_recentes": _weights_recent,
    "supplements_du_jour": _supplements_today,
    "planning_a_venir": _plan_ahead,
    "activites_recentes": _activity_recent,
}


async def slices(store: FileStore, wanted: list[Need], *, today: date | None = None) -> list[str]:
    """Rend les tranches demandées, dans l'ordre où elles ont été nommées.

    `wanted` est **déjà filtré** par `read_need` sur les clés de `SLICES` : cette fonction
    n'a donc aucun nom inconnu à refuser, et c'est voulu — le filtre vit à un seul endroit.

    ## Les périodes (lot 12.B)

    Sans date, la tranche porte sur aujourd'hui — le cas d'avant ce lot, et de loin le plus
    fréquent. Avec une date, elle porte sur ce jour-là ; avec une semaine, sur les **sept
    jours** de cette semaine, servis un par un.

    **Aucun agrégat hebdomadaire n'est fabriqué ici**, et ce n'est pas un raccourci : une
    moyenne calculée à cet endroit serait le plus sûr moyen que l'assistant annonce un
    chiffre que `/activite` contredit. C'est la règle en tête de ce module, et une semaine
    ne la suspend pas. Sept journées servies telles quelles disent la même chose, sans que
    personne ait à croire un calcul que nul service n'a fait.
    """
    current = today or today_local()
    lines: list[str] = []
    for need in wanted:
        loader = SLICES.get(need.name)
        if loader is None:  # pragma: no cover - `read_need` a déjà filtré
            continue

        rendu: list[str] = []
        vues: set[str] = set()
        for day in _days_of(need, current):
            for line in await loader(store, day):
                # **Une même phrase deux fois n'apprend rien**, et sur une semaine ça se
                # voit : les tranches ajoutent des faits qui ne dépendent pas du jour rendu
                # — « Moyenne d'hydratation sur 7 jours » arrivait sept fois à l'identique.
                # Le doublon se retire ici plutôt que dans chaque chargeur, parce qu'aucun
                # d'eux ne sait qu'il est déroulé sur une semaine.
                if line in vues:
                    continue
                vues.add(line)
                rendu.append(line)

        if len(rendu) > MAX_PERIOD_LINES:
            # Une semaine reste une demande explicite, mais elle ne doit pas pouvoir manger
            # la consigne : sept jours de repas détaillés dépassent tout le reste du
            # condensé réuni. La coupe est **annoncée** — un contexte tronqué en silence
            # ferait conclure le modèle sur une semaine dont il n'a vu que le début.
            rendu = [
                *rendu[:MAX_PERIOD_LINES],
                f"(…) {len(rendu) - MAX_PERIOD_LINES} ligne(s) de plus non montrées pour "
                f"« {need.label} » — demande un jour précis pour les voir.",
            ]
        lines.extend(rendu)
    return lines


def _days_of(need: Need, current: date) -> list[date]:
    """Les jours qu'une tranche réclamée couvre. Un seul, sauf pour une semaine."""
    if need.day is None:
        return [current]
    if not need.week:
        return [need.day]
    start = week_start(need.day)
    return [start + timedelta(days=offset) for offset in range(7)]


__all__ = [
    "MAX_MEMORY_LINES",
    "MAX_PERIOD_LINES",
    "MAX_PROGRESS",
    "MAX_SERIES",
    "MAX_SESSIONS",
    "RECENT_INSIGHTS",
    "SLICES",
    "build",
    "memory_lines",
    "slices",
]
