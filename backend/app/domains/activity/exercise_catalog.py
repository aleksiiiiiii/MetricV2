"""Le catalogue d'exercices de Cadence Tabata, figé dans le dépôt (**C5**).

Module **pur**, comme `circuit_link.py` : aucun réseau, aucun fichier utilisateur, aucune
dépendance FastAPI. Il lit une fois `exercise_catalog.json` — 1324 exercices, une centaine
de kilo-octets — et le tient en mémoire pour la vie du processus.

## Pourquoi un fichier du dépôt et pas un appel à Cadence

Cadence sert le même catalogue à `<base>/exercise-db/catalog.json`. L'appeler ferait
dépendre la saisie d'un circuit de la disponibilité d'une autre application, et ajouterait
à l'écran un état « catalogue injoignable » dont il n'a aucun besoin. Le prix admis est
que ce fichier vieillit ; `scripts/build-exercise-catalog.mjs` le régénère en une commande.

## Ce que ce module ne fait pas

**Il ne reproduit pas le rapprochement approximatif de Cadence.** Cadence tolère la casse,
les pluriels, les graphies collées et traduit le français mot à mot ; réécrire cet
algorithme ici en donnerait une seconde version, qui divergerait au premier cas limite et
afficherait dans Metric une démonstration que l'autre application n'affiche pas. Ce module
sert des noms **exacts** à la saisie ; c'est Cadence qui décide de ce qu'il montre.

La conséquence pratique est bénigne, et elle est dans la spécification : un nom sans
correspondance reste parfaitement valide, la séance se déroule, simplement sans image.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.text import fold

_FILE = Path(__file__).with_name("exercise_catalog.json")

#: Le matériel qu'on peut posséder **sans salle**, dans l'ordre où il se coche.
#:
#: Une partition des 28 valeurs du catalogue et non une liste à part : le réglage
#: « matériel » (**R8**) en montre douze d'emblée et range les seize autres derrière un
#: dépliant, parce qu'une grille de vingt-huit machines pousse hors de vue les trois qu'on
#: possède vraiment.
#:
#: **C'est un choix d'affichage, pas une classification.** Rien ici ne filtre : les
#: seize autres se cochent aussi bien, elles sont simplement un appui plus loin. Se
#: tromper de côté coûte un dépliant ouvert, jamais un exercice inaccessible.
#:
#: Les valeurs sont celles du catalogue, à la lettre — aucune traduction, aucune table de
#: correspondance. `test_common_equipment_exists_in_the_catalog` le vérifie : régénérer
#: `exercise_catalog.json` avec un vocabulaire différent fait tomber ce test au lieu de
#: vider silencieusement la moitié de l'écran.
COMMON_EQUIPMENT: tuple[str, ...] = (
    "body weight",
    "dumbbell",
    "barbell",
    "ez barbell",
    "kettlebell",
    "band",
    "resistance band",
    "medicine ball",
    "stability ball",
    "rope",
    "roller",
    "weighted",
)

#: Plafond de résultats servis en une fois. Le catalogue entier fait une centaine de
#: kilo-octets : le servir à un téléphone pour qu'il le filtre serait le réseau **et** le
#: calcul métier du mauvais côté.
LIMIT = 50


@dataclass(frozen=True)
class CatalogExercise:
    """Un exercice du catalogue de Cadence, tel que le dépôt le fige.

    Le nom est celui qui affiche à coup sûr une démonstration — c'est la seule raison
    d'être de ce catalogue. Zone, matériel et cible servent à composer : « haut du corps »,
    « je n'ai que des haltères ».
    """

    name: str
    body_part: str
    equipment: str
    target: str

    @property
    def bodyweight(self) -> bool:
        """Vrai quand l'exercice se fait sans matériel.

        **Sert à suggérer, jamais à classer.** La page Charges attend une déclaration de
        l'utilisateur (**C3**) : un nom écrit librement ne se rapproche pas de ce catalogue
        avec assez de certitude pour décider à sa place, et une mauvaise classification ne
        se voit pas — elle fait simplement disparaître une carte.
        """
        return self.equipment == "body weight"


@dataclass(frozen=True)
class Catalog:
    """Le catalogue entier, chargé une fois."""

    exercises: tuple[CatalogExercise, ...]
    body_parts: tuple[str, ...]
    equipment: tuple[str, ...]
    targets: tuple[str, ...]


@lru_cache(maxsize=1)
def catalog() -> Catalog:
    """Le catalogue, lu une fois et gardé.

    `lru_cache` et non une constante de module : un fichier de 70 ko lu à l'import
    ralentirait le démarrage de tout ce qui touche au domaine Activité, y compris la
    batterie de tests qui ne s'en sert pas.
    """
    raw = json.loads(_FILE.read_text(encoding="utf-8"))
    body_parts: list[str] = raw["bodyParts"]
    equipment: list[str] = raw["equipment"]
    targets: list[str] = raw["targets"]

    return Catalog(
        exercises=tuple(
            CatalogExercise(
                name=item["n"],
                body_part=body_parts[item["b"]],
                equipment=equipment[item["e"]],
                target=targets[item["t"]],
            )
            for item in raw["exercises"]
        ),
        body_parts=tuple(body_parts),
        equipment=tuple(equipment),
        targets=tuple(targets),
    )


def _squash(folded: str) -> str:
    """Le repli, espaces compris.

    `fold` retire le trait d'union sans le remplacer : « push-up » y devient `pushup`,
    « push up » reste `push up`, et les deux ne se reconnaissent plus. Le catalogue écrit
    les deux formes selon l'exercice — `push-up` et `push up on bosu ball` — donc une
    recherche qui ne fait pas tomber l'espace ne trouve que la moitié de ce qu'on cherche.

    **Ce n'est pas de la similarité** : deux graphies du même mot deviennent comparables,
    deux mots différents restent différents.
    """
    return folded.replace(" ", "")


def _rank(folded_name: str, needle: str) -> int:
    """L'ordre d'un résultat : plus petit, plus haut. `-1` quand il ne correspond pas.

    Trois rangs et pas une note de similarité : un score continu se règle à l'infini et
    n'explique jamais pourquoi un résultat est passé devant l'autre. Ici la règle se dit en
    une phrase — le nom exact d'abord, ce qui commence par la recherche ensuite, ce qui la
    contient enfin.
    """
    if folded_name == needle:
        return 0
    if folded_name.startswith(needle):
        return 1
    return 2 if needle in folded_name else -1


def _best_rank(folded_name: str, needle: str) -> int:
    """Le meilleur des deux rangs — sur le repli, puis sur le repli sans espaces."""
    direct = _rank(folded_name, needle)
    squashed = _rank(_squash(folded_name), _squash(needle))
    ranks = [value for value in (direct, squashed) if value >= 0]
    return min(ranks) if ranks else -1


def search(
    query: str = "",
    *,
    body_part: str | None = None,
    equipment: str | None = None,
    limit: int = LIMIT,
) -> tuple[CatalogExercise, ...]:
    """Les exercices du catalogue qui correspondent, au plus `limit`.

    Une recherche vide rend le début du catalogue filtré, et non rien : c'est ce qui permet
    à « je n'ai que des haltères » d'être une question sans mot-clé.
    """
    needle = fold(query)
    found: list[tuple[int, str, CatalogExercise]] = []

    for exercise in catalog().exercises:
        if body_part is not None and exercise.body_part != body_part:
            continue
        if equipment is not None and exercise.equipment != equipment:
            continue
        rank = _best_rank(fold(exercise.name), needle) if needle else 2
        if rank < 0:
            continue
        found.append((rank, exercise.name, exercise))

    found.sort(key=lambda item: (item[0], item[1]))
    return tuple(exercise for _rank_, _name, exercise in found[:limit])


def equipment_options() -> tuple[tuple[str, bool], ...]:
    """Les 28 matériels, chacun avec « est-il montré d'emblée ? ».

    Servi au client plutôt que recopié chez lui, pour la raison du catalogue de métriques :
    une liste tenue dans deux langages finit par ne plus décrire la même chose — et ici la
    divergence serait muette, puisqu'un matériel absent de l'écran ne se coche simplement
    jamais.

    L'ordre est celui de l'écran : les courants dans l'ordre où ils se cochent, puis les
    autres par ordre alphabétique — c'est un dépliant qu'on parcourt, pas une liste qu'on
    lit.
    """
    known = set(catalog().equipment)
    common = tuple((name, True) for name in COMMON_EQUIPMENT if name in known)
    rest = tuple((name, False) for name in sorted(known - set(COMMON_EQUIPMENT)))
    return common + rest


__all__ = [
    "COMMON_EQUIPMENT",
    "LIMIT",
    "Catalog",
    "CatalogExercise",
    "catalog",
    "equipment_options",
    "search",
]
