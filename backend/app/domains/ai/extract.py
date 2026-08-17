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


# ── La lecture au fil de l'eau (§7.1 du plan de coaching) ──


def _decodable(raw: str) -> int:
    """Longueur du plus long préfixe de `raw` qui ne coupe pas une séquence d'échappement.

    Un morceau de réseau tombe où il veut, y compris entre `\\` et `u`, ou au milieu des
    quatre chiffres d'un `\\u00e9`. Décoder un préfixe coupé là lèverait — ou pire, rendrait
    un caractère faux. Ce qui n'est pas encore décodable attend le morceau suivant.
    """
    index = 0
    safe = 0
    while index < len(raw):
        if raw[index] == "\\":
            if index + 1 >= len(raw):
                break
            index += 6 if raw[index + 1] == "u" else 2
            if index > len(raw):
                break
        else:
            index += 1
        safe = index
    return safe


class ReplyStream:
    """Extrait le champ `reply` d'un objet JSON qui arrive par morceaux.

    **Elle ne rend jamais un texte qu'il faudrait ensuite effacer**, et c'est sa raison
    d'être plutôt qu'un détail de réglage. `chat_stream` refusait de diffuser les jetons du
    modèle pour trois raisons, dont une seule comptait : une seconde passe remplace
    entièrement la première, et le lot 1 a rendu cette seconde passe fréquente.

    D'où la règle : **on ne diffuse que ce qu'on peut prouver final.** Le contrat place
    `need` avant `reply` (voir `conversation.py`), donc au moment où le premier caractère de
    la réponse arrive, on sait déjà si cette passe sera remplacée. `assured` court-circuite
    la preuve pour les cas où elle est acquise d'avance : la seconde passe, qui est finale
    par construction, et les appels sans catalogue, où `need` n'existe pas.

    Un modèle qui ne respecte pas l'ordre coûte la diffusion de sa passe — jamais sa
    justesse. Rien n'est deviné : `feed` rend « » tant que la preuve manque.

    L'analyse est **incrémentale** et non refaite à chaque morceau : un objet de quinze
    kilo-octets relu à chaque jeton coûterait le carré de sa taille, ce qui se voit à
    l'écran sur exactement les réponses longues que ce lot cherche à obtenir.
    """

    def __init__(self, *, assured: bool = False, limit: int | None = None) -> None:
        self._buffer = ""
        self._at = 0
        #: `outside` → `fields` → `key` → `colon` → (`value` | `reply`) → … → `done`.
        self._mode = "outside"
        self._depth = 0
        self._key = ""
        self._final = assured
        self._limit = limit
        #: Corps littéral de `reply`, non décodé — les échappements y sont encore écrits.
        self._raw = ""
        #: Caractères **décodés** déjà rendus, ce qui est la seule mesure comparable à la
        #: longueur d'un `reply` relu.
        self._sent = 0
        #: Valeur brute de `need`, capturée pendant qu'elle s'écrit.
        self._need = ""
        self._reply_escaped = False
        self._value_depth = 0
        self._value_in_string = False
        self._value_escaped = False

    @property
    def final(self) -> bool:
        """Vrai quand la passe est prouvée finale — donc diffusable."""
        return self._final

    def feed(self, chunk: str) -> str:
        """Absorbe un morceau et rend ce qu'il ajoute à la réponse, décodé. `""` sinon."""
        self._buffer += chunk
        out: list[str] = []

        while self._at < len(self._buffer):
            if self._mode == "done":
                break
            char = self._buffer[self._at]

            if self._mode == "outside":
                self._at += 1
                if char == "{":
                    self._depth = 1
                    self._mode = "fields"

            elif self._mode == "fields":
                self._at += 1
                if char == '"':
                    self._key = ""
                    self._mode = "key"
                elif char == "}":
                    self._mode = "done"

            elif self._mode == "key":
                self._at += 1
                if char == '"':
                    self._mode = "colon"
                else:
                    self._key += char

            elif self._mode == "colon":
                self._at += 1
                if char == ":":
                    self._mode = "reply" if self._key == "reply" else "value"
                    self._reset_value()

            elif self._mode == "value":
                self._at += 1
                self._consume_value(char)

            elif self._mode == "reply":
                # Avant le guillemet ouvrant : espaces, puis la chaîne. Un `reply` qui ne
                # serait pas une chaîne se traite comme n'importe quelle autre valeur.
                self._at += 1
                if char == '"':
                    self._mode = "reply_body"
                elif not char.isspace():
                    self._mode = "value"
                    self._reset_value()
                    self._consume_value(char)

            elif self._mode == "reply_body":
                out.append(self._consume_reply())

        return "".join(out)

    def _reset_value(self) -> None:
        self._need = ""
        self._value_depth = 0
        self._value_in_string = False
        self._value_escaped = False

    def _consume_value(self, char: str) -> None:
        """Avale une valeur quelconque, et retient celle de `need` pour la relire."""
        if self._key == "need":
            self._need += char

        if self._value_in_string:
            if self._value_escaped:
                self._value_escaped = False
            elif char == "\\":
                self._value_escaped = True
            elif char == '"':
                self._value_in_string = False
                if self._value_depth == 0:
                    self._close_value()
            return

        if char == '"':
            self._value_in_string = True
        elif char in "[{":
            self._value_depth += 1
        elif char in "]}":
            self._value_depth -= 1
            if self._value_depth <= 0:
                self._close_value()
        elif self._value_depth == 0 and char in ",}":
            # Un scalaire nu — nombre, `true`, `null` — se termine sur le séparateur. Le
            # caractère appartient à l'objet et non à la valeur : on le rend au lecteur.
            self._at -= 1
            if self._key == "need":
                self._need = self._need[:-1]
            self._close_value()

    def _close_value(self) -> None:
        """Fin d'une valeur de premier niveau. C'est ici que `need` prononce la finalité."""
        if self._key == "need" and not self._final:
            try:
                parsed = json.loads(self._need.strip() or "null")
            except json.JSONDecodeError:
                parsed = None
            # **Vide vaut final, et rien d'autre ne le vaut.** `null`, une valeur illisible
            # ou une tranche demandée laissent la preuve manquante — donc pas de diffusion.
            self._final = isinstance(parsed, list) and len(parsed) == 0
        self._mode = "fields"

    def _consume_reply(self) -> str:
        """Avance dans le corps de `reply` et rend ce qui est décodable et diffusable.

        L'échappement se suit par un drapeau et non en relisant la fin de `_raw` : trois
        antislashs de suite mettent en défaut toute lecture par suffixe, et un `\\\\` en fin
        de réponse suffit à la déclencher.
        """
        # On avale d'un coup tout ce que le tampon porte, jusqu'au guillemet fermant.
        closed = False
        while self._at < len(self._buffer):
            char = self._buffer[self._at]
            self._at += 1
            if self._reply_escaped:
                self._reply_escaped = False
            elif char == "\\":
                self._reply_escaped = True
            elif char == '"':
                closed = True
                break
            self._raw += char

        emitted = "" if not self._final else self._decode()
        if closed:
            self._mode = "fields"
        return emitted

    def _decode(self) -> str:
        """Décode le préfixe complet du littéral et rend ce qui n'a pas encore été rendu."""
        usable = _decodable(self._raw)
        if usable == 0:
            return ""
        try:
            text = json.loads(f'"{self._raw[:usable]}"')
        except json.JSONDecodeError:
            return ""
        if not isinstance(text, str) or len(text) <= self._sent:
            return ""
        if self._limit is not None:
            text = text[: self._limit]
            if len(text) <= self._sent:
                return ""
        fresh = text[self._sent :]
        self._sent = len(text)
        return fresh
