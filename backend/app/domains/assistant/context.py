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

from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple

from app.core.dates import now_local, today_local, week_start
from app.domains.aggregates.service import DashboardService
from app.domains.assistant import profile
from app.domains.assistant.conversation import Need
from app.domains.goals.progress import fr
from app.domains.goals.service import GoalService, WeeklyInsightService
from app.storage.files import FileStore

if TYPE_CHECKING:  # pragma: no cover - import de typage seulement
    # Même arrangement qu'au lot L14, et pour la même raison : importer quoi que ce soit
    # de `app.domains.planning` exécute le `__init__` du paquet, donc son routeur. Le taux
    # de respect arrive **construit par le routeur**, jamais recalculé (`PLAN-06`).
    from app.domains.activity.models import CircuitSessionSetRow
    from app.domains.planning.schemas import AdherenceView
    from app.storage.csv_repo import Row

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

#: Bilans hebdomadaires servis par la tranche. Le condensé en rappelle deux ; une question
#: sur un trimestre en demande davantage, et treize couvrent l'année sans la dépasser.
MAX_REVIEWS = 13

#: Fenêtre de la tranche d'assiduité détaillée. Un mois de dates tient en une ligne par
#: source ; trois mois en feraient un mur de chiffres que personne ne lit, modèle compris.
MAX_TRACKING_DAYS = 30

#: Jours d'activité servis d'office avant aujourd'hui. Sept couvrent « hier »,
#: « avant-hier » et « cette semaine » — l'écrasante majorité des références à une séance
#: passée. Au-delà, la question devient « ma progression », et une liste la sert moins bien
#: que `progression_charges` ou `tendances`.
WEEK_BACK = 7

#: Jours de planning servis d'office. Même fenêtre que le passé, et pour la même raison :
#: « ce soir », « demain », « cette semaine » sont les questions posées. La tranche
#: `planning_a_venir` garde les quatre semaines et les jetons.
WEEK_AHEAD = 7

#: Les sept sources de l'assiduité (`AGG-03`), en français. Leurs clés sont techniques et
#: anglaises ; la consigne, elle, est en français de bout en bout.
_SOURCES = {
    "weight": "des pesées",
    "measurements": "des mensurations",
    "runs": "des courses",
    "workouts": "des séances",
    "meals": "des repas",
    "hydration": "de l'hydratation",
    "supplements": "des suppléments",
}

