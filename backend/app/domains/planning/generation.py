"""Génération assistée d'un planning (`PLAN-03`).

Le partage du travail avec le modèle est le même qu'à l'import Apple, et il n'est pas
négociable : **le modèle propose, le serveur relit**.

Ce qu'on lui demande est un jugement — quels jours, quelle alternance, combien de
récupération — parce que c'est ce qu'il fait mieux qu'une règle écrite à la main. Ce qu'on
ne lui demande pas, c'est de connaître le calendrier : les dates de la fenêtre lui sont
**données**, en clair, jour par jour. Un modèle à qui l'on demande « la semaine prochaine »
répond parfois avec les dates de l'an dernier, et une séance planifiée le 5 août 2025 ne
se voit nulle part — elle se découvre six mois plus tard dans le fichier.

Trois relectures suivent la réponse, et chacune protège quelque chose de différent :

**Hors fenêtre, on écarte.** Pas de correction, pas de recalage sur le lundi le plus
proche : une date qu'on rectifie est une date qu'on a inventée. C'est « hors bornes, on
écarte ; on ne ramène pas à la borne » du lot L12, appliqué au temps.

**Une séance déjà prévue ne se propose pas deux fois** (`PLAN-03`). Le modèle reçoit
pourtant la liste de l'existant : on le lui dit *et* on le vérifie, parce qu'une consigne
suivie neuf fois sur dix produit un doublon par semaine.

**Ce qui est écarté se dit.** Une proposition amputée en silence laisserait croire que le
modèle n'a suggéré que cela, et rendrait incompréhensible une semaine à deux séances quand
on en attendait quatre.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.core.parsing import ParseError, parse_duration_minutes
from app.domains.planning.ical import KIND_LABELS
from app.domains.planning.models import DEFAULT_KIND, KINDS, normalise_kind
from app.domains.planning.schemas import ProposedSession

#: Bornes de relecture d'une durée.
#:
#: La borne haute est celle de la saisie (`DurationMin`). La borne basse, elle, est
#: **plus sévère**, et pour une raison précise : la grammaire du projet lit `1:00` comme
#: une minute — c'est du `mm:ss`, celui qui fait de `28:45` vingt-huit minutes trois
#: quarts (`ACT-01`). Un modèle qui écrit `1:00` en pensant « une heure » produirait donc
#: une séance d'une minute, silencieusement fausse d'un facteur soixante.
#:
#: On ne corrige pas — il faudrait deviner l'intention — et on n'écrit pas une seconde
#: grammaire. On écarte : cinq minutes n'est pas une séance d'entraînement, quelle que
#: soit la façon dont le nombre est arrivé là. C'est « hors bornes, on écarte ; on ne
#: ramène pas à la borne », et cela rend inoffensive la seule ambiguïté du format.
MIN_DURATION = 5.0
MAX_DURATION = 1440.0

#: Plafond de séances retenues. Deux semaines à sept jours ; au-delà, le modèle a compris
#: autre chose que ce qu'on lui demandait.
MAX_SESSIONS = 14

#: Longueurs maximales des textes rendus, alignées sur `Note` et `Label`.
MAX_TITLE = 80
MAX_NOTE = 500

INSTRUCTION = (
    "Tu es un préparateur physique. Tu réponds uniquement par un objet JSON, "
    "sans phrase avant ni après, sans bloc de code."
)

_TEMPLATE = """Construis un planning d'entraînement.

## Jours à remplir

{calendar}

N'utilise aucune autre date. Recopie-les exactement telles qu'elles sont écrites.

## Ce qui a été fait récemment

{history}

## Groupes musculaires

{muscles}

## Déjà prévu sur la période — ne le propose pas une seconde fois

{existing}

{objective}{constraints}
## Réponse attendue

{{"sessions": [
  {{"date": "AAAA-MM-JJ", "time": "18:30", "kind": "muscu", "title": "Haut du corps",
   "duration_min": 60, "note": "…", "reason": "…"}}
]}}

