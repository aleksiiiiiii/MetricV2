"""Composition assistée d'un circuit — `/activite/creer` (`docs/refonte-activite.md` §5).

Module **pur**, comme `generation.py` du planning et `circuit_link.py` d'à côté : aucun
fichier, aucun modèle, ni pydantic ni FastAPI. Ce qui décide se teste sur des valeurs
fixes.

Le partage du travail est celui du dépôt, et il n'est pas négociable : **le modèle
propose, le serveur relit, l'utilisateur ajuste, l'appui écrit.** Ce module tient les deux
premiers tiers.

## Ce qu'on demande au modèle, et ce qu'on ne lui demande pas

On lui demande un **jugement** — quels mouvements, dans quel ordre, combien de rounds pour
tenir trente minutes — parce que c'est ce qu'il fait mieux qu'une règle écrite à la main.

On ne lui demande pas de **connaître le catalogue** : les noms exacts lui sont donnés,
filtrés sur le matériel possédé (**R8**). Un modèle à qui l'on dit « propose des exercices
de biceps » invente des intitulés plausibles — *Standing Dumbbell Bicep Curls* — que
Cadence n'affiche pas, et la faute est silencieuse : la séance se déroule, sans image.

On ne lui demande pas non plus d'**assembler un lien** (**D7**). Il nomme des exercices ;
l'URL est fabriquée par le serveur à la lecture du circuit, une fois enregistré.

## Ce que la relecture protège

**Le nom hors catalogue n'est pas écarté, il est signalé.** C'est écrit dans la
spécification de Cadence : un nom sans correspondance reste valide, la séance tourne,
simplement sans démonstration. L'écarter coûterait un exercice pour un défaut d'affichage ;
le taire laisserait croire à une illustration qui n'arrivera pas.

**Les nombres sont ramenés dans les bornes, ils ne sont pas rejetés.** C'est ce que fait
l'application cible — `circuit_link.normalise` porte déjà cette règle — et écarter ici
produirait un comportement que Cadence contredirait à l'ouverture du lien.

**Un exercice sans nom est écarté**, lui, et se dit : c'est la seule colonne dont rien ne
peut tenir lieu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domains.activity import circuit_link, exercise_catalog

#: Groupes musculaires acceptés, dans l'ordre où la consigne les présente. Recopiés depuis
#: l'énumération à l'appel, jamais écrits en dur ici — c'est la leçon de `plan.add` : la
#: description que le modèle lit doit venir de la même source que la validation.
MAX_NAME = 80

#: Plafond d'exercices retenus. Douze mouvements à quatre rounds font déjà quarante-huit
#: passages : au-delà, le modèle a compris autre chose que « une séance ».
MAX_EXERCISES = 12

#: Noms du catalogue montrés au modèle, par zone du corps. Dix par zone sur les dix zones
#: font une centaine de lignes — assez pour qu'il reconnaisse ce qui existe, assez peu pour
#: que la consigne reste lisible et que l'appel tienne dans un modèle gratuit.
NAMES_PER_PART = 10

#: Repli quand le modèle n'a rendu ni répétitions ni durée.
#:
#: La durée par défaut du domaine, celle que `_to_rows` écrit déjà. Ce n'est pas une valeur
#: inventée au sens de l'invariant : elle arrive **marquée comme proposée** dans un champ
#: qui s'ajuste, sur une page dont c'est toute la raison d'être. Écarter l'exercice
#: coûterait plus — un mouvement perdu pour un champ oublié.
DEFAULT_DURATION_S = circuit_link.DEFAULT_DURATION_S

INSTRUCTION = (
    "Tu es un préparateur physique. Tu réponds uniquement par un objet JSON, "
    "sans phrase avant ni après, sans bloc de code."
)

_TEMPLATE = """Compose une séance de tabata.

## Ce qui est demandé

{demande}

## Matériel disponible

{materiel}

## Groupes musculaires — utilise **exactement** une de ces valeurs

{groupes}

## Ancienneté de sollicitation

{negliges}

## Noms d'exercices reconnus par Cadence — recopie-les **exactement**

{noms}

Un nom absent de cette liste reste utilisable, mais il n'affichera aucune démonstration
pendant l'effort. Préfère toujours un nom de la liste quand il existe.
{contraintes}
## Réponse attendue

