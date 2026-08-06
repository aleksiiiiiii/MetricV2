"""Modèle CSV du planning sport.

`planning/plan.csv` : id, date, time, kind, title, duration_min, note, source

**Ce fichier décrit ce qui est prévu, pas ce qui a eu lieu.** Il appartient donc à la
famille *planning* du §2 de `docs/etat-du-projet.md`, avec `settings.csv`, les trois
fichiers de pistes et `supplements/schedule.csv` — et non à la famille *mesure*, qui
refuse une ligne illisible.

La conséquence tient en une phrase : **toutes les colonnes portent un défaut**, y compris
`date`. C'est ce qui rend `STO-04` vrai ici, et ce n'est pas une précaution théorique —
une cellule `time` vide de `supplements/schedule.csv` a fait tomber le tableau de bord
entier en `502` au premier usage réel. La colonne `time` de ce fichier-ci est
**facultative par conception** (`PLAN-02` : « heure optionnelle ») : elle sera vide bien
plus souvent qu'elle ne l'a été là-bas, et une séance sans horaire est un cas normal, pas
une ligne abîmée.

Une ligne sans identifiant ou sans date est écartée des vues — on ne sait pas quel jour
l'afficher ni quelle ligne modifier — mais elle **survit dans le fichier** : on n'efface
pas ce qu'on ne comprend pas.
"""

from __future__ import annotations

from app.storage.model import CsvDate, CsvModel, CsvNumber

#: Natures de séance planifiables (`PLAN-02`). Contrairement au `type` d'une séance
#: réalisée, qui reste libre (`ACT-03`), celle-ci est **fermée** : elle sert à comparer
#: un plan à un réalisé et à colorer un calendrier. Trois valeurs suffisent, et le titre
#: porte le détail — « muscu » + « Haut du corps » dit tout ce qu'il faut.
KINDS: tuple[str, ...] = ("course", "muscu", "autre")

#: Repli d'une nature illisible. Une valeur mal orthographiée dans un tableur donne une
#: séance « autre » plutôt qu'une ligne perdue.
DEFAULT_KIND = "autre"


def normalise_kind(raw: str) -> str:
    """Ramène une cellule `kind` à l'une des trois natures connues."""
    cleaned = raw.strip().lower()
    return cleaned if cleaned in KINDS else DEFAULT_KIND


class PlanRow(CsvModel):
    """Une séance prévue. `planning/plan.csv`."""

    #: Identifiant stable, et non la position : le flux iCal en fait son `UID`, et un
    #: `UID` qui change à chaque suppression de ligne ferait réapparaître les séances en
    #: double dans un calendrier abonné.
    id: str = ""
    date: CsvDate = None
    #: `HH:MM`, **facultatif**. Vide, la séance est prévue sans heure : elle s'affiche en
    #: tête de journée et sort en évènement « toute la journée » dans le flux iCal.
    time: str = ""
    #: `course`, `muscu` ou `autre` — voir `KINDS`.
    kind: str = DEFAULT_KIND
    title: str = ""
    #: Durée prévue en minutes. `0` signifie « non renseignée », ce que seule une édition
    #: à la main peut produire : la saisie, elle, l'exige.
    duration_min: CsvNumber = 0
    note: str = ""
    #: `manual` ou `ai` (`PLAN-04`). Ce que la colonne raconte, c'est d'où vient la ligne.
    source: str = "manual"
