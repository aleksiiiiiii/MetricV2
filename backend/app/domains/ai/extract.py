"""Extraction d'un objet JSON dans une réponse de modèle (`IA-05`).

Un modèle à qui l'on demande du JSON en renvoie rarement seulement. Il l'entoure d'une
phrase de politesse, l'enferme dans un bloc de code, ou — pour les modèles à raisonnement
visible, qui sont la majorité des modèles gratuits — le fait précéder d'un monologue entre
`<think>` et `</think>` qui contient lui-même des accolades.

D'où deux gestes, dans cet ordre :

1. **Retirer le raisonnement.** Il est délimité, donc retirable sans deviner. Un `<think>`
   jamais refermé — réponse coupée en plein monologue — emporte tout ce qui suit : il n'y
   a rien à sauver après lui.
2. **Prendre le premier objet équilibré.** On compte les accolades en ignorant celles qui
   sont dans une chaîne, et on s'arrête à la fermeture du premier objet complet. Une
   recherche par expression régulière échouerait sur le premier objet imbriqué venu.

**Rien n'est deviné.** Une réponse tronquée ne rend pas un objet partiel : elle ne rend
rien, et l'appelant passe au modèle suivant (`IA-03`). Compléter des accolades manquantes
reviendrait à inventer les valeurs qu'elles contenaient.
"""

from __future__ import annotations

import json
import re
from typing import Any

#: Monologues de raisonnement. Plusieurs balises coexistent selon les familles de modèles.
_REASONING = re.compile(
    r"<(?P<tag>think|thinking|reasoning|scratchpad)\b[^>]*>.*?</(?P=tag)>",
    re.DOTALL | re.IGNORECASE,
)

#: Ouverture jamais refermée : la réponse s'est arrêtée pendant le raisonnement.
_REASONING_OPEN = re.compile(r"<(?:think|thinking|reasoning|scratchpad)\b[^>]*>", re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Retire les monologues de raisonnement d'une réponse."""
    cleaned = _REASONING.sub(" ", text)
    open_tag = _REASONING_OPEN.search(cleaned)
    # Une ouverture qui subsiste n'a pas de fermeture : tout ce qui suit est du monologue
    # interrompu, et le JSON attendu n'a jamais été écrit.
    return cleaned[: open_tag.start()] if open_tag else cleaned


def first_json_object(text: str) -> dict[str, Any] | None:
    """Premier objet JSON complet du texte, ou `None` s'il n'y en a aucun.

    L'équilibrage se fait à la main plutôt qu'en tentant `json.loads` sur des tranches :
    un objet suivi de prose ferait échouer l'analyseur sur toute la chaîne, alors qu'il
    est parfaitement lisible jusqu'à son accolade fermante.
    """
    cleaned = strip_reasoning(text)

    depth = 0
    start = -1
    in_string = False
    escaped = False

    for index, char in enumerate(cleaned):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth == 0:
                continue  # accolade fermante orpheline : du texte, pas du JSON
            depth -= 1
            if depth == 0:
                candidate = cleaned[start : index + 1]
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    # Équilibré mais invalide — guillemets simples, virgule finale. On
                    # continue : un modèle bavard peut avoir écrit un exemple avant.
                    continue
                if isinstance(parsed, dict):
                    return parsed

    return None