- "kind" vaut "course", "muscu" ou "autre". Rien d'autre.
- "time" est facultatif : mets null si l'heure n'a pas d'importance.
- "duration_min" est un nombre de minutes.
- "title" dit ce qu'on fait ce jour-là, en trois mots ("Haut du corps", "Sortie longue").
- "reason" dit pourquoi ce jour et pas un autre, en une phrase courte.

Règles :
- Reste sur la fréquence hebdomadaire constatée ci-dessus, à une séance près.
- Alterne les groupes musculaires et laisse au moins un jour entre deux séances qui
  sollicitent les mêmes.
- Prévois au moins un jour de repos complet par semaine.
- Ne planifie rien un jour qui porte déjà une séance de même nature.
"""


def _calendar(start: dt.date, end: dt.date) -> str:
    """Les jours de la fenêtre, écrits en toutes lettres.

    C'est la partie de la consigne qui coûte le plus de jetons et qui en vaut le plus :
    un modèle n'a pas de calendrier, il a des habitudes typographiques. Lui donner
    « lundi 10 août 2026 → 2026-08-10 » supprime d'un coup les décalages d'un jour, les
    années fausses et les semaines qui commencent le dimanche.
    """
    jours = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
    lines = []
    day = start
    while day <= end:
        lines.append(f"- {jours[day.weekday()]} : {day.isoformat()}")
        day += dt.timedelta(days=1)
    return "\n".join(lines)


def build_prompt(
    *,
    start: dt.date,
    end: dt.date,
    history: list[str],
    muscles: list[str],
    existing: list[str],
    objective: str = "",
    constraints: str = "",
) -> str:
    """Assemble la consigne. Aucun fichier n'est envoyé au modèle, seulement des résumés.

    Même règle qu'à `GOAL-02` : un condensé factuel, jamais les fichiers entiers. Ce qui
    part d'ici tient en trente lignes et ne contient ni note personnelle, ni poids, ni
    photo.
    """
    return _TEMPLATE.format(
        calendar=_calendar(start, end),
        history="\n".join(f"- {line}" for line in history) or "- Aucun historique.",
        muscles="\n".join(f"- {line}" for line in muscles) or "- Aucune séance de musculation.",
        existing="\n".join(f"- {line}" for line in existing) or "- Rien de prévu.",
        objective=f"## Objectif en cours\n\n{objective.strip()}\n\n" if objective.strip() else "",
        constraints=(f"## Contraintes\n\n{constraints.strip()}\n\n" if constraints.strip() else ""),
    )


def _text(raw: object) -> str:
    """Valeur textuelle, `""` pour tout ce qui veut dire « rien ».

    Les modèles rendent `null`, `"null"`, `"—"` ou `"N/A"` pour la même chose. Reprise
    telle quelle de la relecture d'import, où elle a évité qu'un tiret devienne une
    distance.
    """
    if raw is None or isinstance(raw, bool):
        return ""
    text = str(raw).strip()
    return "" if text.lower() in {"", "null", "none", "n/a", "na", "-", "—", "--"} else text


def _read_time(raw: object) -> str | None:
    """`HH:MM` ou rien. Une heure illisible coûte l'heure, jamais la séance."""
    text = _text(raw)
    if not text:
        return None
    hours, sep, minutes = text.partition(":")
    if not sep or not hours.isdigit() or not minutes.isdigit():
        return None
    if not (0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
        return None
    return f"{int(hours):02d}:{int(minutes):02d}"


def _read_duration(raw: object) -> float | None:
    """Durée en minutes, bornée. `None` si elle n'est pas exploitable.

    La grammaire est celle de `app/core/parsing.py`, la même que pour une saisie au
    clavier : un modèle qui écrit `1:00` ou `1h` veut dire soixante minutes, et en écrire
    une seconde lecture ici garantirait deux résultats divergents un jour.
    """
    text = _text(raw)
    if not text:
        return None
    try:
        minutes = parse_duration_minutes(text)
    except ParseError:
        return None
    return round(minutes, 2) if MIN_DURATION <= minutes <= MAX_DURATION else None


def _label(day: dt.date, kind: str) -> str:
    """Désignation d'une séance écartée, pour que le motif dise **laquelle**.

    Date en `JJ/MM/AAAA` et non en ISO : ces phrases s'affichent telles quelles à côté de
    « lundi 10 août » (`API-07` — le message vient du serveur, en français). Un
    `2026-08-19` au milieu trahirait le format d'échange dans une phrase destinée à être
    lue.
    """
    return f"{KIND_LABELS.get(kind, 'Séance')} du {day:%d/%m/%Y}"


def read_proposals(
    payload: dict[str, Any],
    *,
    start: dt.date,
    end: dt.date,
    taken: set[tuple[dt.date, str]],
) -> tuple[list[ProposedSession], list[str]]:
    """Relit la réponse du modèle et rend `(séances retenues, motifs d'écart)`.

    `taken` porte les couples `(jour, nature)` déjà prévus. Il est **enrichi au fil de la
    lecture** : c'est ce qui écarte aussi les doublons que le modèle produit à
    l'intérieur de sa propre réponse, cas plus fréquent que la collision avec l'existant.
    """
    raw_sessions = payload.get("sessions")
    if not isinstance(raw_sessions, list):
        return [], []

    kept: list[ProposedSession] = []
    dropped: list[str] = []

    for entry in raw_sessions:
        if not isinstance(entry, dict):
            continue
        if len(kept) >= MAX_SESSIONS:
            dropped.append(f"Au-delà de {MAX_SESSIONS} séances, le reste a été ignoré.")
            break

        raw_date = _text(entry.get("date")) or "vide"
        try:
            day = dt.date.fromisoformat(raw_date)
        except ValueError:
            dropped.append(f"Date illisible « {raw_date} ».")
            continue

        if not start <= day <= end:
            # Aucun recalage : une date hors fenêtre est une date que le modèle a
            # inventée, et la corriger reviendrait à en inventer une autre.
            dropped.append(f"{day.isoformat()} tombe hors de la période demandée.")
            continue

        kind = normalise_kind(_text(entry.get("kind")) or DEFAULT_KIND)
        if (day, kind) in taken:
            dropped.append(f"{_label(day, kind)} : déjà prévue.")
            continue

        duration = _read_duration(entry.get("duration_min"))
        if duration is None:
            # Une séance sans durée exploitable ne peut pas être adoptée — la saisie
            # l'exige — et lui en attribuer une reviendrait à décider à la place de
            # quelqu'un. Écarter une proposition ne coûte rien : rien n'existe encore.
            dropped.append(f"{_label(day, kind)} : durée illisible.")
            continue

        # Repli de **présentation**, pas de donnée : « Muscu » décrit ce que la nature
        # dit déjà, là où une durée ou une date inventées ajouteraient une information
        # que personne n'a fournie. Sans lui, la séance serait inadoptable pour un titre.
        title = _text(entry.get("title"))[:MAX_TITLE] or KIND_LABELS.get(kind, "Séance")

        kept.append(
            ProposedSession(
                date=day,
                time=_read_time(entry.get("time")),
                # `normalise_kind` garantit l'une des trois valeurs de `KINDS`.
                kind=kind,
                title=title,
                duration_min=duration,
                note=_text(entry.get("note"))[:MAX_NOTE] or None,
                reason=_text(entry.get("reason"))[:MAX_NOTE] or None,
            )
        )
        taken.add((day, kind))

    kept.sort(key=lambda session: (session.date, session.time or ""))
    return kept, dropped


__all__ = [
    "INSTRUCTION",
    "KINDS",
    "MAX_SESSIONS",
    "build_prompt",
    "read_proposals",
]