#: Les tranches qui regardent **devant** et acceptent donc une date future.
#:
#: Toutes les autres rapportent ce qui a eu lieu : leur servir un jour à venir produirait
#: un relevé sur une journée qui n'existe pas encore. Une seule tranche fait exception, et
#: c'est celle dont c'est le métier — un entraînement prévu jeudi prochain est une donnée.
FORWARD_LOOKING = frozenset({"planning_a_venir", "exercices"})

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
    store: FileStore,
    *,
    adherence: AdherenceView,
    today: date | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Rassemble le condensé. `adherence` est **fourni**, jamais recalculé.

    L'ordre des lignes n'est pas indifférent : la date d'abord — un modèle n'a pas de
    calendrier et « cette semaine » ne veut rien dire sans elle —, puis ce qu'on vise, puis
    ce qu'on fait, puis ce qu'on a dit de la semaine passée.

    **L'heure est donnée avec la date**, et pas par confort d'affichage : la moitié des
    conseils en dépendent. « J'ai assez bu ? » n'appelle pas la même réponse à 9 h et à
    22 h — 750 ml est en avance le matin et très en retard le soir. « Je m'entraîne
    encore aujourd'hui ? » non plus. Sans heure, le modèle jugeait une journée entière
    comme si elle était finie.

    `now` suit la même règle que `today` : **injectable**, jamais lu en douce. Un condensé
    qui irait chercher l'horloge lui-même ne serait pas reproductible, et c'est exactement
    le défaut qui a fait échouer deux tests d'écran au déploiement du 19/08.
    """
    moment = now or now_local()
    current = today or moment.date()
    # Un appelant qui épingle le jour sans épingler l'instant — c'est le cas des tests —
    # obtiendrait sinon une phrase qui donne la date d'un jour et l'heure d'un autre. On
    # ramène l'heure sur le jour demandé : la ligne reste vraie d'elle-même.
    if today is not None and now is None:
        moment = datetime.combine(current, moment.timetz())
    goals = GoalService(store)

    # **Demain est nommé, pas laissé à dériver.** La date seule obligeait le modèle à
    # calculer le lendemain — et « je charge combien demain ? » est une des questions les
    # plus fréquentes. C'est la même règle que partout : ce qui se dérive se sert.
    tomorrow = current + timedelta(days=1)
    lines: list[str] = [
        f"Nous sommes le {_WEEKDAYS[current.weekday()]} {current:%d/%m/%Y}, "
        f"il est {moment:%Hh%M} — "
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
    lines.extend(await week_lines(store, current))
    lines.extend(await plan_lines(store, current))

    return lines


async def plan_lines(store: FileStore, today: date) -> list[str]:
    """Ce qui est **prévu** sur les sept jours qui viennent, servi d'office.

    ## Le même angle mort que la semaine écoulée, dans l'autre sens

    Le condensé porte le **taux** de respect du planning — « 3 séances honorées sur 9
    prévues, 33,3 % ». Un taux dit si l'on tient ses rendez-vous ; il ne dit jamais lequel
    est mardi. « Je fais quoi ce soir ? » et « qu'est-ce qui est prévu demain ? » retombaient
    donc exactement dans le piège qui a fait dire « cette course n'apparaît pas dans ton
    suivi » : une tranche à réclamer, et un modèle qui préfère conclure.

    ## Pas de jetons ici

    `planning_a_venir` reste, et couvre quatre semaines **avec les jetons**. C'est le même
    partage qu'ailleurs : le condensé sert les **faits**, la tranche sert de quoi **agir**.
    Retirer une séance prévue continue d'exiger la tranche — `STO-05` ne s'assouplit pas
    parce qu'une information est devenue plus facile à lire.
    """
    from app.domains.planning.service import PlanningService

    sessions = await PlanningService(store).between(today, today + timedelta(days=WEEK_AHEAD))
    if not sessions:
        return [f"Rien de prévu d'ici {WEEK_AHEAD} jours"]

    lines: list[str] = []
    for item in sessions:
        quand = "aujourd'hui" if item.date == today else f"le {item.date:%d/%m}"
        # L'heure est facultative dans `plan.csv` — une séance sans créneau est une
        # possibilité normale, et lui en inventer un la daterait faussement.
        heure = f" à {item.time}" if item.time else ""
        lines.append(f"Prévu {quand}{heure} : {item.title} ({fr(item.duration_min)} min)")
    return lines


async def week_lines(store: FileStore, today: date) -> list[str]:
    """Les séances et courses des sept derniers jours, **servies d'office**.

    ## Le défaut que ce bloc répare, et il était grave

    Sur « j'ai des courbatures de ma course d'hier », l'assistant a répondu « cette course
    n'apparaît pas encore dans ton suivi ». Elle y était. Il n'a pas seulement omis de
    réclamer `activites_recentes` — **il a affirmé une absence sans avoir regardé**, ce qui
    est pire qu'un tour perdu : c'est une phrase fausse sur les données de quelqu'un.
    Relancé deux fois — « regarde bien », « vérifie car tu l'as » — il n'a toujours pas
    demandé.

    La consigne peut inviter à demander, elle ne peut pas garantir qu'il le fasse. Servir
    la semaine d'office retire la question : ce qu'on ne peut pas obliger un modèle à
    chercher, on le lui donne.

    ## Pourquoi la semaine, et pas plus

    C'est la fenêtre dont on parle. « Hier », « avant-hier », « cette semaine » couvrent
    l'écrasante majorité des références à une séance passée ; au-delà, la question devient
    « ma progression », et `progression_charges` ou `tendances` la servent mieux qu'une
    liste. Le condensé de `build` cite déjà des **moyennes** hebdomadaires — elles disent
    la cadence, jamais ce qui a été fait mardi.

    Aujourd'hui est exclu : `today_lines` le porte déjà, avec ses exercices en prime.
    """
    from app.domains.activity.service import CircuitSessionService, RunService

    debut = today - timedelta(days=WEEK_BACK)
    lines: list[str] = []
    sets = await CircuitSessionService(store).sets()

    for row in await CircuitSessionService(store).all():
        seance = row.model
        if not debut <= seance.date < today:
            continue
        details = [f"{fr(seance.duration_min)} min"]
        if seance.rpe is not None:
            details.append(f"effort perçu {seance.rpe}/10")
        # **Ce qu'une séance a travaillé, pas seulement qu'elle a eu lieu.** « tabata,
        # 18 min » ne dit pas si les jambes ont été touchées cette semaine — or c'est
        # exactement ce qu'un coach doit savoir avant de proposer la suivante.
        groupes = _muscles(_groups_of(sets, seance.session_id))
        travail = f" — {groupes}" if groupes else ""
        lines.append(
            f"Séance du {seance.date:%d/%m} : {seance.name}, {', '.join(details)}{travail}"
        )

    for sortie in await RunService(store).all():
        run = RunService.to_schema(sortie)
        if not debut <= run.date < today:
            continue
        details = [f"{fr(run.distance_km)} km", f"{fr(run.duration_min)} min"]
        if run.pace_min_km is not None:
            details.append(f"allure {fr(run.pace_min_km)} min/km")
        if run.avg_hr is not None:
            details.append(f"FC moyenne {run.avg_hr}")
        lines.append(f"Course du {run.date:%d/%m} : {', '.join(details)}")

    if not lines:
        # L'absence se dit, mais **bornée à la fenêtre** : « rien depuis sept jours » est
        # vrai et utile, « tu ne t'entraînes pas » serait une conclusion qui n'est pas la
        # nôtre à tirer.
        return ["Les sept jours précédents : aucune séance ni course notée"]
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
    from app.domains.activity.service import CircuitSessionService, RunService

    lines: list[str] = []

    sets = await CircuitSessionService(store).sets()

    for row in await CircuitSessionService(store).all():
        seance = row.model
        if seance.date != today:
            continue
        details = [f"{fr(seance.duration_min)} min"]
        if seance.rpe is not None:
            details.append(f"effort perçu {seance.rpe}/10")
        groupes = _muscles(_groups_of(sets, seance.session_id))
        travail = f" — {groupes}" if groupes else ""
        lines.append(f"Aujourd'hui — séance : {seance.name}, {', '.join(details)}{travail}")

    # Les séries du jour : ce que la séance a réellement contenu, exercice par exercice.
    # **Aucune charge** — `circuit_session_sets.csv` n'en porte pas (**C4**), et aller
    # chercher la charge courante dans `circuit_loads.csv` l'annoncerait comme celle du
    # jour, ce qu'elle n'est pas : une charge se corrige, une séance passée non.
    du_jour = [row.model for row in sets if row.model.date == today]
    if du_jour:
        rendu = " · ".join(
            f"{item.exercise_name} {item.sets}×{_reps(item.reps)}" for item in du_jour
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


def _muscles(groups: Iterable[str]) -> str:
    """Les groupes musculaires d'une séance, dans l'ordre où ils ont été travaillés.

    **C'est une lecture, pas un calcul.** `muscle_group` est une colonne de
    `circuit_session_sets.csv`, recopiée du circuit à l'écriture. Les lister ne dérive
    donc rien, et « le serveur calcule » n'est pas mis en cause.

    L'ordre d'apparition plutôt que l'alphabétique : « pectoraux, triceps » dit qu'on a
    poussé avant de finir sur les bras, et un coach lit ça.

    Il reçoit les groupes **déjà filtrés** sur leur séance, et ne les cherche plus
    lui-même : les trois rubriques qui l'appellent lisent la même colonne d'un même
    fichier, et le rattachement — `session_id` — se lit mieux sur place qu'à travers un
    `getattr`.
    """
    vus: list[str] = []
    for groupe in groups:
        if groupe and groupe not in vus:
            vus.append(groupe)
    return ", ".join(vus)


def _groups_of(sets: Sequence[Row[CircuitSessionSetRow]], session_id: str) -> list[str]:
    """Les groupes d'une séance, dans l'ordre écrit du fichier.

    Sur un `session_id` vide — une ligne de session corrigée à la main — rien n'est rendu
    plutôt que toutes les séries orphelines du fichier : c'est la garde de `_items_of`
    chez les circuits, et pour la même raison.
    """
    if not session_id:
        return []
    return [row.model.muscle_group for row in sets if row.model.session_id == session_id]


def _reps(value: int) -> str:
    """Les répétitions d'une série, ou « au temps » pour la sentinelle.

    `-1` est une convention de stockage : la faire lire à un modèle lui ferait écrire
    « moins une répétition » un jour ou l'autre. C'est la règle de l'API — aucune
    sentinelle ne sort du fichier.
    """
    return "au temps" if value < 0 else str(value)


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


async def _cadence_circuits(store: FileStore, _today: date) -> list[str]:
    """Les séances Cadence enregistrées, **et les noms qui affichent une illustration**.

    Les deux dans la même tranche, et ce n'est pas un fourre-tout : elles répondent à la
    même question — « de quoi je dispose pour créer ou rejouer une séance ». Les séparer
    coûterait une passe de plus au modèle, alors que le plafond est de deux.

    ## Pourquoi il n'y a plus de liste de noms ici

    Elle en portait 35, les seuls qui affichaient alors une illustration. Cadence en
    embarque maintenant **1324**, avec un rapprochement qui tolère la casse, les pluriels,
    les graphies collées et traduit le français mot à mot : « Pompes » y trouve *push-up*,
    « Gainage » *power point plank*.

    Les injecter tous coûterait la fenêtre de contexte pour un gain nul, et en tenir une
    sélection reviendrait à la liste tenue à la main qui finit par mentir. Ce qui reste est
    la seule règle qui décide encore de quelque chose : **un nom précis**. En dessous de la
    moitié des mots reconnus, Cadence n'affiche aucune démonstration plutôt qu'une fausse —
    donc « fentes marchées » et non « jambes ». Un nom sans correspondance reste valide, la
    séance se déroule, simplement sans image.
    """
    from app.domains.activity.service import CircuitService

    view = await CircuitService(store).list()

    lines = ["Séances Cadence enregistrées : aucune"] if not view.circuits else []
    for circuit in view.circuits:
        detail = ", ".join(
            f"{item.name} {item.reps}×"
            if item.reps is not None
            else f"{item.name} {item.duration_s}s"
            for item in circuit.exercises
        )
        minutes = f"{circuit.estimated_duration_min:.0f} min"
        lines.append(
            f"Séance Cadence « {circuit.name} » (circuit_id={circuit.circuit_id}) — "
            f"{circuit.rounds} rounds, repos {circuit.round_rest_s}s, "
            f"{minutes if circuit.exact else '~' + minutes} : {detail}"
        )

    if not view.linkable:
        # Le dire au modèle plutôt que de le laisser promettre un lien qui n'existera pas.
        lines.append(
            "Adresse de Cadence non réglée : une séance créée maintenant ne sera pas ouvrable "
            "tant qu'elle n'est pas renseignée dans les réglages."
        )

    lines.append(
        "Noms d'exercices : en **anglais**, repris mot pour mot du catalogue Cadence — "
        "« push-up », « mountain climber », « jump rope ». C'est cette orthographe qui "
        "affiche la démonstration, et « exercices_cadence:<mot-clé> » la donne. Le nom de "
        "la séance et tout ce que tu me dis restent en français. Un nom hors catalogue "
        "reste utilisable : la séance tourne, simplement sans démonstration."
    )
    return lines


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


async def _tabata_progress(store: FileStore, today: date) -> list[str]:
    """Par exercice de tabata : la charge, depuis quand, et combien de séances tenues.

    ## Ce que cette tranche est, et ce qu'elle n'est pas

    Elle remplacera `progression_charges`, qui vit sur `exercise_log.csv` et disparaîtra
    avec lui. Elle ne le recopie pas : il n'y a **ni 1RM estimé, ni record, ni écart avec
    la fois d'avant** (`docs/refonte-activite.md` §5 bis). Un tabata au poids du corps ou
    à répétitions n'a pas de charge maximale lisible, et l'estimer depuis quinze
    répétitions à 10 kg serait une valeur inventée que le modèle prendrait au sérieux.

    Ce qu'elle porte à la place, ce sont les deux chiffres qui manquaient : **depuis quand
    la charge n'a pas bougé**, et **combien de séances elle a tenu**. C'est le constat, pas
    la conclusion — le modèle dit « trois séances tenues à 10 kg », l'utilisateur décide
    (**R10**).

    ## Les groupes négligés viennent avec

    Ils répondent à l'autre moitié de la question — quoi travailler, et pas seulement à
    quelle charge — et ils sont lus chez `ActivityStats`, où la règle `ACT-16` vit déjà.
    Deux implémentations de « jamais travaillé rend `None` » finiraient par répondre
    autrement.
    """
    from app.domains.activity.service import CircuitLoadService
    from app.domains.activity.stats import ActivityStats

    lines: list[str] = []

    for load in (await CircuitLoadService(store).list()).loads:
        if load.state == "unset":
            # Rien de déclaré : il n'y a aucune charge à commenter, et écrire « — » ferait
            # une ligne par exercice du catalogue sans rien apprendre.
            continue
        charge = "poids du corps" if load.state == "bodyweight" else f"{fr(load.weight_kg or 0)} kg"
        details: list[str] = []
        if load.days_since_change is not None:
            details.append(f"dernier changement il y a {load.days_since_change} jour(s)")
            # `sessions_since` accompagne toujours `days_since_change` : sans le premier il
            # n'y a pas de date depuis laquelle compter, et le chiffre seul ne voudrait
            # rien dire.
            details.append(f"{load.sessions_since} séance(s) tenue(s) depuis")
        suite = f" — {', '.join(details)}" if details else ""
        lines.append(f"{load.name} : {charge}{suite}")

    if not lines:
        lines.append("Charges de tabata : aucune déclarée")

    negliges = [
        f"{groupe.muscle_group} : jamais travaillé"
        if groupe.days_since is None
        else f"{groupe.muscle_group} : il y a {groupe.days_since} jour(s)"
        for groupe in (await ActivityStats(store).overview(today, limit=1)).neglected
    ]
    lines.append("Groupes par ancienneté de sollicitation — " + " · ".join(negliges))
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
    from app.domains.activity.service import CircuitSessionService, RunService

    runs = [RunService.to_schema(row) for row in (await RunService(store).all())[-5:]]
    sessions = (await CircuitSessionService(store).all())[-5:]

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

    # Les mêmes groupes que le condensé sert pour la semaine : deux rubriques qui
    # décriraient la même séance différemment feraient douter de la bonne.
    sets = await CircuitSessionService(store).sets()

    for row in sessions:
        seance = row.model
        details = [f"{fr(seance.duration_min)} min", f"{seance.rounds} rounds"]
        if seance.rpe is not None:
            details.append(f"effort perçu {seance.rpe}/10")
        groupes = _muscles(_groups_of(sets, seance.session_id))
        travail = f" — {groupes}" if groupes else ""
        # **Aucun `row_id` ni jeton pour une séance.** Les courses en portent parce que
        # `run.delete` existe ; rien ne supprime une séance tabata, et annoncer un jeton
        # pour un geste qui n'a pas d'action inviterait le modèle à l'inventer.
        lines.append(
            f"Séance du {seance.date:%d/%m/%Y} : {seance.name}, {', '.join(details)}{travail}"
        )
    return lines or ["Activités récentes : aucune"]


async def _trends(store: FileStore, today: date) -> list[str]:
    """Les cinq chiffres de `AGG-04` pour chaque métrique suivie, sur trois mois.

    **C'est la tranche qui débloque la comparaison** — « compare ma progression au développé
    couché avec mon sommeil » n'avait aucune donnée pour se poser. Elle rend les *stats* et
    non les points : quatre-vingt-dix nombres par métrique noieraient la consigne, et un
    modèle n'en tire pas une corrélation qu'on pourrait croire. Dernier, variation, moyenne,
    minimum, maximum situent une tendance, ce qui est la question réelle.

    `SeriesStats` rend `None` partout sur une plage vide, et c'est délibéré côté service :
    « un zéro s'afficherait comme une mesure alors qu'il n'y a rien eu à mesurer ». On dit
    donc l'absence plutôt que d'écrire des tirets qui ressembleraient à des chiffres.
    """
    from app.domains.aggregates.service import METRICS, SeriesService

    service = SeriesService(store)
    lines: list[str] = []
    # **Les métriques vides se regroupent en une ligne, elles ne s'énumèrent pas.** Sur un
    # suivi ordinaire, onze des treize métriques n'ont rien — six mensurations que presque
    # personne ne relève. Les annoncer une par une remplissait la tranche de « rien relevé »
    # et noyait les deux qui parlent : c'est le volume que `IA-09` interdit, obtenu par
    # accident plutôt que par excès de zèle.
    muettes: list[str] = []
    for key, metric in METRICS.items():
        if metric.parameterised:
            # `exercise_load` demande un exercice ; `progression_charges` le sert déjà,
            # exercice par exercice, et le refaire ici donnerait deux chiffres pour la
            # même chose.
            continue
        view = await service.series(key, today, range_key="3m")
        stats = view.stats
        if stats.count == 0 or stats.average is None:
            muettes.append(view.label)
            continue
        variation = "" if stats.change is None else f", variation {fr(stats.change)} {view.unit}"
        lines.append(
            f"Tendance {view.label} sur trois mois : dernier {fr(stats.latest or 0)} {view.unit} "
            f"({stats.latest_date:%d/%m/%Y}), moyenne {fr(stats.average)} {view.unit}, "
            f"de {fr(stats.minimum or 0)} à {fr(stats.maximum or 0)} {view.unit}, "
            f"{stats.count} relevé(s){variation}"
        )

    if muettes:
        # L'absence reste dite — un coach doit savoir ce qui n'est pas suivi avant de
        # conseiller dessus — mais en une ligne plutôt qu'en onze.
        lines.append(f"Rien relevé sur trois mois : {', '.join(muettes)}")
    return lines


async def _weekly_reviews(store: FileStore, today: date) -> list[str]:
    """Tous les bilans hebdomadaires, là où le condensé n'en rappelle que deux.

    Deux suffisent à situer une tendance et c'est pourquoi le condensé s'y tient ; une
    question sur un trimestre en demande davantage, et c'est exactement ce qu'une tranche
    à la demande existe pour servir.
    """
    view = await WeeklyInsightService(store).view(today=today)
    if not view.entries:
        return ["Bilans hebdomadaires : aucun enregistré"]
    return [
        f"Bilan de la semaine du {entry.week:%d/%m/%Y} : {entry.summary}"
        for entry in view.entries[:MAX_REVIEWS]
    ]


async def _tracking_days(store: FileStore, today: date) -> list[str]:
    """Quels jours ont été relevés, source par source, sur le dernier mois.

    Le condensé donne le **compteur** d'assiduité — « 12 jours d'affilée ». Il ne dit pas
    *quoi* a été relevé ni *quand* : un mois où seule l'hydratation est notée et un mois
    complet donnent la même série. La différence change tout ce qu'un coach en conclut.
    """
    from app.domains.aggregates.service import DashboardService

    depuis = today - timedelta(days=MAX_TRACKING_DAYS - 1)
    sources = await DashboardService(store).sources()

    lines: list[str] = []
    muettes: list[str] = []
    for cle, jours in sorted(sources.items()):
        # Les clés de `sources()` sont techniques et anglaises ; tout le reste de la
        # consigne est en français. Un modèle qui lit « workouts » au milieu de phrases
        # françaises le recopie tel quel dans sa réponse.
        nom = _SOURCES.get(cle, cle)
        recents = sorted(day for day in jours if depuis <= day <= today)
        if not recents:
            muettes.append(nom)
            continue
        lines.append(
            f"Suivi {nom} sur {MAX_TRACKING_DAYS} jours : {len(recents)} jour(s) — "
            + ", ".join(f"{day:%d/%m}" for day in recents)
        )

    if muettes:
        lines.append(f"Rien relevé sur {MAX_TRACKING_DAYS} jours : {', '.join(muettes)}")
    return lines


#: Les tranches, par nom. **La liste des clés est ce que le modèle a le droit de demander.**
class Slice(NamedTuple):
    """Une tranche : ce qu'elle charge, et **ce qu'elle promet au modèle**.

    Les deux vivent ensemble parce qu'ils divergeraient séparés. C'est la leçon du
    catalogue d'actions, qui est généré depuis les schémas Pydantic après cinq échecs
    d'affilée sur un `kind` décrit « texte » alors qu'il n'acceptait que trois valeurs :
    une description tenue à la main à côté du code qu'elle décrit finit par mentir.
    """

    load: Callable[[FileStore, date], Awaitable[list[str]]]
    #: Une ligne, à la première personne du serveur — « je te donne … ». Elle part telle
    #: quelle dans la consigne, c'est donc elle que le modèle lit pour choisir.
    describes: str
    #: La variante **cherchée** de la tranche, quand le modèle joint un mot-clé
    #: (`exercices_cadence:push up`). Sans mot-clé, c'est `load` qui répond — et pour une
    #: tranche cherchable, il répond en disant quoi demander.
    #:
    #: Elle a la signature de `load`, et ce n'était pas le cas : la recherche était
    #: synchrone et sans `FileStore`, « elle lit un catalogue figé du dépôt, pas les
    #: données de l'utilisateur ». **Ce n'est plus vrai** depuis le réglage matériel
    #: (**R8**) : la recherche ne sert que ce qui est faisable avec ce qu'on possède, et
    #: ça se lit dans le profil. La signature suit, plutôt qu'un accès au store passé en
    #: contrebande derrière une fonction qui se déclare pure.
    search: Callable[[FileStore, str], Awaitable[list[str]]] | None = None


#: Ce qu'on rend quand la tranche est demandée sans mot-clé. Dire quoi demander plutôt que
#: servir 1324 noms : c'est la même conduite que la coupe d'une semaine trop longue, qui
#: finit par « demande un jour précis pour les voir ».
_ASK_FOR_QUERY = (
    "Catalogue Cadence : 1324 exercices, trop pour être listés. Joins un mot-clé "
    "**en anglais** — `exercices_cadence:push up`, `exercices_cadence:mountain climber`. "
    "Le catalogue est anglais et je ne traduis pas : traduis avant de chercher, puis "
    "reprends le nom rendu tel quel. Ce que tu me dis, toi, reste en français."
)

#: Combien de noms une recherche rend au modèle. Vingt, et non les cinquante de l'écran :
#: une liste qu'on lit à l'œil se parcourt, une liste qui entre dans une consigne se paie
#: en jetons à chaque tour.
CADENCE_HITS = 20

#: La valeur du catalogue qui veut dire « sans matériel ». Toujours jointe au filtre : elle
#: porte 325 des 1324 exercices, et l'omettre viderait le tabata de sa moitié la plus utile.
BODYWEIGHT = "body weight"


async def _cadence_exercises(_store: FileStore, _today: date) -> list[str]:
    """La tranche sans mot-clé — elle dit quoi demander, elle ne liste rien.

    C'est la moitié qui répond quand `search` n'est pas sollicitée, et elle n'est pas un
    repli poli : servir un extrait arbitraire des 1324 laisserait croire au modèle qu'il a
    vu le catalogue.
    """
    return [_ASK_FOR_QUERY]


async def _owned_equipment(store: FileStore) -> list[str]:
    """Le matériel déclaré au profil (**R8**), ou rien du tout.

    Rien du tout **n'est pas « aucun matériel »** : c'est « on ne sait pas », et les deux
    ne se filtrent pas pareil. Un profil vide qui filtrerait sur l'ensemble vide ne
    laisserait que le poids du corps, sans que rien ne dise pourquoi — l'assistant
    deviendrait subitement plus pauvre pour n'avoir jamais été renseigné.
    """
    from app.domains.app_settings.service import SettingsService

    found, _inconnus = profile.equipment(
        (await SettingsService(store).all()).get(profile.EQUIPMENT, "")
    )
    return found


async def _search_cadence_exercises(store: FileStore, query: str) -> list[str]:
    """Les noms **exacts** du catalogue de Cadence qui correspondent au mot-clé.

    ## Pourquoi cette tranche existe

    Un nom sans correspondance reste valide — la séance se déroule, simplement sans
    démonstration. Un nom qui correspond **au mauvais exercice** met une mauvaise animation
    devant quelqu'un en plein effort, et c'est silencieux. Le modèle n'a aucun moyen de
    distinguer les deux tout seul : cette tranche est ce moyen.

    ## Pourquoi le résultat n'est pas rapproché du français

    `exercise_catalog.search` compare des noms anglais, ceux du catalogue. « pompes » n'y
    trouve rien, et c'est écrit dans `_ASK_FOR_QUERY` plutôt que corrigé ici : traduire
    mot à mot côté serveur serait une seconde implémentation du rapprochement de Cadence,
    celle que `docs/charges.md` §4 s'interdit. Le modèle traduit — c'est ce qu'il sait
    faire — et le serveur confirme l'orthographe.
    """
    from app.domains.activity import exercise_catalog

    # Le poids du corps est **toujours** faisable, quel que soit le profil : ne pas
    # l'ajouter d'office ferait disparaître la moitié du catalogue tabata — 325 exercices —
    # pour qui n'a coché que « dumbbell ».
    possede = await _owned_equipment(store)
    faisable = {*possede, BODYWEIGHT} if possede else None

    found = [
        item
        for item in exercise_catalog.search(query, limit=exercise_catalog.LIMIT)
        if faisable is None or item.equipment in faisable
    ][:CADENCE_HITS]

    if not found:
        # Deux absences, deux réponses. « Rien pour ce mot » se corrige en cherchant
        # autrement ; « rien avec ton matériel » se corrige en cochant une case de plus, et
        # confondre les deux enverrait le modèle chercher un synonyme qui n'existe pas.
        if faisable is not None and exercise_catalog.search(query, limit=1):
            return [
                f"Catalogue Cadence : des exercices existent pour « {query} », mais aucun "
                f"avec le matériel déclaré ({', '.join(possede)}). Propose autre chose, ou "
                "dis-lui d'ajouter son matériel dans Réglages, section « Ce que je suis »."
            ]
        return [
            f"Catalogue Cadence : aucun exercice pour « {query} ». Cherche en anglais et "
            "en un mot ou deux. Un nom hors catalogue reste utilisable : la séance tourne, "
            "sans démonstration."
        ]

    noms = ", ".join(f"{item.name} ({item.body_part} · {item.equipment})" for item in found)
    # Le filtre est **annoncé**. Un catalogue rétréci en silence ferait conclure au modèle
    # que Cadence ne connaît que ça, et il cesserait de chercher là où il aurait dû
    # demander une case de plus.
    portee = f" (limité à ton matériel : {', '.join(possede)})" if faisable is not None else ""
    return [
        f"Exercices Cadence pour « {query} »{portee} — reprends le nom **exactement** : {noms}",
    ]


#: Les tranches, par nom. **La liste des clés est ce que le modèle a le droit de demander,
#: et les descriptions sont ce qui lui permet de choisir.**
#:
#: Elles étaient listées en noms nus. Les actions, elles, portent leurs arguments depuis
#: longtemps — l'asymétrie n'avait aucune raison d'être, et personne ne devine ce que
#: `jours_suivis` contient. Une possibilité non décrite est une possibilité morte.
SLICES: dict[str, Slice] = {
    "exercices": Slice(
        _exercises,
        "le catalogue des exercices, avec leur groupe musculaire et leur identifiant "
        "— à demander avant d'ajouter une série",
    ),
    "exercices_cadence": Slice(
        _cadence_exercises,
        "les noms exacts du catalogue Cadence pour un mot-clé **en anglais** "
        "(`exercices_cadence:push up`) — à demander avant de créer une séance Cadence. "
        "Les noms d'exercices s'écrivent en anglais, tout le reste en français. "
        "Filtré sur le matériel déclaré au profil quand il y en a un, poids du corps "
        "compris ; je te le dis dans la réponse",
        search=_search_cadence_exercises,
    ),
    "seances_cadence": Slice(
        _cadence_circuits,
        "les séances Cadence déjà enregistrées, et la façon de nommer un exercice "
        "— à demander avant de créer une séance Cadence",
    ),
    "progression_charges": Slice(
        _lift_progress,
        "par exercice : dernière charge, écart avec la fois d'avant, record, 1RM estimé "
        "et les charges des dernières séances",
    ),
    "progression_tabata": Slice(
        _tabata_progress,
        "par exercice de tabata : la charge déclarée, depuis quand elle n'a pas bougé et "
        "combien de séances elle a tenu, plus les groupes par ancienneté de sollicitation "
        "— à demander avant de conseiller de monter ou de composer une séance. "
        "Ni 1RM ni record : un tabata n'a pas de charge maximale lisible",
    ),
    "detail_seances": Slice(
        _session_detail,
        "ce que les dernières séances ont réellement contenu, exercice par exercice : "
        "séries, répétitions, charge et volume",
    ),
    "repas_du_jour": Slice(
        _meals_today,
        "les repas d'une journée et leurs totaux — protéines, calories, sucres ajoutés, "
        "restant — avec les jetons pour en supprimer un",
    ),
    "hydratation_du_jour": Slice(
        _hydration_today,
        "ce qui a été bu dans la journée, la cible, le restant, et chaque prise avec son jeton",
    ),
    "pesees_recentes": Slice(
        _weights_recent, "les dix dernières pesées, avec les jetons pour en supprimer une"
    ),
    "supplements_du_jour": Slice(
        _supplements_today,
        "les suppléments prévus ce jour-là, pris ou non, avec l'identifiant pour les cocher",
    ),
    "planning_a_venir": Slice(
        _plan_ahead,
        "les séances prévues sur les quatre semaines qui suivent, avec les jetons pour en "
        "retirer une",
    ),
    "activites_recentes": Slice(
        _activity_recent,
        "les cinq dernières courses et séances : distance, durée, allure, fréquence "
        "cardiaque, dénivelé, effort perçu",
    ),
    "tendances": Slice(
        _trends,
        "pour chaque métrique suivie et sur trois mois : dernier relevé, moyenne, minimum, "
        "maximum et variation — à demander pour comparer deux métriques",
    ),
    "bilans_hebdomadaires": Slice(
        _weekly_reviews,
        "les bilans de semaine déjà écrits, au-delà des deux que tu as reçus",
    ),
    "jours_suivis": Slice(
        _tracking_days,
        "quels jours du dernier mois ont été relevés, source par source — à demander pour "
        "savoir si un trou est une absence de suivi ou une absence d'activité",
    ),
}


def describe_slices() -> list[str]:
    """Les tranches et ce qu'elles rendent, une ligne chacune, pour la consigne.

    Rendu depuis `SLICES` et non recopié à côté : c'est la règle du catalogue d'actions,
    dont `conversation.py` insère les lignes sans connaître un seul nom. Une tranche
    ajoutée sans description ferait échouer la batterie plutôt que d'arriver muette chez le
    modèle.
    """
    return [f"{nom} — {tranche.describes}" for nom, tranche in SLICES.items()]


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
        tranche = SLICES.get(need.name)
        if tranche is None:  # pragma: no cover - `read_need` a déjà filtré
            continue

        # Une tranche cherchée ne se déroule sur aucune période : elle ne lit rien de daté.
        # Le mot-clé absent retombe volontairement sur `load`, qui dit alors quoi demander.
        if tranche.search is not None and need.query:
            lines.extend(await tranche.search(store, need.query))
            continue

        rendu: list[str] = []
        vues: set[str] = set()
        for day in _days_of(need, current):
            if day > current and need.name not in FORWARD_LOOKING:
                # **Un jour qui n'a pas eu lieu n'a pas de relevé, et le dire est la seule
                # réponse juste.** Sans cette garde, `hydratation_du_jour@2030-01-01` rendait
                # « 0 ml sur une cible de 2000 ml, il reste 2000 ml à boire » — un déficit
                # annoncé sur une journée future, que le modèle lit comme un retard. Trouvé
                # en sondant des dates aberrantes, pas par un test.
                #
                # Le planning, lui, regarde devant : une séance prévue jeudi prochain est
                # une donnée réelle, et la refuser serait le défaut inverse.
                ligne = f"Le {day:%d/%m/%Y} n'a pas encore eu lieu : rien n'y est relevé."
                if ligne not in vues:
                    vues.add(ligne)
                    rendu.append(ligne)
                continue
            for line in await tranche.load(store, day):
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
    "FORWARD_LOOKING",
    "MAX_MEMORY_LINES",
    "MAX_PERIOD_LINES",
    "MAX_PROGRESS",
    "MAX_REVIEWS",
    "MAX_SERIES",
    "MAX_SESSIONS",
    "MAX_TRACKING_DAYS",
    "RECENT_INSIGHTS",
    "SLICES",
    "WEEK_AHEAD",
    "WEEK_BACK",
    "Slice",
    "build",
    "describe_slices",
    "memory_lines",
    "plan_lines",
    "slices",
    "week_lines",
]
