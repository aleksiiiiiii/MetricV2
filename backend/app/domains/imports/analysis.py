"""Lecture d'une capture Apple Fitness (`IMP-01`, `IMP-03`, `IMP-06`).

Le partage du travail avec le modèle est délibéré et vaut d'être nommé :

**Le modèle lit, il ne convertit pas.** On lui demande de recopier ce qui est affiché,
unité comprise — `5,20 MI`, `28:45`, `Hier` — et rien d'autre. Un modèle à qui l'on demande
en plus de convertir des miles en kilomètres se trompe d'un facteur mille une fois sur dix,
et l'erreur est invisible : `8,37` est aussi plausible que `5,20`.

**La conversion vit dans `app/core/parsing.py`**, celui-là même qui lit les saisies au
clavier. Les miles, les `28:45` et les décimales à la française y ont **une seule**
grammaire (`ACT-01`) ; en écrire une seconde ici, c'est se garantir deux résultats
différents pour la même chaîne le jour où l'une des deux évolue.

**Ce qui n'est pas lisible reste vide** (`IMP-03`). Aucune valeur par défaut, aucun zéro de
remplissage, aucune date du jour « en attendant ». Un champ vide se remplit au pouce en
deux secondes ; une valeur fausse entrée sans qu'on s'en aperçoive reste dans le fichier
des années, et c'est exactement ce que `STO-02` cherche à éviter.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.parsing import (
    ParseError,
    parse_day,
    parse_decimal,
    parse_distance_km,
    parse_duration_minutes,
)
from app.domains.imports.schemas import AppleDraft

INSTRUCTION = (
    "Tu lis des captures d'écran d'applications de sport. Tu réponds uniquement par un "
    "objet JSON, sans phrase avant ni après, sans bloc de code."
)

#: La consigne. Le point capital est la copie **littérale** : c'est ce qui permet à la
#: conversion de rester chez nous, où elle est testée.
PROMPT = """Lis cette capture d'écran d'une application de sport (Apple Fitness, Apple Watch,
Strava…) et relève les valeurs affichées.

Réponds par cet objet JSON exactement :
{"kind": "run", "activity": "…", "date": "…", "distance": "…", "duration": "…",
 "avg_hr": "…", "elevation_m": "…", "calories": "…", "readable": true}

- "kind" : "run" si l'activité parcourt une distance (course, marche, vélo), sinon "workout".
- "activity" : le nom de l'activité tel qu'affiché ("Course à pied", "Musculation"…).
- "date" : telle qu'affichée ("28/07/2026", "Hier", "Lundi"). Ne la calcule pas.
- "distance" : recopie le nombre ET son unité, exactement ("5,20 MI", "8,37 KM").
- "duration" : recopie telle quelle ("28:45", "1:18:44").
- "avg_hr" : fréquence cardiaque moyenne en battements par minute.
- "elevation_m" : dénivelé positif, en mètres.
- "calories" : kilocalories actives.
- "readable" : false si cette image n'est pas une capture d'activité sportive.

Ne convertis rien, ne calcule rien, ne complète rien : recopie ce qui est écrit.
Mets null sur tout champ absent de la capture."""

#: Bornes de relecture, alignées sur `app/core/validation.py`. Hors de ces bornes, la
#: valeur est **écartée** et le champ reste vide : un modèle qui lit `1852` battements par
#: minute a lu autre chose que la fréquence cardiaque.
_BOUNDS: dict[str, tuple[float, float]] = {
    "avg_hr": (1, 260),
    "elevation_m": (0, 10000),
    "calories": (0, 10000),
}

#: Ordre d'affichage des champs manquants — celui de la capture, pas celui du modèle.
_REPORTED = ("date", "distance_km", "duration_min", "avg_hr", "elevation_m", "calories")


def _text(payload: dict[str, Any], key: str) -> str:
    """Valeur textuelle d'une clé, `""` si elle est absente ou nulle.

    Les modèles rendent `null`, `"null"`, `"—"` ou `"N/A"` pour dire la même chose. Les
    traiter tous comme du vide évite qu'un tiret devienne une distance.
    """
    raw = payload.get(key)
    if raw is None or isinstance(raw, bool):
        return ""
    text = str(raw).strip()
    return "" if text.lower() in {"", "null", "none", "n/a", "na", "-", "—", "--"} else text


def _integer(payload: dict[str, Any], key: str) -> int | None:
    """Entier borné, ou `None`. L'unité collée (`152 bpm`) est tolérée."""
    text = _text(payload, key)
    if not text:
        return None

    cleaned = "".join(char for char in text if char.isdigit() or char in ".,-")
    if not cleaned:
        return None
    try:
        value = parse_decimal(cleaned)
    except ParseError:
        return None

    low, high = _BOUNDS[key]
    return round(value) if low <= value <= high else None


def read_draft(payload: dict[str, Any], *, today: date) -> AppleDraft:
    """Traduit la réponse du modèle en pré-remplissage (`IMP-02`, `IMP-03`).

    `readable` n'est pas relu ici : c'est l'appelant qui décide qu'une capture est
    inexploitable, parce que la règle dépend de ce qu'il en attend (`IMP-06`).
    """
    when = parse_day(_text(payload, "date"), today=today) or None

    distance: float | None = None
    raw_distance = _text(payload, "distance")
    if raw_distance:
        try:
            converted = parse_distance_km(raw_distance)
        except ParseError:
            converted = 0.0
        # Une distance nulle ou aberrante n'est pas une distance. La borne haute est celle
        # de la saisie manuelle : au-delà de 1000 km, le modèle a lu un total annuel.
        distance = round(converted, 3) if 0 < converted <= 1000 else None

    duration: float | None = None
    raw_duration = _text(payload, "duration")
    if raw_duration:
        try:
            minutes = parse_duration_minutes(raw_duration)
        except ParseError:
            minutes = 0.0
        duration = round(minutes, 2) if 0 < minutes <= 1440 else None

    activity = _text(payload, "activity") or None
    kind = "run" if str(payload.get("kind", "")).strip().lower() == "run" else "workout"
    # Une course sans distance ne peut pas s'écrire dans `runs.csv` (`ACT-02` : l'allure
    # n'existe pas sans elle). Plutôt que de proposer un import impossible à valider, on
    # la présente en séance — que l'écran laisse rebasculer en un appui.
    if kind == "run" and distance is None:
        kind = "workout"

    draft = AppleDraft(
        kind=kind,
        date=when,
        workout_type=activity,
        distance_km=distance,
        duration_min=duration,
        avg_hr=_integer(payload, "avg_hr"),
        elevation_m=_integer(payload, "elevation_m"),
        calories=_integer(payload, "calories"),
    )
    draft.missing = [field for field in _REPORTED if getattr(draft, field) is None]
    return draft


def is_unreadable(payload: dict[str, Any], draft: AppleDraft) -> bool:
    """Vrai quand la capture n'a rien donné d'exploitable (`IMP-06`).

    Deux cas, et le second compte autant que le premier : le modèle annonce lui-même qu'il
    ne voit pas d'activité sportive, ou il a répondu poliment sans rien lire. Une capture
    sans durée **et** sans distance ne pré-remplit rien — mieux vaut le dire que d'ouvrir
    un formulaire vide en le présentant comme un import.
    """
    if payload.get("readable") is False:
        return True
    return draft.duration_min is None and draft.distance_km is None
