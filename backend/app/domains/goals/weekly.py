"""Bilan hebdomadaire (`IA-08`).

Trois choses, et pas une de plus : **ce qui a progressé**, **ce qui a décroché**, **une
action concrète pour la semaine suivante**. La contrainte de forme est la fonctionnalité :
un paragraphe libre dirait la même chose en plus long et ne se relirait pas dans six mois.

Comme partout ailleurs dans ce lot, ce module est **pur** — une consigne à assembler, une
réponse à relire. Il ne lit aucun fichier, ne connaît ni l'horloge ni le modèle, et
n'écrit rien.

## La semaine commentée est révolue

Le bilan porte sur la semaine **qui vient de finir**, jamais sur celle en cours. Commenter
un mardi le « décrochage » d'une semaine dont il reste cinq jours donnerait un bilan faux
qui se corrigerait tout seul le dimanche — la même raison qui fait que la fenêtre
d'observation d'un objectif s'arrête au dimanche dernier.

## Ce que le bilan ne recalcule pas

L'écart entre le planning et le réalisé lui est **fourni** : `PLAN-06` en détient l'unique
implémentation, et `AdherenceView` la sert déjà. En réécrire une seconde ici donnerait deux
taux de respect divergents pour la même semaine, ce que le §2 du document d'état interdit
depuis trois lots.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

#: Nombre maximal de points retenus par rubrique. Au-delà, ce n'est plus un bilan mais un
#: journal, et l'action concrète — la seule ligne sur laquelle on peut agir — se noie.
MAX_POINTS = 4

#: Longueurs des textes retenus, alignées sur `Note`.
MAX_LINE = 300
MAX_ACTION = 300

INSTRUCTION = (
    "Tu es un préparateur physique. Tu réponds uniquement par un objet JSON, "
    "sans phrase avant ni après, sans bloc de code."
)

_TEMPLATE = """Rédige le bilan de la semaine du {monday} au {sunday}.

## Ce que disent les données de cette semaine

{summary}

## Les semaines précédentes, pour comparer

{history}

{goal}## Réponse attendue

{{"progress": ["…"], "setbacks": ["…"], "action": "…"}}

- "progress" : ce qui a progressé, un fait chiffré par ligne, au maximum {maximum}.
- "setbacks" : ce qui a décroché, même forme. Liste vide si rien n'a décroché.
- "action" : **une seule** action concrète pour la semaine qui commence, en une phrase.

Règles :
- N'écris que ce que les chiffres ci-dessus disent. Pas de conseil général, pas de morale.
- Compare à la semaine précédente, pas à un idéal.
- L'action doit être faisable en sept jours et se vérifier sur ces mêmes chiffres.
"""


def build_prompt(
    *,
    monday: dt.date,
    summary: list[str],
    history: list[str],
    goal: str = "",
) -> str:
    """Assemble la consigne. Un condensé factuel, jamais les fichiers (`GOAL-02`).

    La règle vaut ici comme pour un objectif : ce qui part tient en une trentaine de
    lignes et ne contient ni note personnelle, ni photo, ni horodatage.
    """
    return _TEMPLATE.format(
        monday=monday.isoformat(),
        sunday=(monday + dt.timedelta(days=6)).isoformat(),
        summary="\n".join(f"- {line}" for line in summary) or "- Aucune donnée cette semaine-là.",
        history="\n".join(f"- {line}" for line in history) or "- Aucun historique.",
        goal=f"## Objectif en cours\n\n{goal.strip()}\n\n" if goal.strip() else "",
        maximum=MAX_POINTS,
    )


def _text(raw: object) -> str:
    """Valeur textuelle, `""` pour tout ce qui veut dire « rien »."""
    if raw is None or isinstance(raw, bool):
        return ""
    text = str(raw).strip()
    return "" if text.lower() in {"", "null", "none", "n/a", "na", "-", "—", "--"} else text


def _lines(raw: object) -> list[str]:
    """Une rubrique, quelle que soit la forme rendue.

    Les modèles alternent entre une liste et une phrase unique pour la même demande.
    Accepter les deux coûte trois lignes ; refuser la seconde coûterait un bilan perdu
    sur deux — et un appel payant avec.
    """
    if isinstance(raw, str):
        line = _text(raw)
        return [line[:MAX_LINE]] if line else []
    if not isinstance(raw, list):
        return []
    kept = [_text(item)[:MAX_LINE] for item in raw if _text(item)]
    return kept[:MAX_POINTS]


def read_review(payload: dict[str, Any]) -> tuple[list[str], list[str], str]:
    """Relit la réponse et rend `(progrès, décrochages, action)`.

    Aucune rubrique n'est obligatoire, et l'absence de décrochages est une **bonne
    nouvelle**, pas une réponse incomplète : une semaine sans rien à redire existe. Le
    service décide plus haut si ce qui reste vaut d'être montré.
    """
    return (
        _lines(payload.get("progress")),
        _lines(payload.get("setbacks")),
        _text(payload.get("action"))[:MAX_ACTION],
    )


__all__ = ["INSTRUCTION", "MAX_POINTS", "build_prompt", "read_review"]
