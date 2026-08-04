"""Estimation des macros d'une assiette par un modèle vision (`NUT-04`).

Ce module ne sait rien des modèles ni des quotas — il écrit une consigne, et relit ce qui
en revient. Toute la mécanique de cascade vit dans `app/domains/ai/service.py`.

**Ce qui sort d'ici est une proposition, jamais une écriture.** L'endpoint d'analyse ne
touche pas au fichier : il rend des chiffres que l'écran affiche comme *proposés*, et rien
ne part sur Nextcloud tant que l'utilisateur n'a pas validé. C'est « aucune valeur inventée
à l'écran » transposé à l'estimation : une valeur devinée par une machine est encore plus
facile à prendre pour une mesure qu'un zéro, parce qu'elle est plausible.

D'où la relecture stricte de la réponse : un nombre hors des bornes de vraisemblance
(`API-06`) est **écarté**, pas ramené à la borne. Ramener 4000 g de protéines à 500 g
donnerait une valeur fausse d'apparence honnête ; un champ vide dit ce qu'il en est.
"""

from __future__ import annotations

from typing import Any

from app.domains.nutrition.schemas import MealEstimate

#: Rôle du modèle. Court et impératif : les modèles gratuits suivent d'autant mieux une
#: consigne qu'elle tient en quelques lignes.
INSTRUCTION = (
    "Tu es un assistant nutritionnel. Tu réponds uniquement par un objet JSON, "
    "sans phrase avant ni après, sans bloc de code."
)

#: La demande. Deux points y font tout le travail : l'ordre de mettre `null` sur ce qui
#: n'est pas visible, et l'interdiction de la fourchette — « 30 à 40 g » n'est pas un
#: nombre, et le premier des deux serait choisi arbitrairement à la relecture.
PROMPT = """Analyse cette photo de repas et estime ce qu'elle contient.

Réponds par cet objet JSON exactement :
{"comment": "…", "protein_g": 0, "added_sugar_g": 0, "calories": 0, "readable": true}

- "comment" : les aliments visibles, en français, quelques mots ("poulet, riz, brocolis").
- "protein_g" : protéines totales de l'assiette, en grammes.
- "added_sugar_g" : sucres AJOUTÉS uniquement, pas ceux des fruits entiers.
- "calories" : total en kilocalories.
- "readable" : false si la photo ne montre pas de nourriture.

Mets null sur tout ce que tu ne peux pas estimer depuis cette photo. Ne devine pas.
Un seul nombre par champ, jamais de fourchette ni d'unité dans la valeur."""


def _number(payload: dict[str, Any], key: str, *, low: float, high: float) -> float | None:
    """Nombre exploitable d'une réponse de modèle, ou `None`.

    Les modèles écrivent indifféremment `32`, `32.5`, `"32"` ou `"32 g"`. Les trois
    premiers sont un nombre ; le quatrième aussi, une fois l'unité retirée. Tout le reste —
    `"environ 30-40"`, `"beaucoup"`, `null` — n'en est pas un et ne devient pas un zéro.
    """
    raw = payload.get(key)
    if raw is None or isinstance(raw, bool):
        return None

    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        # Une seule unité collée est tolérée ; un texte reste un texte.
        text = raw.strip().lower().removesuffix("kcal").removesuffix("g").strip()
        try:
            value = float(text.replace(",", "."))
        except ValueError:
            return None
    else:
        return None

    # Hors bornes : écarté, jamais ramené à la borne (`API-06`).
    return value if low <= value <= high else None


def read_estimate(payload: dict[str, Any]) -> MealEstimate:
    """Traduit la réponse du modèle en proposition affichable (`NUT-04`)."""
    calories = _number(payload, "calories", low=0, high=10000)
    comment = payload.get("comment")

    # `readable` absent vaut « lisible » : la majorité des modèles ne renvoient le drapeau
    # que lorsqu'ils butent, et exiger sa présence rejetterait des réponses valables.
    readable = payload.get("readable")

    protein = _number(payload, "protein_g", low=0, high=500)
    sugar = _number(payload, "added_sugar_g", low=0, high=1000)

    return MealEstimate(
        comment=comment.strip()[:200] if isinstance(comment, str) and comment.strip() else None,
        protein_g=protein,
        added_sugar_g=sugar,
        calories=int(calories) if calories is not None else None,
        readable=readable is not False,
        # Une réponse bien formée mais entièrement à `null` est un cas courant sur les
        # petits modèles. L'écran doit pouvoir le dire — trois champs restés vides sans un
        # mot passeraient pour une panne.
        empty=protein is None and sugar is None and calories is None,
    )
