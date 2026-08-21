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
    parse_clock_time,
    parse_day,
    parse_decimal,
    parse_distance_km,
    parse_duration_minutes,
)
from app.domains.activity.splits import (
    Split,
    mark_partials,
    measure_distances,
    verify,
)
from app.domains.imports.schemas import AppleDraft, SplitDraft

INSTRUCTION = (
    "Tu lis des captures d'écran d'applications de sport. Tu réponds uniquement par un "
    "objet JSON, sans phrase avant ni après, sans bloc de code."
)

#: La consigne. Le point capital est la copie **littérale** : c'est ce qui permet à la
#: conversion de rester chez nous, où elle est testée.
#:
#: Elle a été **étendue** au lot C08 et non réécrite : les paliers, les deux chiffres de
#: calories et les bornes horaires s'ajoutent à ce qui marchait, et la distinction
#: course/séance reste en tête parce que l'écran d'import ne sait pas d'avance laquelle
#: des deux on lui présente.
PROMPT = """Lis ces captures d'écran d'une application de sport (Apple Fitness, Apple Watch,
Strava…) et relève les valeurs affichées. Elles montrent UNE SEULE séance : l'une le
résumé, les autres éventuellement la liste des paliers (« Splits »).

Réponds par un unique objet JSON, sans phrase avant ni après, sans bloc de code :
{"kind": "run", "activity": "…", "date": "…", "start_time": "…", "end_time": "…",
 "distance": "…", "duration": "…", "pace": "…", "cadence_spm": "…", "avg_hr": "…",
 "elevation_m": "…", "calories": "…", "total_calories": "…",
 "split_length": "…", "splits_seen": 0, "splits_contiguous": true,
 "splits": [{"index": 1, "time": "…", "pace": "…", "cadence_spm": "…",
             "avg_hr": "…", "elevation_m": "…", "partial": false}],
 "readable": true}

RÈGLE GÉNÉRALE — recopie, ne calcule pas.
Chaque valeur est recopiée telle qu'elle est affichée, unité comprise : « 8.14 KM »,
« 5'02"/KM », « 0:40:59 », « 439 ». Ne convertis aucune unité, ne déduis aucun champ
d'un autre, n'arrondis rien. Mets null sur tout champ absent des captures.
N'invente jamais une valeur pour compléter une ligne.

LE RÉSUMÉ
- "kind" : "run" si l'activité parcourt une distance (course, marche, vélo), sinon "workout".
- "activity" : le titre affiché ("Outdoor Run", "Course en extérieur", "Musculation").
- "date" : telle qu'affichée ("August 21, 2026", "28/07/2026", "Hier"). Ne la calcule pas.
- "start_time" / "end_time" : les deux bornes horaires si une plage est affichée
  ("7:40 – 8:21 PM" donne "7:40 PM" et "8:21 PM"). Garde AM/PM tel quel.
- "distance" : recopie le nombre ET son unité, exactement ("5,20 MI", "8.14 KM").
- "duration" : le temps de séance ("Workout Time"), pas la plage horaire. Les deux
  diffèrent dès qu'il y a eu une pause. Recopie tel quel ("28:45", "0:40:59").
- "pace" : allure moyenne, recopiée telle quelle ("5:16", "5'02\\"/KM"). Ne la calcule pas.
- "cadence_spm" : cadence moyenne en pas par minute (SPM), le nombre seul.
- "avg_hr" : fréquence cardiaque moyenne en battements par minute.
- "elevation_m" : dénivelé positif, en mètres.
- "calories" et "total_calories" sont DEUX champs distincts : les kilocalories ACTIVES
  et les TOTALES. Si un seul chiffre est affiché sans qualificatif, mets-le dans
  "calories" et laisse "total_calories" à null.

LES PALIERS — le point important
Si aucune capture ne montre de liste de paliers, mets "splits": [] et "splits_seen": 0.
- "split_length" : l'en-tête de la liste, recopié ("1 Kilometer", "1 Mile").
- "splits" : UNE entrée par ligne visible, dans l'ordre affiché.
- "index" : le numéro écrit sur la ligne. Lis-le, ne le recompte pas : une capture peut
  être défilée et commencer au palier 7.
- "time", "pace", "cadence_spm", "avg_hr", "elevation_m" : les colonnes présentes. Toute
  colonne absente de la capture vaut null pour toutes les lignes.
- "partial" : true UNIQUEMENT pour une ligne dont le temps est nettement plus court que
  les autres — typiquement la dernière, qui est le reliquat de distance et NON un palier
  entier. Exemple : huit lignes autour de 05:00 et une dernière à 00:44 : cette dernière
  porte partial true, les huit autres partial false. L'allure affichée sur une ligne
  partielle est une extrapolation de l'application, pas une mesure : recopie-la quand
  même, le drapeau dit comment la lire.
- "splits_seen" : le nombre de lignes que tu as effectivement relevées.
- "splits_contiguous" : true si les index vont de 1 à splits_seen sans trou. false si une
  capture manque au milieu ou si la liste ne commence pas à 1.

PLUSIEURS IMAGES
Fusionne-les en une seule liste. Si un même index apparaît sur deux captures qui se
recouvrent, garde-le une seule fois. Ne complète jamais un index que tu n'as pas vu.

- "readable" : false si ces images ne sont pas des captures d'activité sportive.

Ne convertis rien, ne calcule rien, ne complète rien : recopie ce qui est écrit.
Mets null sur tout champ absent des captures."""