{{"name": "Bras — 30 min", "rounds": 4, "round_rest_s": 60, "exercises": [
  {{"name": "Dumbbell Bicep Curl", "muscle_group": "biceps", "reps": 12, "rest_s": 20}},
  {{"name": "Plank", "muscle_group": "abdos", "duration_s": 40, "rest_s": 20}}
]}}

Par exercice : **soit** `reps`, **soit** `duration_s`, jamais les deux. `rest_s` est le
repos qui suit l'exercice, en secondes. `round_rest_s` est le repos entre deux rounds.
Le titre de la séance est en français ; les noms d'exercices en anglais."""


@dataclass(frozen=True, slots=True)
class ProposedExercise:
    """Un exercice proposé, déjà relu et borné."""

    name: str
    muscle_group: str
    duration_s: int | None
    reps: int | None
    rest_s: int
    #: Vrai quand le nom est **exactement** celui d'un exercice du catalogue Cadence, donc
    #: quand une démonstration s'affichera pendant l'effort. Faux n'est pas une erreur :
    #: c'est ce que l'écran dit à l'utilisateur, pour qu'il choisisse de corriger ou non.
    illustrated: bool


@dataclass(frozen=True, slots=True)
class ProposedCircuit:
    """Un circuit proposé. **Rien n'est écrit** : c'est l'appui qui écrit."""

    name: str
    rounds: int
    round_rest_s: int
    exercises: tuple[ProposedExercise, ...]


def build_prompt(
    *,
    demande: str,
    materiel: list[str],
    groupes: list[str],
    negliges: list[str],
    contraintes: str,
) -> str:
    """La consigne, avec ce que l'application sait déjà de l'utilisateur.

    **Le matériel et les groupes négligés partent sans qu'on ait à les taper** (§5 bis).
    C'est ce qui rend « fais-moi 30 minutes » répondable : sans eux, la même phrase
    obtient un développé couché de qui n'a ni banc ni barre.
    """
    return _TEMPLATE.format(
        demande=demande.strip() or "Une séance de tabata, à toi de voir.",
        materiel=_liste(materiel)
        if materiel
        else "Non renseigné — reste sur des exercices au poids du corps.",
        groupes=_liste(groupes),
        negliges=_liste(negliges) if negliges else "Aucun historique.",
        noms=_catalogue(materiel),
        contraintes=f"\n## Contraintes à respecter\n\n{contraintes.strip()}\n"
        if contraintes.strip()
        else "",
    )


def _liste(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values)


def _catalogue(materiel: list[str]) -> str:
    """Les noms du catalogue, par zone, filtrés sur le matériel possédé.

    Le poids du corps est **toujours** joint : il porte 325 des 1324 exercices, et
    l'omettre viderait la proposition de sa moitié la plus utile pour qui n'a coché qu'un
    haltère. Sans matériel déclaré, aucun filtre — « on ne sait pas » n'est pas « rien ».

    ## Les plus courts d'abord, et ce n'est pas arbitraire

    Dix noms par zone sur deux cents, il faut choisir lesquels. L'ordre alphabétique donne
    « back pec stretch » et « bodyweight squatting row (with towel) » : des variantes, et
    les variantes sont exactement ce qu'un modèle ne sait pas départager. Dans ce
    catalogue, **un nom long est une variante d'un nom court** — `push-up` porte le
    mouvement, `chest tap push-up (male)` en porte une déclinaison. Trier par longueur
    remonte donc les mouvements de base, qui sont ceux qu'on veut dans un tabata.

    À longueur égale, l'ordre alphabétique : la consigne doit être identique d'un appel à
    l'autre, sinon le cache de préfixe du modèle se casse pour rien.
    """
    faisable = {*materiel, "body weight"} if materiel else None
    par_zone: dict[str, list[str]] = {}

    for item in exercise_catalog.catalog().exercises:
        if faisable is not None and item.equipment not in faisable:
            continue
        par_zone.setdefault(item.body_part, []).append(item.name)

    lignes: list[str] = []
    for part in exercise_catalog.catalog().body_parts:
        found = sorted(par_zone.get(part, []), key=lambda name: (len(name), name))
        if found:
            lignes.append(f"**{part}** — {', '.join(found[:NAMES_PER_PART])}")

    return "\n".join(lignes)


