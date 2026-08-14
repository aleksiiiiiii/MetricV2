"""Lecture d'une séance écrite en clair, ou photographiée (`C07`).

Ce module traduit « développé couché 4x8 60kg / tractions 3xmax » en lignes qu'on peut
relire, corriger, puis enregistrer. Il ne décide **d'aucune écriture** : ce qui en sort est
un tableau que l'utilisateur valide ligne par ligne.

## Trois règles, et elles ne se négocient pas

**Le nom du catalogue l'emporte toujours.** Quand la note dit « dev couché » et que le
catalogue porte « Développé couché », c'est le second qui s'affiche et qui s'écrit. Ce que
la note contenait devient un **alias** — la fois suivante, la même abréviation sera
reconnue sans rien demander. Sans cette règle, l'historique se remplirait de dix graphies
du même mouvement, et les statistiques par exercice compteraient dix exercices.

**Une charge dans une autre unité que le kilogramme reste vide.** `135 lbs` n'est pas
converti : le domaine convertit déjà les miles en kilomètres pour les distances, mais une
conversion faite ici, sur une lecture de modèle, produirait un nombre d'apparence honnête
que personne n'a soulevé. Le champ vide dit ce qu'il en est ; la valeur se retape.

**Le poids du corps vaut zéro**, qui est une valeur légitime du domaine (`ACT-07`) et non
une absence — c'est déjà la convention de `exercise_log.csv`.

## Qui rapproche, et pourquoi pas une distance d'édition

Deux mécanismes, et ils ne portent pas le même risque.

**Ce qui est déjà connu est reconnu sans rien demander** : le nom d'un exercice ou l'un de
ses alias, comparé au repli près. C'est exact, sans approximation, et cela n'écrit rien.

**Ce qui ressemble à un exercice connu est proposé par le modèle**, qui reçoit la liste du
catalogue et dit à quelle entrée il croit avoir affaire. Ce n'est ni une distance d'édition
ni un « à peu près » calculé ici : une mesure de similarité qui se trompe fusionnerait deux
mouvements distincts dans l'historique, et le projet n'a pas d'annulation. Une proposition
du modèle, elle, **passe par une validation ligne à ligne** avant d'écrire quoi que ce
soit — c'est ce que le ticket exige, et c'est ce qui rend le rapprochement tenable.

Ce que le modèle ne rattache à rien est proposé à la **création**, avec son groupe déduit.
"""

from __future__ import annotations

from typing import Any

from app.core.text import fold
from app.domains.activity.schemas import NoteLine

#: Rôle du modèle.
INSTRUCTION = (
    "Tu lis des notes de séance de musculation, manuscrites ou tapées. Tu réponds "
    "uniquement par un objet JSON, sans phrase avant ni après, sans bloc de code."
)

#: La consigne. Deux points y font tout le travail : l'interdiction de convertir, et
#: l'ordre de laisser vide plutôt que de deviner. Ce sont les deux façons dont une lecture
#: de notes produit des chiffres faux d'apparence plausible.
PROMPT = """Relève les exercices de cette séance.

Réponds par cet objet JSON exactement :
{"exercises": [{"name": "…", "match": "…", "muscle_group": "…", "sets": 0, "reps": 0,
 "weight": "…"}], "readable": true}

- "name" : le nom de l'exercice tel qu'il est écrit dans la note, sans le corriger.
- "match" : le nom du catalogue ci-dessous qui désigne le MÊME mouvement, recopié à
  l'identique. null si aucun ne correspond, ou dans le moindre doute — proposer une
  correspondance fausse est bien pire que n'en proposer aucune.
- "muscle_group" : un seul parmi pectoraux, dos, épaules, biceps, triceps, jambes,
  fessiers, abdos, autre.
- "sets" : nombre de séries. null si la note ne le dit pas.
- "reps" : répétitions par série. null pour « max », « échec », ou si la note se tait.
- "weight" : recopie la charge ET son unité, exactement ("60kg", "135 lbs", "poids du
  corps"). Ne convertis rien. null si la note ne porte aucune charge.
- "readable" : false si ce texte n'est pas une séance de musculation.

Recopie ce qui est écrit. N'ajoute aucun exercice que la note ne mentionne pas, et ne
complète aucune valeur absente."""

#: Ce qu'on accepte d'écrire dans `muscle_group`. Hors de cette liste, `autre` — le
#: domaine n'a que neuf groupes et un dixième casserait les statistiques.
_GROUPS = (
    "pectoraux",
    "dos",
    "épaules",
    "biceps",
    "triceps",
    "jambes",
    "fessiers",
    "abdos",
    "autre",
)

#: Les façons dont une note dit « poids du corps ». Elles valent **0**, qui est une
#: mesure et non une absence (`ACT-07`).
_BODYWEIGHT = frozenset(
    {"poids du corps", "pdc", "bodyweight", "bw", "corps", "sans charge", "a vide", "à vide"}
)

#: Les unités qu'on sait lire. Tout le reste laisse la charge **vide** : convertir ici
#: produirait un nombre que personne n'a soulevé.
_KILOS = ("kg", "kgs", "kilo", "kilos", "k")

