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
from datetime import date, time, timedelta

from app.core.text import fold

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


#: `2026-07-30`, la forme demandée au modèle et la seule qui n'a pas d'ambiguïté.
_ISO_DAY = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")

#: `30/07/2026`, `30/07`, `30-07`. L'ordre est jour puis mois : une capture d'un appareil
#: réglé en français ne s'écrit pas autrement, et l'inverse serait indécidable au-delà du 12.
_DAY_MONTH = re.compile(r"^(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2}|\d{4}))?$")

#: `il y a 3 jours`, `il y a 1 jour`, une fois les espaces retirés.
_DAYS_AGO = re.compile(r"^ilya(\d+)jours?$")

#: Décalages nommés, tels qu'une capture ou un modèle les écrivent.
_NAMED_OFFSETS: dict[str, int] = {
    "aujourdhui": 0,
    "cejour": 0,
    "hier": 1,
    "avanthier": 2,
}

#: Jours de la semaine, pour « lundi » — qui désigne le lundi **écoulé**, jamais le suivant.
_WEEKDAYS: dict[str, int] = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}

#: Mois écrits en toutes lettres, français et anglais, abréviations comprises.
#:
#: L'anglais n'est pas un luxe : un iPhone réglé en anglais titre « August 21, 2026 », et
#: c'est exactement la forme qu'un modèle recopie quand on lui demande de ne rien
#: convertir. Sans cette table, une capture parfaitement lue rendait une date **vide** —
#: le pire des cas, parce qu'il ressemble à une mauvaise lecture du modèle.
#:
#: Les clés sont déjà repliées — sans accent, sans point : `parse_day` normalise avant de
#: chercher, et « février » doit répondre sous `fevrier`.
_MONTHS: dict[str, int] = {
    "janvier": 1,
    "january": 1,
    "jan": 1,
    "fevrier": 2,
    "february": 2,
    "feb": 2,
    "fev": 2,
    "mars": 3,
    "march": 3,
    "mar": 3,
    "avril": 4,
    "april": 4,
    "avr": 4,
    "apr": 4,
    "mai": 5,
    "may": 5,
    "juin": 6,
    "june": 6,
    "jun": 6,
    "juillet": 7,
    "july": 7,
    "jul": 7,
    "juil": 7,
    "aout": 8,
    "august": 8,
    "aug": 8,
    "septembre": 9,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "octobre": 10,
    "october": 10,
    "oct": 10,
    "novembre": 11,
    "november": 11,
    "nov": 11,
    "decembre": 12,
    "december": 12,
    "dec": 12,
}

#: `august21,2026` et `21aout2026`, une fois les espaces retirés.
#:
#: Les deux ordres coexistent sur le même appareil selon sa langue, et **rien dans la
#: position ne permet de trancher** : c'est le mot qui lève l'ambiguïté, jamais le rang.
#: D'où deux motifs et non un seul avec des groupes optionnels.
_MONTH_FIRST = re.compile(r"^([a-z]+)\.?(\d{1,2}),?(\d{4})?$")
_DAY_FIRST = re.compile(r"^(\d{1,2})([a-z]+)\.?,?(\d{4})?$")

#: `7:40PM`, `19:40`, `7:40:12PM`, une fois les espaces retirés. Les secondes sont
#: tolérées puis oubliées : une borne horaire de séance se lit à la minute, et Apple n'en
#: affiche pas davantage.
_TIME_OF_DAY = re.compile(r"^(\d{1,2}):(\d{2})(?::\d{2})?(am|pm)?$")