def read_proposal(
    payload: dict[str, Any], *, groups: set[str], fallback_group: str
) -> tuple[ProposedCircuit | None, list[str]]:
    """La réponse du modèle → un circuit relu, et ce qui a été écarté.

    Rend `None` quand il ne reste aucun exercice : la chaîne a fonctionné, la réponse ne
    contient rien qu'on puisse afficher. C'est à l'appelant d'en faire un refus qui porte
    un code, comme le planning le fait.
    """
    raw = payload.get("exercises")
    entries = raw if isinstance(raw, list) else []

    exercises: list[ProposedExercise] = []
    dropped: list[str] = []

    for index, entry in enumerate(entries[: MAX_EXERCISES + 4], start=1):
        if len(exercises) >= MAX_EXERCISES:
            dropped.append(f"exercice {index} : au-delà de {MAX_EXERCISES}, non retenu")
            continue
        if not isinstance(entry, dict):
            dropped.append(f"exercice {index} : illisible")
            continue

        name = str(entry.get("name") or "").strip()[:MAX_NAME]
        if not name:
            # La seule colonne dont rien ne peut tenir lieu : un exercice sans nom
            # n'affiche rien, ne se corrige pas, et ne dit pas ce qu'il était.
            dropped.append(f"exercice {index} : sans nom")
            continue

        group = str(entry.get("muscle_group") or "").strip().lower()
        exercises.append(
            ProposedExercise(
                name=name,
                # Un groupe hors liste ne coûte pas l'exercice : c'est un champ que l'écran
                # affiche **proposé et ajustable** (§5), et « autre » s'y voit comme un
                # champ à corriger. L'écarter perdrait un mouvement pour une étiquette.
                muscle_group=group if group in groups else fallback_group,
                **_length(entry),
                rest_s=_bounded(entry.get("rest_s"), circuit_link.REST_S[1], default=0),
                illustrated=_illustrated(name),
            )
        )

    if not exercises:
        return None, dropped

    return (
        ProposedCircuit(
            name=str(payload.get("name") or "").strip()[:MAX_NAME] or "Séance de tabata",
            rounds=_bounded(
                payload.get("rounds"),
                circuit_link.ROUNDS[1],
                default=1,
                floor=circuit_link.ROUNDS[0],
            ),
            round_rest_s=_bounded(
                payload.get("round_rest_s"), circuit_link.ROUND_REST_S[1], default=0
            ),
            exercises=tuple(exercises),
        ),
        dropped,
    )


def _length(entry: dict[str, Any]) -> dict[str, int | None]:
    """Répétitions **ou** durée, jamais les deux.

    `reps` l'emporte quand le modèle rend les deux : c'est la règle du domaine, écrite sur
    `CircuitExerciseRow` — « `reps` fait autorité, `duration_s` est subordonnée ». Une
    seconde règle ici trancherait autrement le jour où le cas arrive.
    """
    reps = _optional(entry.get("reps"), circuit_link.REPS[1])
    if reps is not None:
        return {"reps": reps, "duration_s": None}

    duration = _optional(entry.get("duration_s"), circuit_link.DURATION_S[1])
    return {"reps": None, "duration_s": duration if duration is not None else DEFAULT_DURATION_S}


def _optional(value: Any, ceiling: int) -> int | None:
    """Un entier borné, ou `None` quand la cellule n'en porte pas un."""
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return None if number <= 0 else min(number, ceiling)


def _bounded(value: Any, ceiling: int, *, default: int, floor: int = 0) -> int:
    """Un entier **ramené** dans les bornes, jamais rejeté.

    C'est ce que fait l'application cible : `circuit_link.normalise` borne déjà rounds et
    repos au moment de fabriquer le lien. Écarter ici produirait un refus que Cadence
    contredirait à l'ouverture, et l'utilisateur verrait deux applications se disputer.
    """
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(floor, min(number, ceiling))


def _illustrated(name: str) -> bool:
    """Vrai quand le catalogue porte **exactement** ce nom.

    Exact et non approximatif : reproduire le rapprochement de Cadence en donnerait une
    seconde version, qui divergerait au premier cas limite et promettrait une image que
    l'autre application n'affiche pas. On confirme une orthographe, on n'en devine pas une.
    """
    from app.core.text import fold

    return any(fold(item.name) == fold(name) for item in exercise_catalog.catalog().exercises)


__all__ = [
    "DEFAULT_DURATION_S",
    "INSTRUCTION",
    "MAX_EXERCISES",
    "ProposedCircuit",
    "ProposedExercise",
    "build_prompt",
    "read_proposal",
]