#: Bornes de relecture, alignées sur `app/core/validation.py`. Hors de ces bornes, la
#: valeur est **écartée** et le champ reste vide : un modèle qui lit `1852` battements par
#: minute a lu autre chose que la fréquence cardiaque.
_BOUNDS: dict[str, tuple[float, float]] = {
    "avg_hr": (1, 260),
    "elevation_m": (0, 10000),
    "calories": (0, 10000),
    "total_calories": (0, 10000),
    "cadence_spm": (30, 300),
}

#: Durée plausible d'un palier, en secondes. La borne basse écarte un `00:00` lu de
#: travers ; la haute laisse passer un kilomètre de marche en côte sans laisser passer un
#: temps total pris pour un palier.
_SPLIT_SECONDS = (1.0, 3600.0)

#: Plafond du nombre de paliers relevés. Un modèle qui en rend trois cents a bouclé sur
#: lui-même — cela arrive, et la liste entière est alors sans valeur.
MAX_SPLITS = 200

#: Ordre d'affichage des champs manquants — celui de la capture, pas celui du modèle.
_REPORTED = (
    "date",
    "distance_km",
    "duration_min",
    "pace_min_km",
    "cadence_spm",
    "avg_hr",
    "elevation_m",
    "calories",
)


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


def _duration_field(payload: dict[str, Any], key: str) -> float | None:
    """Une durée recopiée, en minutes. `None` si elle est absente ou illisible."""
    raw = _text(payload, key)
    if not raw:
        return None
    try:
        minutes = parse_duration_minutes(raw)
    except ParseError:
        return None
    return minutes if 0 < minutes <= 1440 else None


def _pace_field(payload: dict[str, Any], key: str) -> float | None:
    """Une allure recopiée, en minutes par kilomètre.

    L'allure se lit **comme une durée** — `5'02"` vaut 5 min 2 s par kilomètre — après
    avoir ramené les apostrophes et le suffixe d'unité à ce que l'analyseur de durée sait
    lire. Un second analyseur pour la même écriture divergerait du premier au cas limite.
    """
    raw = _text(payload, key)
    if not raw:
        return None

    cleaned = raw.replace("’", ":").replace("'", ":").replace('"', "").strip()
    # « 5:02/KM », « 5:02 /km » : le dénominateur est écrit sur la capture et n'ajoute
    # rien — l'unité de la colonne est déjà connue.
    lowered = cleaned.lower()
    for suffix in ("/km", "/mi", "perkm", "km", "mi"):
        if lowered.endswith(suffix):
            cleaned = cleaned[: len(cleaned) - len(suffix)].strip().rstrip("/")
            break

    try:
        minutes = parse_duration_minutes(cleaned)
    except ParseError:
        return None
    return round(minutes, 3) if 1 < minutes <= 60 else None


