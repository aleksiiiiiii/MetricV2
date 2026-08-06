"""Formes échangées par le planning (`PLAN-01` → `PLAN-06`).

Trois familles, et leur séparation porte les garanties du lot :

* **charge utile** (`PlanPayload`) — ce que le client envoie, borné comme toute saisie
  (`API-06`). Sa date est `PlannedDate` et non `PastDate` : le planning est le seul
  domaine à porter des dates futures.
* **entrée** (`PlannedSession`) — ce que le client reçoit, avec `id` et `token`.
* **proposition** (`ProposedSession`) — ce qu'un modèle a suggéré et que **personne n'a
  encore validé** (`PLAN-04`). Elle n'a pas de jeton, et c'est le point : elle ne désigne
  aucune ligne, puisqu'il n'en existe encore aucune.
"""

from __future__ import annotations

# Le module et non le nom : ces schémas portent des champs **appelés** `date` et `time`,
# et un champ avec valeur par défaut masque le type homonyme au moment où pydantic relit
# l'annotation. `dt.date` ne peut être masqué par rien. (Le piège a déjà été payé au L12.)
import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.validation import DurationMin, Label, Note, PlannedDate

#: Les trois natures planifiables. Fermée côté API alors que le fichier tolère n'importe
#: quoi : le fichier doit survivre à un tableur, une saisie n'a pas cette excuse.
Kind = Literal["course", "muscu", "autre"]

#: `HH:MM` sur 24 heures. Le même motif que `supplements`, pour la même raison : c'est ce
#: qui se trie et ce qui se lit sans ambiguïté dans un tableur.
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


def _empty_time_is_none(value: str | None) -> str | None:
    """Une heure vide vaut « pas d'heure », pas une chaîne à valider.

    Un formulaire HTML envoie `""` pour un champ non rempli. Le refuser au motif qu'il ne
    ressemble pas à `HH:MM` rendrait l'heure obligatoire par accident, alors que `PLAN-02`
    la dit optionnelle.
    """
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class PlanPayload(BaseModel):
    """Une séance à planifier ou à corriger (`PLAN-02`)."""

    date: PlannedDate
    #: Facultative. Vide, la séance est prévue sans heure.
    time: str | None = Field(default=None, pattern=TIME_PATTERN)
    kind: Kind = "autre"
    title: Label
    duration_min: DurationMin
    note: Note | None = None

    _blank_time = field_validator("time", mode="before")(_empty_time_is_none)


class PlannedSession(BaseModel):
    """Une séance prévue, telle que le client la reçoit."""

    id: int
    token: str
    session_id: str
    date: dt.date
    time: str | None = None
    kind: Kind
    title: str
    duration_min: float
    note: str | None = None
    #: `manual` ou `ai` — l'origine reste lisible jusque dans le CSV (`PLAN-04`).
    source: str


class DoneActivity(BaseModel):
    """Une activité **réellement effectuée**, telle que le calendrier la montre.

    Elle ne vient pas de `plan.csv` mais des fichiers du domaine Activité : le planning
    n'écrit jamais ce qui a eu lieu, et ne le recopie pas non plus.
    """

    kind: Literal["run", "workout"]
    #: Position de la ligne dans son fichier, pour aller la voir sur `/activite`.
    id: int
    label: str
    duration_min: float


class DayCell(BaseModel):
    """Une case du calendrier mensuel (`PLAN-01`)."""

    date: dt.date
    #: Faux pour les jours de débordement — la semaine du 1er commence souvent en juillet.
    in_month: bool
    planned: list[PlannedSession] = Field(default_factory=list)
    done: list[DoneActivity] = Field(default_factory=list)


class MonthView(BaseModel):
    """Un mois entier, semaine au lundi (`PLAN-01`).

    Les jours sont rendus **en bloc et dans l'ordre**, débordements compris : le client
    n'a aucun trou à combler ni aucune semaine à recomposer. C'est la même exigence que
    `HEAT-24`, et elle vaut ici pour une raison de plus — recalculer le premier lundi du
    mois côté client serait un calcul de date, donc une seconde implémentation de la
    règle « la semaine commence le lundi ».
    """

    #: Premier jour du mois demandé, `AAAA-MM-01`.
    month: dt.date
    #: Bornes réellement rendues, débordements compris.
    start: dt.date
    end: dt.date
    days: list[DayCell]
    #: Aujourd'hui, tel que le serveur le voit. L'écran ne calcule pas sa propre date :
    #: le fuseau de découpage est un réglage du serveur (`HEAT-32`).
    today: dt.date


class WeekAdherence(BaseModel):
    """Écart plan / réalisé d'une semaine (`PLAN-06`)."""

    #: Lundi de la semaine ISO.
    week: dt.date
    planned: int
    done: int
    #: Séances prévues dont le jour porte au moins une activité réelle.
    honoured: int
    #: `honoured / planned`. **`null` quand rien n'était prévu** : une semaine sans
    #: planning n'a pas un taux de 0 %, elle n'a pas de taux du tout.
    rate: float | None = Field(default=None, ge=0, le=1)


