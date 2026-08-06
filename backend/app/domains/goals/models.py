"""Modèles CSV des objectifs et des bilans hebdomadaires.

`goals/goals.csv` : id, created, title, metric, target, unit, deadline, rationale,
source, status, outcome

`insights/weekly.csv` : week, created, summary, source

**Deux fichiers de la famille *planning*, pas de la famille *mesure*** (§2 de
`docs/etat-du-projet.md`). Un objectif n'est pas un relevé : c'est une intention datée,
écrite une fois puis relue longtemps. Toutes les colonnes portent donc un défaut, `created`
et `deadline` comprises, et une ligne abîmée dans un tableur rend l'écran incomplet, jamais
en `502`. La règle a coûté le tableau de bord entier au premier usage réel, sur un fichier
de la même famille.

Une ligne sans identifiant, sans métrique ou sans échéance est écartée des vues — on ne
saurait ni sur quoi mesurer sa progression ni jusqu'à quand — mais elle **survit dans le
fichier** : on n'efface pas ce qu'on ne comprend pas.

La colonne `unit` est **écrite par le serveur**, jamais envoyée par le client : elle vient
du registre des métriques (`METRICS`), qui en détient l'unique définition. Elle est
recopiée dans le fichier pour une raison précise — « le fichier doit se lire seul » : dans
dix ans, `target=3` sans unité ne voudra rien dire, `3 séances` se lira encore.
"""

from __future__ import annotations

from app.storage.model import CsvDate, CsvModel, CsvNumber

# ── Statuts (`GOAL-03`, `GOAL-05`) ────────────────────

#: Objectif en cours. Il n'y en a **qu'un** à la fois (`GOAL-01` : « objectif unique »).
STATUS_ACTIVE = "active"
#: Objectif terminé, quel qu'en soit le résultat. Il rejoint l'historique (`GOAL-06`).
STATUS_CLOSED = "closed"

STATUSES: tuple[str, ...] = (STATUS_ACTIVE, STATUS_CLOSED)

# ── Résultats finaux (`GOAL-06`) ──────────────────────

#: Cible atteinte ou dépassée.
OUTCOME_REACHED = "reached"
#: Objectif mené à son terme sans que la cible soit atteinte.
OUTCOME_PARTIAL = "partial"
#: Objectif interrompu en cours de route, par décision et non par échec de mesure.
OUTCOME_ABANDONED = "abandoned"

OUTCOMES: tuple[str, ...] = (OUTCOME_REACHED, OUTCOME_PARTIAL, OUTCOME_ABANDONED)

#: Les trois libellés du backlog, tels qu'ils s'affichent. Ils vivent ici parce que la
#: consigne envoyée au modèle les réutilise (`GOAL-06` : l'historique est réinjecté dans
#: la génération suivante), et deux traductions du même mot finiraient par diverger.
OUTCOME_LABELS: dict[str, str] = {
    OUTCOME_REACHED: "atteint",
    OUTCOME_PARTIAL: "partiel",
    OUTCOME_ABANDONED: "abandonné",
}


def normalise_status(raw: str) -> str:
    """Ramène une cellule `status` à l'un des deux statuts connus.

    Le repli est `active` et non `closed` : une ligne dont le statut est illisible décrit
    un objectif qu'on a pris la peine d'écrire, et le faire disparaître dans l'historique
    serait plus surprenant que de le montrer en cours.
    """
    cleaned = raw.strip().lower()
    return cleaned if cleaned in STATUSES else STATUS_ACTIVE


def normalise_outcome(raw: str) -> str:
    """Ramène une cellule `outcome` à l'un des trois résultats, ou à la chaîne vide.

    Vide est une valeur normale : un objectif en cours n'a pas encore de résultat, et lui
    en attribuer un serait inventer une valeur.
    """
    cleaned = raw.strip().lower()
    return cleaned if cleaned in OUTCOMES else ""


class GoalRow(CsvModel):
    """Un objectif. `goals/goals.csv`."""

    #: Identifiant stable, et non la position : l'historique se relit après des
    #: suppressions de lignes, et la génération suivante cite les objectifs passés.
    id: str = ""
    #: Jour d'adoption. C'est de lui que se déduit le **point de départ** de la
    #: progression (`GOAL-04`) : la valeur qu'avait la métrique ce jour-là.
    created: CsvDate = None
    title: str = ""
    #: Clé du registre `METRICS`, restreinte aux cinq métriques de `GOAL-04`.
    metric: str = ""
    target: CsvNumber = 0
    #: Unité recopiée du registre, pour que la ligne se lise sans l'application.
    unit: str = ""
    #: Échéance, **dans le futur** à l'adoption. C'est la seconde colonne du projet à
    #: porter une date à venir, après `planning/plan.csv`.
    deadline: CsvDate = None
    rationale: str = ""
    #: `ai` ou `manual` — d'où vient la ligne, pas ce qu'elle vaut.
    source: str = "ai"
    status: str = STATUS_ACTIVE
    #: Vide tant que l'objectif est en cours (`GOAL-06`).
    outcome: str = ""


class WeeklyRow(CsvModel):
    """Un bilan hebdomadaire. `insights/weekly.csv` (`IA-08`)."""

    #: Lundi de la semaine **révolue** que le bilan commente. C'est la clé naturelle du
    #: fichier : deux lignes pour la même semaine rendraient « le bilan de la semaine du
    #: 3 août » ambigu, et un fichier destiné à un tableur ne porte pas deux vérités.
    week: CsvDate = None
    created: CsvDate = None
    summary: str = ""
    source: str = "ai"