#: Bornes de vraisemblance, alignées sur `app/core/validation.py`.
_MAX_LOAD = 1000.0
_MAX_SETS = 50
_MAX_REPS = 200


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _count(value: Any, *, high: int) -> int | None:
    """Un compte de séries ou de répétitions, ou `None`.

    « max » et « échec » arrivent en texte : ce sont des répétitions réelles mais inconnues,
    et les remplacer par un nombre les inventerait.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = int(value)
    elif isinstance(value, str):
        try:
            number = int(float(value.strip().replace(",", ".")))
        except ValueError:
            return None
    else:
        return None
    return number if 1 <= number <= high else None


def read_load(raw: str) -> tuple[float | None, str | None]:
    """La charge en kilogrammes, et la raison quand il n'y en a pas.

    Rend `(None, raison)` plutôt que `(None, None)` sur une unité étrangère : l'écran doit
    pouvoir **dire** pourquoi le champ est vide, sinon la ligne passe pour une lecture
    ratée alors que c'est un refus délibéré.
    """
    text = raw.strip().lower()
    if not text:
        return None, None

    if text in _BODYWEIGHT:
        # Zéro est une valeur du domaine, pas une absence de valeur (`ACT-07`).
        return 0.0, None

    digits = "".join(c for c in text if c.isdigit() or c in ",.").replace(",", ".")
    unit = "".join(c for c in text if c.isalpha())

    if not digits:
        return None, None

    try:
        value = float(digits)
    except ValueError:
        return None, None

    if unit and unit not in _KILOS:
        return None, f"charge en {unit}, non convertie"
    if not 0 <= value <= _MAX_LOAD:
        return None, None
    return round(value, 2), None


def prompt_with(catalogue: list[Any]) -> str:
    """La consigne, augmentée du catalogue existant.

    Le modèle a besoin de la liste pour proposer un rapprochement : sans elle, il ne peut
    que rendre ce que la note contient, et tout arriverait en création. C'est un tri, pas
    une décision — chaque proposition est validée à l'écran avant d'écrire.
    """
    if not catalogue:
        return PROMPT
    names = "\n".join(f"- {exercise.name}" for exercise in catalogue[:120])
    return f"{PROMPT}\n\n## Catalogue existant\n\n{names}"


def read_lines(payload: dict[str, Any]) -> list[NoteLine]:
    """Traduit la réponse du modèle en lignes affichables. **Rien n'est écrit.**"""
    raw = payload.get("exercises")
    if not isinstance(raw, list):
        return []

    lines: list[NoteLine] = []
    for item in raw[:60]:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        if not name:
            continue

        group = _text(item.get("muscle_group")).lower()
        weight, why = read_load(_text(item.get("weight")))

        line = NoteLine(
            name=name[:80],
            muscle_group=group if group in _GROUPS else "autre",
            sets=_count(item.get("sets"), high=_MAX_SETS),
            reps=_count(item.get("reps"), high=_MAX_REPS),
            weight_kg=weight,
            note=why,
        )
        # Le rapprochement proposé par le modèle voyage à part : `match` le confrontera
        # au catalogue réel, parce qu'un modèle nomme volontiers une entrée qui n'existe
        # pas.
        line.alias_of = _text(item.get("match")) or None
        lines.append(line)
    return lines


def match(lines: list[NoteLine], catalogue: list[Any]) -> list[NoteLine]:
    """Rapproche chaque ligne du catalogue, sans rien y écrire.

    Trois issues par ligne, et l'écran les distingue parce qu'elles ne coûtent pas la même
    chose : `known` ne touche à rien, `alias` ajoute une graphie à un exercice existant,
    `new` crée une entrée. Les deux dernières se valident **une par une**.

    La comparaison est **exacte, sur des noms repliés**. Aucune approximation : rapprocher
    « développé couché » et « développé incliné » parce qu'ils se ressemblent fusionnerait
    deux mouvements distincts dans l'historique, et rien ne le déferait.
    """
    known: dict[str, Any] = {}
    by_catalogue_name: dict[str, Any] = {}
    for exercise in catalogue:
        known.setdefault(fold(exercise.name), exercise)
        by_catalogue_name.setdefault(fold(exercise.name), exercise)
        for alias in exercise.aliases:
            known.setdefault(fold(alias), exercise)

    for line in lines:
        proposed = line.alias_of
        line.alias_of = None

        found = known.get(fold(line.name))
        if found is not None:
            # Déjà connu — par son nom ou par un alias appris précédemment. Rien à écrire
            # au catalogue, et rien à valider : c'est ce qui rend la lecture de plus en
            # plus silencieuse au fil des séances.
            line.exercise_id = found.exercise_id
            line.muscle_group = found.muscle_group
            line.name = found.name
            line.status = "known"
            continue

        # Le modèle propose un rapprochement : on ne le croit que s'il désigne une entrée
        # qui existe vraiment, et l'écran le fera valider ligne à ligne.
        target = by_catalogue_name.get(fold(proposed or ""))
        if target is not None:
            line.exercise_id = target.exercise_id
            line.muscle_group = target.muscle_group
            # Ce que la note portait devient l'alias ; le nom du catalogue s'impose.
            line.alias_of = line.name
            line.name = target.name
            line.status = "alias"
            continue

        line.status = "new"
    return lines


def is_unreadable(payload: dict[str, Any], lines: list[NoteLine]) -> bool:
    """Vrai quand la note n'a rien donné d'exploitable.

    Comme pour une capture (`IMP-06`) : le modèle peut le dire lui-même, ou avoir répondu
    poliment sans rien lire. Une note qui ne produit aucune ligne ne pré-remplit rien, et
    mieux vaut le dire que d'ouvrir un tableau vide en le présentant comme une lecture.
    """
    return payload.get("readable") is False or not lines