def read_splits(payload: dict[str, Any]) -> tuple[list[Split], bool]:
    """Les paliers relevés par le modèle, et s'ils se suivent (`ACT-19`).

    Ce que cette fonction **ne fait pas** mérite d'être dit, parce que c'est tout le
    partage du travail du module : elle ne décide pas quel palier est un reliquat, ne
    calcule aucune distance, et ne juge pas la vraisemblance de l'ensemble. Elle lit.

    Le drapeau `partial` du modèle est **ignoré** : il est redemandé dans la consigne parce
    que le faire nommer améliore la lecture du reste, mais celui qui compte se déduit des
    durées dans `activity/splits.py`. Un modèle qui qualifie son propre travail rend un
    verdict aussi faux que son extraction.

    Une ligne sans durée lisible est **écartée** plutôt que comblée : c'est la durée qui
    porte tout — le reliquat s'y voit, la somme s'y contrôle — et une ligne sans elle
    n'est pas un palier incomplet, c'est du bruit.
    """
    raw = payload.get("splits")
    if not isinstance(raw, list):
        return [], True

    found: list[Split] = []
    for entry in raw[:MAX_SPLITS]:
        if not isinstance(entry, dict):
            continue

        minutes = _duration_field(entry, "time")
        if minutes is None:
            continue
        seconds = round(minutes * 60, 1)
        low, high = _SPLIT_SECONDS
        if not low <= seconds <= high:
            continue

        index = _integer_unbounded(entry, "index")
        if index is None or not 1 <= index <= MAX_SPLITS:
            continue

        found.append(
            Split(
                index=index,
                duration_s=seconds,
                pace_min_km=_pace_field(entry, "pace"),
                cadence_spm=_integer(entry, "cadence_spm"),
                avg_hr=_integer(entry, "avg_hr"),
                elevation_m=_integer(entry, "elevation_m"),
            )
        )

    # Un même index rendu deux fois vient de deux captures qui se recouvrent : la consigne
    # demande de le fusionner, et le premier relevé fait foi quand il ne l'a pas été.
    unique: dict[int, Split] = {}
    for split in found:
        unique.setdefault(split.index, split)
    ordered = sorted(unique.values(), key=lambda split: split.index)

    # La contiguïté se **constate**, elle ne se croit pas : le champ que rend le modèle
    # dirait « true » sur une liste qui saute le quatrième palier. Les index doivent aller
    # de 1 à n sans trou, ce qui est vérifiable sans rien connaître de la course.
    contiguous = [split.index for split in ordered] == list(range(1, len(ordered) + 1))
    return ordered, contiguous


def _integer_unbounded(payload: dict[str, Any], key: str) -> int | None:
    """Entier sans borne de vraisemblance — pour un numéro de ligne, qui n'en a pas."""
    text = _text(payload, key)
    if not text:
        return None
    cleaned = "".join(char for char in text if char.isdigit())
    return int(cleaned) if cleaned else None


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

    # L'allure se lit **comme une durée** — `5:16` vaut 5 min 16 s par kilomètre. Un
    # second analyseur pour la même écriture divergerait du premier au cas limite.
    pace = _pace_field(payload, "pace")

    activity = _text(payload, "activity") or None
    kind = "run" if str(payload.get("kind", "")).strip().lower() == "run" else "workout"
    # Une course a besoin de sa distance **ou** de son allure : le serveur calcule l'une
    # depuis l'autre. Sans ni l'une ni l'autre elle ne peut pas s'écrire dans `runs.csv`,
    # et on la présente en séance — que l'écran laisse rebasculer en un appui.
    if kind == "run" and distance is None and pace is None:
        kind = "workout"

    # La longueur d'un palier arrive écrite (« 1 Kilometer », « 1 Mile ») : c'est une
    # distance, et elle se lit par l'analyseur de distances — celui-là même qui convertit
    # les miles, ce qui règle « 1 Mile » sans une ligne de plus.
    length: float | None = None
    raw_length = _text(payload, "split_length")
    if raw_length:
        try:
            converted = parse_distance_km(raw_length)
        except ParseError:
            converted = 0.0
        length = round(converted, 3) if 0 < converted <= 100 else None

    read, contiguous = read_splits(payload)
    marked = mark_partials(read)
    measured = measure_distances(marked, split_length_km=length, total_distance_km=distance)
    verdict = verify(measured, duration_min=duration, distance_km=distance, contiguous=contiguous)

    draft = AppleDraft(
        kind=kind,
        date=when,
        workout_type=activity,
        distance_km=distance,
        duration_min=duration,
        pace_min_km=pace,
        cadence_spm=_integer(payload, "cadence_spm"),
        avg_hr=_integer(payload, "avg_hr"),
        elevation_m=_integer(payload, "elevation_m"),
        calories=_integer(payload, "calories"),
        total_calories=_integer(payload, "total_calories"),
        start_time=parse_clock_time(_text(payload, "start_time")),
        end_time=parse_clock_time(_text(payload, "end_time")),
        split_length_km=length,
        splits=[
            SplitDraft(
                index=item.index,
                duration_s=item.duration_s,
                distance_km=item.distance_km,
                pace_min_km=item.pace_min_km,
                cadence_spm=item.cadence_spm,
                avg_hr=item.avg_hr,
                elevation_m=item.elevation_m,
                partial=item.partial,
            )
            for item in measured
        ],
        splits_trusted=verdict.trusted,
        splits_doubts=list(verdict.reasons),
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
    return draft.duration_min is None and draft.distance_km is None and draft.pace_min_km is None
