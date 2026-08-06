"""Formes échangées par les objectifs et le bilan hebdomadaire (`GOAL-01` → `GOAL-06`,
`IA-08`).

Trois familles, et leur séparation porte les garanties du lot :

* **charge utile** (`GoalPayload`) — ce que le client envoie pour adopter. Bornée comme
  toute saisie (`API-06`), et son échéance est `PlannedDate` et non `PastDate` : un
  objectif se date **dans le futur**, c'est le second endroit du projet à en avoir besoin
  après le planning.
* **entrée** (`GoalEntry`) — ce que le client reçoit, avec `id` et `token`.
* **proposition** (`ProposedGoal`) — ce qu'un modèle a suggéré et que **personne n'a
  encore validé** (`GOAL-03`). Pas de jeton, pas de ligne : elle ne désigne rien dans le
  fichier, puisqu'il n'y a encore rien à désigner. C'est exactement la forme de
  `ProposedSession` (`PLAN-04`) et de `MealEstimate` (`NUT-04`) — le projet n'a qu'une
  façon de dire « pas encore validé », et ce n'est pas le moment d'en inventer une
  quatrième.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.validation import Note, PlannedDate, today_local

#: Bornes de l'échéance (`GOAL-01` : « daté sur 4 à 8 semaines »).
#:
#: En deçà, la progression n'a pas le temps de se voir sur une moyenne de quatre semaines.
#: Au-delà, l'objectif cesse d'informer la semaine qui vient — et c'est justement ce que le
#: bilan hebdomadaire attend de lui.
DEADLINE_MIN_WEEKS = 4
DEADLINE_MAX_WEEKS = 8

#: Longueurs alignées sur `Label` et `Note`.
MAX_TITLE = 80
MAX_RATIONALE = 500
MAX_SUMMARY = 1200

#: Les trois états de `GOAL-05`, tels que le **serveur** les connaît.
#:
#: Le troisième — « suggestion en attente » — n'est pas ici, et c'est volontaire : une
#: proposition non adoptée n'existe nulle part côté serveur. Elle vit dans l'écran qui
#: vient de la recevoir, et se perd si on recharge la page. C'est la traduction exacte de
#: « rien n'est écrit sans validation » : un état qui survivrait au rechargement serait un
#: état écrit quelque part.
GoalState = Literal["none", "active"]


class GoalPayload(BaseModel):
    """Un objectif à adopter (`GOAL-03`).

    Les valeurs passent par les mêmes bornes qu'une saisie manuelle, et pour la raison
    déjà écrite à l'adoption d'un planning : **personne n'a tapé ces chiffres**, ils
    méritent plutôt plus de méfiance que moins.

    L'unité n'est pas ici. Elle vient du registre des métriques, servie et jamais
    recopiée : un client qui l'enverrait pourrait écrire « kg » sur un objectif de
    protéines, et le fichier mentirait pour toujours.
    """

    title: str = Field(min_length=1, max_length=MAX_TITLE)
    #: Clé du registre, restreinte aux cinq de `GOAL-04`. Le contrôle d'appartenance vit
    #: dans le service, qui a le registre sous la main ; le schéma en garde la forme.
    metric: str = Field(min_length=1, max_length=40)
    target: float
    deadline: PlannedDate
    rationale: Note = ""

    @model_validator(mode="after")
    def _deadline_within_horizon(self) -> GoalPayload:
        """L'échéance tient dans la fenêtre de `GOAL-01`, à l'adoption comme à la
        proposition.

        La borne est relative au jour de l'adoption et non à `created` : c'est le même
        instant, et faire dépendre une validation d'un champ que le client fournirait
        reviendrait à lui laisser choisir la règle.
        """
        today = today_local()
        floor = today + dt.timedelta(weeks=DEADLINE_MIN_WEEKS)
        ceiling = today + dt.timedelta(weeks=DEADLINE_MAX_WEEKS)
        if not floor <= self.deadline <= ceiling:
            raise ValueError(
                f"l'échéance doit tomber entre {DEADLINE_MIN_WEEKS} et "
                f"{DEADLINE_MAX_WEEKS} semaines d'ici"
            )
        return self


class GoalProgress(BaseModel):
    """Avancement vers la cible (`GOAL-04`).

    **Ce n'est pas un quatrième taux de respect.** `AGG-03` mesure l'assiduité de *suivi*,
    `HEAT-27` le respect d'un *engagement* de cadence, `PLAN-06` le respect d'un
    *rendez-vous*. Celui-ci mesure autre chose encore : la distance parcourue entre le
    chiffre qu'on avait et le chiffre qu'on s'est fixé. Les quatre resteront distincts.
    """

    metric: str
    label: str
    unit: str
    #: Valeur de la métrique le jour de l'adoption, redéduite des mêmes données. `null`
    #: quand rien n'avait été relevé — l'avancement est alors indéterminé, pas nul.
    baseline: float | None = None
    current: float | None = None
    target: float
    #: `0` → au point de départ, `1` → cible atteinte. `null` faute de point de départ.
    ratio: float | None = Field(default=None, ge=0, le=1)
    #: Libellé chiffré prêt à afficher : « 2,4 sur 3 séances · séances par semaine ».
    summary: str
    #: Fenêtre d'observation, dite en français : « moyenne des 4 dernières semaines
    #: complètes ». Un chiffre dont on voit la fenêtre se discute.
    basis: str


class GoalEntry(BaseModel):
    """Un objectif écrit, tel que le client le reçoit."""

    id: int
    token: str
    goal_id: str
    created: dt.date | None = None
    title: str
    metric: str
    target: float
    unit: str
    deadline: dt.date
    rationale: str = ""
    #: `manual` ou `ai` (`GOAL-03`).
    source: str
    status: str
    #: `reached`, `partial`, `abandoned`, ou vide tant que l'objectif est en cours.
    outcome: str = ""
    #: Libellé français du résultat, pour que l'écran n'ait pas à traduire un code.
    outcome_label: str = ""


class ActiveGoal(BaseModel):
    """L'objectif en cours, avec ce qu'il faut pour le juger (`GOAL-05`)."""

    goal: GoalEntry
    progress: GoalProgress
    #: Jours restants avant l'échéance. Négatif une fois celle-ci passée.
    days_left: int
    #: Vrai quand l'échéance est derrière nous. L'objectif reste `active` dans le fichier
    #: — il n'est clos que par un geste, jamais par une lecture : un `GET` qui écrirait
    #: fausserait aussi bien le cache que la promesse « rien sans validation ».
    expired: bool


class GoalsView(BaseModel):
    """Tout l'écran Objectif en une requête (`GOAL-05`, `GOAL-06`)."""

    state: GoalState
    active: ActiveGoal | None = None
    #: Objectifs clos, du plus récent au plus ancien.
    history: list[GoalEntry] = Field(default_factory=list)
    #: Aujourd'hui **selon le serveur**. L'écran ne calcule pas sa propre date (`HEAT-32`).
    today: dt.date


