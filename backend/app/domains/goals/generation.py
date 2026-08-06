"""Génération d'un objectif (`GOAL-01`, `GOAL-02`).

Le partage du travail avec le modèle est celui du planning et de l'import Apple, et il
n'est toujours pas négociable : **le modèle propose, le serveur relit**.

Ce qu'on lui demande est un jugement — quelle métrique vaut la peine d'être poussée, quel
chiffre est ambitieux sans être absurde, pourquoi celui-là plutôt qu'un autre. Ce qu'on ne
lui demande pas, c'est de connaître le calendrier ni le catalogue : les cinq métriques
possibles lui sont **données**, avec leurs bornes, et les deux dates entre lesquelles
l'échéance doit tomber lui sont écrites en clair.

## Ce qui part d'ici, et ce qui ne part pas (`GOAL-02`)

Un **condensé factuel**, jamais les fichiers. Une trentaine de lignes : poids actuel et
amplitude, séances et courses, distance cumulée, protéines et hydratation moyennes,
suppléments suivis, objectifs passés et leur résultat. Aucune note personnelle, aucune
photo, aucun horodatage de repas.

C'est la règle que `build_prompt` du planning applique déjà, et elle est appliquée ici de
la même façon : le condensé est **construit à part**, publié à l'écran avec la proposition
(`GoalProposal.basis`), et c'est cette publication qui rend la promesse vérifiable plutôt
que déclarative.

## Trois relectures, trois protections différentes

**Une métrique inconnue est écartée.** Le modèle a le droit de répondre « sommeil » ; on
n'a aucun moyen de le mesurer, et adopter un objectif immesurable donnerait un écran qui
affiche une cible et un tiret jusqu'à son échéance.

**Une cible hors bornes est écartée, jamais ramenée à la borne.** 40 séances par semaine
rabotées à 14 donneraient un objectif faux d'apparence honnête. C'est la règle du L12,
appliquée à une intention.

**Une échéance hors fenêtre est écartée.** Pas de recalage sur le lundi le plus proche :
une date qu'on rectifie est une date qu'on a inventée.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.domains.goals.metrics import GOAL_METRICS, granularity_of, label_of, unit_of
from app.domains.goals.progress import fr
from app.domains.goals.schemas import (
    DEADLINE_MAX_WEEKS,
    DEADLINE_MIN_WEEKS,
    MAX_RATIONALE,
    MAX_TITLE,
    ProposedGoal,
)

#: En dessous de ce nombre de séances sur quatre semaines, les données sont trop maigres
#: pour viser une performance chiffrée (`GOAL-01`).
#:
#: Le seuil est bas et c'est voulu : une séance par semaine suffit à établir une cadence
#: sur laquelle bâtir. En deçà, il n'y a pas de point de départ, et proposer « 12 km par
#: semaine » à quelqu'un qui n'a jamais couru n'est pas un objectif mais un vœu. Le repli
#: n'est pas une punition — c'est le seul objectif qui ait un sens quand la régularité
#: elle-même n'est pas acquise.
THIN_SESSIONS = 4

#: Métrique du repli de régularité. Elle se mesure sans rien d'autre que des séances
#: consignées, ce qui est exactement ce qui manque quand les données sont maigres.
FALLBACK_METRIC = "weekly_sessions"

INSTRUCTION = (
    "Tu es un préparateur physique. Tu réponds uniquement par un objet JSON, "
    "sans phrase avant ni après, sans bloc de code."
)

_TEMPLATE = """Propose **un seul** objectif d'entraînement, chiffré et daté.

## Ce que disent les données

{summary}

## Objectifs précédents

{past}

## Métriques mesurables — tu ne peux en choisir aucune autre

{metrics}

## Échéance

Elle doit tomber entre le {floor} et le {ceiling}. Recopie une date exactement dans cette
forme : AAAA-MM-JJ.

{focus}{fallback}## Réponse attendue

{{"title": "…", "metric": "…", "target": 3, "deadline": "AAAA-MM-JJ", "rationale": "…"}}

- "metric" est l'une des clés listées ci-dessus, écrite telle quelle.
- "target" est un nombre, dans l'unité de la métrique choisie. Pas de texte, pas d'unité.
- "title" dit l'objectif en une phrase courte ("Trois séances par semaine").
- "rationale" dit pourquoi ce chiffre-là, en s'appuyant sur un fait ci-dessus.

Règles :
- Un objectif ambitieux mais atteignable : pars de la valeur actuelle, pas de zéro.
- Ne reprends pas un objectif déjà atteint, ni un objectif abandonné à l'identique.
- Une seule métrique. Un objectif qui en suit deux ne se mesure pas.
"""

_FALLBACK_NOTE = """## Contrainte

Les données sont trop maigres pour viser une performance. Propose un objectif de
**régularité** : la métrique doit être « {metric} ». C'est le seul chiffre qui ait un sens
tant que la fréquence n'est pas établie.

