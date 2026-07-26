"""Analyse de saisies humaines (`ACT-01`, `IMP-03`).

Une durée se tape de cinq façons selon l'humeur et l'appareil : `44:12`, `1:18:44`, `44`,
`44,5`, `44.5`. Les refuser toutes sauf une ferait perdre plus de temps à la saisie que
le relevé n'en vaut — et la saisie en un geste est la cible du projet.

Ce module est volontairement placé dans le socle et non dans le domaine Activité :
l'import de captures Apple (`IMP-03`) doit normaliser exactement les mêmes formats, et
deux analyseurs finiraient par diverger.
"""

from __future__ import annotations

import re

#: `44:12` ou `1:18:44`, avec ou sans espaces.
_CLOCK = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:[.,]\d+)?)$")

#: `1h30`, `1 h 30`, `90min`, `2h`.
_HUMAN = re.compile(r"^(?:(\d+)\s*h)?\s*(?:(\d+)\s*(?:min|m)?)?$", re.IGNORECASE)

#: Unités de distance acceptées à la saisie.
_MILES_PER_KM = 1.609344


class ParseError(ValueError):
    """Saisie inintelligible. Le message est destiné à l'utilisateur."""


def parse_decimal(raw: str | float | int) -> float:
    """Nombre décimal, virgule française acceptée.

    `8,40` et `8.40` désignent la même distance : refuser la virgule reviendrait à
    demander à un francophone de taper contre son clavier.
    """
    if isinstance(raw, (int, float)):
        return float(raw)

    text = raw.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not text:
        raise ParseError("valeur vide")
    try:
        return float(text)
    except ValueError as exc:
        raise ParseError(f"« {raw} » n'est pas un nombre") from exc


def parse_duration_minutes(raw: str | float | int) -> float:
    """Durée en minutes décimales, quel que soit le format saisi.

    Accepté :

    | Saisie      | Minutes | Lecture                        |
    |-------------|---------|--------------------------------|
    | `44:12`     | 44,2    | minutes et secondes            |
    | `1:18:44`   | 78,73   | heures, minutes, secondes      |
    | `44`        | 44      | minutes seules                 |
    | `44,5`      | 44,5    | minutes décimales              |
    | `1h30`      | 90      | forme parlée                   |

    Le choix de trancher `44:12` en « 44 min 12 s » plutôt qu'en « 44 h 12 » suit l'usage
    du domaine : une séance dépasse rarement la journée, et la charte elle-même écrit
    `44:12` pour une sortie de trois quarts d'heure.
    """
    if isinstance(raw, (int, float)):
        return float(raw)

    text = raw.strip().lower().replace(" ", "").replace(" ", "")
    if not text:
        raise ParseError("durée vide")

    clock = _CLOCK.match(text)
    if clock:
        hours, minutes, seconds = clock.groups()
        return (int(hours) * 60 if hours else 0) + int(minutes) + parse_decimal(seconds) / 60

    if "h" in text:
        human = _HUMAN.match(text)
        if human and any(human.groups()):
            hours, minutes = human.groups()
            return (int(hours) * 60 if hours else 0) + (int(minutes) if minutes else 0)
        raise ParseError(f"« {raw} » n'est pas une durée")

    # Minutes seules, éventuellement suffixées.
    return parse_decimal(text.removesuffix("min").removesuffix("m"))


def parse_distance_km(raw: str | float | int) -> float:
    """Distance en kilomètres, miles convertis (`IMP-03`).

    Les captures Apple d'un appareil réglé en impérial arrivent en miles ; les convertir
    à la saisie évite de stocker deux unités dans la même colonne.
    """
    if isinstance(raw, (int, float)):
        return float(raw)

    text = raw.strip().lower().replace(" ", "")
    for suffix in ("miles", "mile", "mi"):
        if text.endswith(suffix):
            return parse_decimal(text.removesuffix(suffix)) * _MILES_PER_KM
    return parse_decimal(text.removesuffix("km"))


def format_duration(minutes: float) -> str:
    """Inverse de `parse_duration_minutes`, pour un aperçu à la volée.

    Même règle que le frontend : trois segments au-delà de l'heure.
    """
    total = round(minutes * 60)
    hours, remainder = divmod(total, 3600)
    mins, secs = divmod(remainder, 60)
    return f"{hours}:{mins:02d}:{secs:02d}" if hours else f"{mins}:{secs:02d}"


def pace_min_per_km(distance_km: float, minutes: float) -> float | None:
    """Allure en minutes par kilomètre (`ACT-02`).

    `None` quand elle n'a pas de sens — une séance de musculation n'a pas d'allure.
    """
    if distance_km <= 0 or minutes <= 0:
        return None
    return minutes / distance_km


def estimate_one_rep_max(weight_kg: float, reps: int) -> float | None:
    """1RM estimé par la formule d'Epley (`ACT-15`).

        1RM = charge × (1 + réps / 30)

    `None` au poids du corps : sans charge, la formule ne dit rien. Au-delà d'une
    dizaine de répétitions l'estimation dérive — c'est une limite connue d'Epley, pas un
    défaut d'implémentation, et on la laisse plutôt que d'inventer un plafond.
    """
    if weight_kg <= 0 or reps <= 0:
        return None
    return weight_kg * (1 + reps / 30)