class AdherenceView(BaseModel):
    """Respect du planning, semaine par semaine (`PLAN-06`).

    **Troisième taux du projet, et il ne fusionne avec aucun des deux autres.** `AGG-03`
    mesure l'assiduité de *suivi* — a-t-on relevé quelque chose ce jour-là. `HEAT-27`
    mesure le respect d'un *engagement* de cadence — « deux fois par semaine ». Celui-ci
    mesure le respect d'un *rendez-vous* : la séance prévue mardi a-t-elle eu lieu mardi.

    Les trois répondent à trois questions différentes, et les confondre donnerait un
    chiffre dont personne ne saurait dire ce qu'il compte.
    """

    weeks: list[WeekAdherence]
    #: Taux sur toute la fenêtre. `null` si rien n'était prévu — jamais `0`.
    rate: float | None = Field(default=None, ge=0, le=1)
    planned: int
    honoured: int


# ── Génération assistée (`PLAN-03`, `PLAN-04`) ────────


class ProposalRequest(BaseModel):
    """Ce qu'on demande au modèle (`PLAN-03`)."""

    #: Une semaine ou deux, jamais plus : au-delà, la fréquence réelle sur laquelle la
    #: proposition s'appuie a le temps de changer.
    weeks: Literal[1, 2] = 1
    #: Premier jour planifié. Par défaut, le lundi prochain — on ne remplit pas une
    #: semaine déjà entamée.
    start: PlannedDate | None = None
    #: Contraintes libres : « pas le mercredi », « genou fragile », « une seule sortie
    #: longue ». Transmises telles quelles au modèle.
    constraints: str = Field(default="", max_length=500)
    #: Objectif à faire tenir au planning. **Facultatif depuis le lot L14** : laissé vide,
    #: le serveur y met l'objectif actif de `goals/goals.csv` (`GOAL-01`).
    #:
    #: Rempli, il le **remplace** ponctuellement — « cette semaine je prépare une course »
    #: n'a pas vocation à devenir un objectif de six semaines. C'est ce qui reste de
    #: l'écart assumé du L13, où le champ était la seule façon de faire entrer un objectif
    #: dans la consigne, et où l'oublier une fois donnait une semaine qui l'ignorait sans
    #: le dire.
    objective: str = Field(default="", max_length=300)


class ProposedSession(BaseModel):
    """Une séance proposée, **pas encore écrite** (`PLAN-04`).

    Pas de jeton, pas d'identifiant de ligne : elle ne désigne rien dans le fichier. Ce
    qui la distingue d'une séance réelle à l'écran — trait discontinu, bloc IA — est la
    même chose qui distingue une macro estimée d'une macro relevée (`NUT-04`).
    """

    date: dt.date
    time: str | None = None
    kind: Kind
    title: str
    duration_min: float
    note: str | None = None
    #: Motif du choix, en une phrase : « dos non travaillé depuis 12 jours ».
    #: Affiché, jamais écrit dans le fichier — c'est un argument, pas une donnée.
    reason: str | None = None


class Proposal(BaseModel):
    """Ce que la génération rend. **Aucune ligne n'a été écrite** (`PLAN-04`)."""

    sessions: list[ProposedSession]
    start: dt.date
    end: dt.date
    #: Ce sur quoi la proposition s'appuie, dit à l'écran : « 3,2 séances par semaine sur
    #: les 4 dernières semaines ». Une suggestion dont on voit l'argument se discute ;
    #: une suggestion nue se croit ou se rejette.
    basis: list[str] = Field(default_factory=list)
    #: Séances écartées à la relecture, et pourquoi. Les taire laisserait croire que le
    #: modèle n'a proposé que cela.
    dropped: list[str] = Field(default_factory=list)


class AdoptionPayload(BaseModel):
    """Les séances retenues, après retrait individuel (`PLAN-04`).

    Le client renvoie **ce qu'il garde**, pas ce qu'il retire : c'est ce qui rend le
    retrait individuel gratuit côté serveur, et ce qui garantit qu'une séance retirée à
    l'écran ne peut pas être écrite par un désaccord d'index.

    Les séances passent par les mêmes bornes qu'une saisie manuelle : personne n'a tapé
    ces chiffres, ils méritent plutôt plus de méfiance que moins.
    """

    sessions: list[PlanPayload] = Field(min_length=1, max_length=30)


class AdoptionResult(BaseModel):
    """Ce qui a été écrit, une fois l'adoption confirmée."""

    created: list[PlannedSession]


# ── Abonnement iCal (`PLAN-05`) ───────────────────────


class SubscriptionInfo(BaseModel):
    """État de l'abonnement au flux `.ics`.

    Même forme que `AiStatus`, et pour la même raison : un écran ne demande jamais « la
    clé est-elle configurée ? » à sa propre configuration — il ne la connaît pas. Il le
    demande au serveur, qui répond `200` dans les deux cas et fournit la phrase à
    afficher, en français (`API-07`).
    """

    configured: bool
    #: Adresse d'abonnement, clé comprise. `null` tant qu'aucune clé n'est configurée.
    url: str | None = None
    message: str