"""


def metric_lines() -> list[str]:
    """Les cinq métriques, avec leur unité et leurs bornes, telles qu'elles partent.

    Publiées au modèle et bornées à la relecture : on le lui dit **et** on le vérifie.
    Une consigne suivie neuf fois sur dix produit un objectif immesurable une fois sur dix,
    et celui-là serait adopté.
    """
    lines: list[str] = []
    for key, metric in GOAL_METRICS.items():
        unit = unit_of(key)
        period = "par semaine" if granularity_of(key) == "week" else "par jour"
        lines.append(
            f'"{key}" — {label_of(key).lower()}, en {unit} {period} '
            f"(entre {fr(metric.minimum)} et {fr(metric.maximum)}) ; {metric.hint}"
        )
    return lines


def build_prompt(
    *,
    summary: list[str],
    past: list[str],
    floor: dt.date,
    ceiling: dt.date,
    focus: str = "",
    fallback: bool = False,
) -> str:
    """Assemble la consigne. **Aucun fichier n'est envoyé au modèle** (`GOAL-02`).

    `summary` et `past` sont déjà des phrases : ce module ne sait pas les produire, et
    c'est ce qui permet de le tester sur des valeurs fixes.
    """
    return _TEMPLATE.format(
        summary="\n".join(f"- {line}" for line in summary) or "- Aucune donnée relevée.",
        past="\n".join(f"- {line}" for line in past) or "- Aucun objectif précédent.",
        metrics="\n".join(f"- {line}" for line in metric_lines()),
        floor=floor.isoformat(),
        ceiling=ceiling.isoformat(),
        # Une rubrique vide dans une consigne invite le modèle à la remplir lui-même.
        focus=f"## Ce que je veux travailler\n\n{focus.strip()}\n\n" if focus.strip() else "",
        fallback=_FALLBACK_NOTE.format(metric=FALLBACK_METRIC) if fallback else "",
    )


def _text(raw: object) -> str:
    """Valeur textuelle, `""` pour tout ce qui veut dire « rien ».

    Reprise telle quelle de la relecture d'import et de celle du planning, où elle a évité
    qu'un tiret devienne une distance. Les modèles rendent `null`, `"null"`, `"—"` ou
    `"N/A"` pour la même chose.
    """
    if raw is None or isinstance(raw, bool):
        return ""
    text = str(raw).strip()
    return "" if text.lower() in {"", "null", "none", "n/a", "na", "-", "—", "--"} else text


def _number(raw: object) -> float | None:
    """Nombre décimal, virgule française comprise. `None` si ce n'en est pas un.

    Volontairement étroit : on n'essaie pas d'extraire « 3 » de « environ 3 séances ». Une
    cible devinée dans une phrase serait une cible inventée.
    """
    text = _text(raw).replace(",", ".").replace(" ", "").replace(" ", "")
    try:
        return float(text)
    except ValueError:
        return None


def read_goal(
    payload: dict[str, Any],
    *,
    floor: dt.date,
    ceiling: dt.date,
    fallback: bool = False,
) -> tuple[ProposedGoal | None, list[str]]:
    """Relit la réponse du modèle et rend `(objectif retenu, motifs d'écart)`.

    Rend `None` dès qu'une pièce indispensable manque. Un objectif amputé — sans cible, ou
    daté n'importe quand — ne serait pas « presque bon » : il serait inadoptable, et le
    proposer quand même ferait porter à l'utilisateur un contrôle que le serveur vient de
    refuser de faire.
    """
    dropped: list[str] = []

    key = _text(payload.get("metric")).lower()
    metric = GOAL_METRICS.get(key)
    if metric is None:
        dropped.append(f"Métrique « {key or 'absente'} » : rien ne la mesure dans Metric.")
        return None, dropped

    if fallback and key != FALLBACK_METRIC:
        # Le repli n'est pas une préférence, c'est une contrainte : sans historique, tout
        # chiffre de performance serait tiré d'un point de départ qui n'existe pas.
        dropped.append(
            f"Métrique « {key} » : les données sont trop maigres pour autre chose "
            "qu'un objectif de régularité."
        )
        return None, dropped

    target = _number(payload.get("target"))
    if target is None:
        dropped.append("Cible illisible : un objectif sans chiffre ne se mesure pas.")
        return None, dropped

    if not metric.minimum <= target <= metric.maximum:
        # Hors bornes, on écarte ; on ne ramène pas à la borne. Une cible rabotée
        # donnerait un objectif faux d'apparence honnête.
        dropped.append(
            f"Cible {fr(target)} {unit_of(key)} hors des bornes plausibles "
            f"({fr(metric.minimum)} à {fr(metric.maximum)})."
        )
        return None, dropped

    raw_deadline = _text(payload.get("deadline")) or "vide"
    try:
        deadline = dt.date.fromisoformat(raw_deadline)
    except ValueError:
        dropped.append(f"Échéance illisible « {raw_deadline} ».")
        return None, dropped

    if not floor <= deadline <= ceiling:
        # Aucun recalage : une date hors fenêtre est une date que le modèle a inventée, et
        # la corriger reviendrait à en inventer une autre.
        dropped.append(
            f"Échéance {deadline:%d/%m/%Y} hors de la fenêtre de "
            f"{DEADLINE_MIN_WEEKS} à {DEADLINE_MAX_WEEKS} semaines."
        )
        return None, dropped

    # Repli de **présentation**, pas de donnée : « Séances par semaine » ne dit rien que la
    # métrique ne disait déjà, là où une cible ou une date inventées ajouteraient une
    # information que personne n'a fournie.
    title = _text(payload.get("title"))[:MAX_TITLE] or label_of(key)

    return (
        ProposedGoal(
            title=title,
            metric=key,
            label=label_of(key),
            target=target,
            unit=unit_of(key),
            deadline=deadline,
            rationale=_text(payload.get("rationale"))[:MAX_RATIONALE],
        ),
        dropped,
    )


__all__ = [
    "FALLBACK_METRIC",
    "INSTRUCTION",
    "THIN_SESSIONS",
    "build_prompt",
    "metric_lines",
    "read_goal",
]