# ── Génération assistée (`GOAL-01`, `GOAL-02`, `GOAL-03`) ──


class ProposalRequest(BaseModel):
    """Ce qu'on demande au modèle."""

    #: Envie du moment : « je veux courir plus », « perdre du ventre ». Transmise telle
    #: quelle. Vide, le modèle choisit sur les seules données.
    focus: str = Field(default="", max_length=300)


class ProposedGoal(BaseModel):
    """Un objectif proposé, **pas encore écrit** (`GOAL-03`)."""

    title: str
    metric: str
    label: str
    target: float
    unit: str
    deadline: dt.date
    rationale: str = ""


class GoalProposal(BaseModel):
    """Ce que la génération rend. **Aucune ligne n'a été écrite.**"""

    goal: ProposedGoal
    #: Le condensé factuel réellement envoyé au modèle, ligne par ligne (`GOAL-02`).
    #: Publié pour une raison simple : c'est la seule façon de vérifier à l'écran que les
    #: fichiers n'ont pas été envoyés entiers, et de voir sur quoi la suggestion s'appuie.
    basis: list[str] = Field(default_factory=list)
    #: Vrai quand les données étaient trop maigres pour viser un chiffre de performance :
    #: la demande s'est alors repliée sur un objectif de régularité (`GOAL-01`).
    fallback: bool = False
    #: Ce qui a été écarté à la relecture, et pourquoi.
    dropped: list[str] = Field(default_factory=list)


# ── Bilan hebdomadaire (`IA-08`) ──────────────────────


class WeeklyEntry(BaseModel):
    """Un bilan conservé."""

    id: int
    token: str
    week: dt.date
    created: dt.date | None = None
    summary: str
    source: str


class WeeklyReview(BaseModel):
    """Un bilan proposé, **pas encore conservé** (`IA-08`).

    Même forme que partout ailleurs : le modèle rend, l'écran montre, un appui écrit. Un
    bilan qu'on trouve à côté de la plaque n'a aucune raison d'entrer dans l'historique
    d'où la génération suivante tirera son contexte.
    """

    week: dt.date
    #: Les trois parties que `IA-08` demande, séparées plutôt que noyées dans un
    #: paragraphe : elles ne se lisent pas de la même façon.
    progress: list[str] = Field(default_factory=list)
    setbacks: list[str] = Field(default_factory=list)
    action: str = ""
    #: Le condensé factuel envoyé au modèle, publié comme celui d'une proposition.
    basis: list[str] = Field(default_factory=list)

    def to_summary(self) -> str:
        """Le bilan en une cellule de tableur, lisible sans l'application.

        Le fichier ne porte qu'une colonne `summary` : la mise en forme se replie donc en
        une phrase continue. C'est le prix de « les données restent exploitables dans un
        tableur même si l'application disparaît », et il est modeste.
        """
        parts: list[str] = []
        if self.progress:
            parts.append("Progrès : " + " ".join(self.progress))
        if self.setbacks:
            parts.append("Décrochages : " + " ".join(self.setbacks))
        if self.action:
            parts.append("Action : " + self.action)
        return " — ".join(parts)[:MAX_SUMMARY]


class WeeklyPayload(BaseModel):
    """Le bilan qu'on choisit de conserver (`IA-08`)."""

    week: dt.date
    summary: str = Field(min_length=1, max_length=MAX_SUMMARY)


class WeeklyView(BaseModel):
    """L'historique des bilans, du plus récent au plus ancien."""

    entries: list[WeeklyEntry] = Field(default_factory=list)
    #: Semaine révolue que le prochain bilan commenterait — le lundi d'il y a sept jours.
    next_week: dt.date
    #: Vrai si cette semaine-là a déjà son bilan. Conserver à nouveau le **remplacerait**.
    already_kept: bool = False