def parse_day(raw: str, *, today: date) -> date | None:
    """Date absolue et **non future**, à partir de ce qu'une capture peut porter (`IMP-03`).

    Une capture Apple écrit « Hier », « Lundi », « 30/07 » ou une date complète selon
    l'écran et la langue de l'appareil. Toutes désignent un jour passé : on relève ce qui
    a eu lieu.

    Le repli est `None` — **jamais une date choisie par défaut**. Une date inventée entrerait
    silencieusement dans `runs.csv` et y resterait des années ; un champ vide se remplit en
    deux secondes, et l'écran le montre vide.

    | Saisie           | Rendu, un 30/07/2026 (jeudi)                      |
    |------------------|---------------------------------------------------|
    | `2026-07-28`     | le 28 juillet 2026                                |
    | `hier`           | le 29 juillet 2026                                |
    | `il y a 3 jours` | le 27 juillet 2026                                |
    | `28/07`          | le 28 juillet 2026 — l'année qui n'est pas future |
    | `lundi`          | le lundi écoulé, jamais celui à venir             |
    | `2027-01-01`     | `None` : on ne relève pas ce qui n'a pas eu lieu  |
    """
    text = raw.strip().lower().replace(" ", "").replace(" ", "").replace("'", "").replace("’", "")
    if not text:
        return None

    # Les formes parlées perdent aussi leur trait d'union : « avant-hier » est un mot. Les
    # formes chiffrées le gardent, où il sépare — `28-07-2026`.
    word = text.replace("-", "")

    if word in _NAMED_OFFSETS:
        return today - timedelta(days=_NAMED_OFFSETS[word])

    ago = _DAYS_AGO.match(word)
    if ago:
        return today - timedelta(days=int(ago.group(1)))

    if word in _WEEKDAYS:
        # Distance en arrière jusqu'à ce jour de la semaine. Zéro veut dire aujourd'hui,
        # et c'est bien le sens de « lundi » quand on est lundi.
        back = (today.weekday() - _WEEKDAYS[word]) % 7
        return today - timedelta(days=back)

    iso = _ISO_DAY.match(text)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        return _valid_past_date(year, month, day, today=today)

    partial = _DAY_MONTH.match(text)
    if partial:
        day, month = int(partial.group(1)), int(partial.group(2))
        written_year = partial.group(3)
        if written_year is None:
            # Sans année, on choisit la seule qui ne soit pas future : une sortie du 28/12
            # lue le 3 janvier appartient à l'année précédente.
            for year in (today.year, today.year - 1):
                candidate = _valid_past_date(year, month, day, today=today)
                if candidate is not None:
                    return candidate
            return None
        year = int(written_year)
        if year < 100:
            year += 2000
        return _valid_past_date(year, month, day, today=today)

    return _month_name_date(raw, today=today)


def _month_name_date(raw: str, *, today: date) -> date | None:
    """« August 21, 2026 » et « 21 août 2026 ».

    En **dernier recours**, après les formes chiffrées : celles-ci portent des séparateurs
    (`/`, `-`, `.`) que le repli efface, et les essayer sur du texte replié transformerait
    `28-07-2026` en un nombre de huit chiffres.

    Le repli est celui du projet (`app.core.text.fold`) et non un second : il retire les
    accents, la casse et la ponctuation, ce qui règle d'un coup « août », « Août », le
    point de « sept. » et la virgule de « August 21, 2026 ».
    """
    letters = fold(raw).replace(" ", "")
    if not letters:
        return None

    for pattern, month_first in ((_MONTH_FIRST, True), (_DAY_FIRST, False)):
        found = pattern.match(letters)
        if found is None:
            continue
        name = found.group(1 if month_first else 2)
        number = found.group(2 if month_first else 1)
        month = _MONTHS.get(name)
        if month is None:
            continue

        day = int(number)
        written_year = found.group(3)
        if written_year is not None:
            return _valid_past_date(int(written_year), month, day, today=today)
        # Sans année, la même règle que `28/07` : celle qui ne soit pas future.
        for year in (today.year, today.year - 1):
            candidate = _valid_past_date(year, month, day, today=today)
            if candidate is not None:
                return candidate
        return None

    return None


def parse_clock_time(raw: str) -> time | None:
    """Heure d'horloge d'une capture — `7:40 PM`, `19:40` (`IMP-03`).

    Rend `None` plutôt que de lever : une borne horaire est un **contexte**, pas une
    mesure. Une plage mal lue ne doit pas faire échouer l'import d'une course dont la
    distance et la durée, elles, sont parfaitement lisibles.

    `12 AM` vaut minuit et `12 PM` midi — le cas qui se trompe dans les deux sens quand on
    ajoute douze heures sans y penser.
    """
    # Les espaces fines et insécables s'écrivent en échappement : une capture les porte,
    # et un caractère invisible dans le source se relit mal et se copie encore plus mal.
    text = raw.strip().lower()
    for space in (" ", "\u202f", "\xa0"):
        text = text.replace(space, "")
    if not text:
        return None

    found = _TIME_OF_DAY.match(text)
    if found is None:
        return None

    hours, minutes = int(found.group(1)), int(found.group(2))
    half = found.group(3)
    if half is not None:
        if not 1 <= hours <= 12:
            return None
        hours = hours % 12 + (12 if half == "pm" else 0)

    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return None
    return time(hour=hours, minute=minutes)


def _valid_past_date(year: int, month: int, day: int, *, today: date) -> date | None:
    """Date réelle et passée, ou `None`. Un 31 février n'est pas une date à corriger."""
    try:
        candidate = date(year, month, day)
    except ValueError:
        return None
    return candidate if candidate <= today else None


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
