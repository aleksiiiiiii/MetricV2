"""Consigne et relecture de l'assistant (`IA-09`, `IA-10`, `IA-12`).

Module **pur** : une consigne à assembler, une réponse à relire. Il ne lit aucun fichier,
ne connaît ni l'horloge ni le modèle, et n'écrit rien. C'est le même parti pris que
`progress.py` et `weekly.py`, avec la même conséquence — chaque cas se vérifie sur des
valeurs fixes, sans monter d'application.

## Le partage du travail

Le modèle **répond** et **repère** ; le serveur relit. Ce qu'on lui demande de repérer est
précis : ce que l'utilisateur vient de dire sur lui-même et qu'aucun fichier ne porte. Pas
de résumé de la conversation, pas de reformulation des chiffres qu'on vient de lui donner.

## Le garde-fou médical (`IA-12`)

L'assistant n'est pas médecin, et la consigne le lui interdit explicitement — pas de
diagnostic, pas de traitement, pas d'interprétation de symptôme. La relecture, elle, **ne
censure rien** : filtrer une réponse qu'on a demandée donnerait un texte amputé dont
personne ne saurait ce qu'il a perdu. La garde est en amont, dans la consigne, et en aval,
dans une mention permanente à l'écran.

C'est un choix de produit assumé : une application de santé dont l'assistant interprète une
douleur au genou rend un service **négatif**, parce que le conseil paraît sûr du seul fait
qu'il est bien écrit.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from app.domains.assistant.models import MAX_NOTE, normalise_topic
from app.domains.assistant.schemas import MAX_PROPOSED, ProposedMemory

#: Longueur de la réponse rendue. Une réponse plus longue n'a pas été tronquée par le
#: modèle : elle a été coupée ici, parce qu'un mur de texte ne se lit pas sur un téléphone.
MAX_REPLY = 2000

#: Longueur minimale d'une note retenue. En dessous, ce n'est pas un fait durable — c'est
#: « ok », « le genou », ou un fragment que personne ne comprendra dans six mois.
MIN_NOTE = 10

INSTRUCTION = (
    "Tu es l'assistant d'entraînement de cette application de suivi sportif. "
    "Tu réponds uniquement par un objet JSON, sans phrase avant ni après, sans bloc de "
    "code. "
    "Tu n'es pas médecin : tu ne poses aucun diagnostic, tu ne recommandes aucun "
    "traitement, tu n'interprètes aucun symptôme. Devant une douleur, une blessure ou un "
    "trouble, tu le dis franchement et tu renvoies vers un professionnel de santé — puis "
    "tu t'en tiens à ce que les données montrent."
)

_TEMPLATE = """Réponds à la question en t'appuyant sur ce qui suit, et sur rien d'autre.

## Ce que disent les données

{context}

## Ce que tu sais de moi

{memory}

{history}## Question

{question}

## Réponse attendue

{{"reply": "…", "remember": [{{"topic": "…", "note": "…"}}]}}

- "reply" : ta réponse, en français, quatre phrases au plus. Cite les chiffres ci-dessus
  quand ils répondent ; dis que tu ne sais pas quand ils ne disent rien là-dessus.
- "remember" : ce que **je viens de t'apprendre sur moi** et qui vaudra encore dans six
  mois — une blessure, un sommeil, un traitement, une contrainte. Liste vide le plus
  souvent, et c'est le cas normal.

Règles :
- N'invente aucun chiffre. Si la réponse demande une donnée absente ci-dessus, dis-le.
- Ne mets **jamais** dans "remember" ce que les données ci-dessus disent déjà : elles sont
  recalculées à chaque question, une copie figée deviendrait fausse.
- Ne mets pas dans "remember" ce que tu viens de répondre. On y retient ce que je dis, pas
  ce que tu dis.
- Une douleur, une blessure ou un symptôme se note dans "remember" et se renvoie à un
  professionnel dans "reply". Les deux, pas l'un ou l'autre.
"""


def build_prompt(
    *,
    question: str,
    context: list[str],
    memory: list[str],
    history: list[tuple[str, str]] | None = None,
) -> str:
    """Assemble la consigne. **Aucun fichier n'est envoyé au modèle** (`IA-09`).

    `context` et `memory` sont déjà des phrases : ce module ne sait pas les produire, et
    c'est ce qui permet de le tester sur des valeurs fixes.

    L'historique est rendu tel quel, rôle par rôle. Le condensé, lui, est renvoyé **entier**
    à chaque tour et non résumé : il est recalculé, et une réponse au dixième tour doit
    porter sur les chiffres du moment, pas sur ceux d'il y a dix minutes.
    """
    turns = ""
    if history:
        lines = "\n".join(
            f"- {'Moi' if role == 'user' else 'Toi'} : {content}" for role, content in history
        )
        turns = f"## Ce qu'on s'est déjà dit\n\n{lines}\n\n"

    return _TEMPLATE.format(
        context="\n".join(f"- {line}" for line in context) or "- Aucune donnée relevée.",
        memory="\n".join(f"- {line}" for line in memory) or "- Rien de noté pour l'instant.",
        history=turns,
        question=question.strip(),
    )


def _text(raw: object) -> str:
    """Valeur textuelle, `""` pour tout ce qui veut dire « rien ».

    Reprise des relectures d'import, de planning et d'objectif, où elle a évité qu'un tiret
    devienne une distance.
    """
    if raw is None or isinstance(raw, bool):
        return ""
    text = str(raw).strip()
    return "" if text.lower() in {"", "null", "none", "n/a", "na", "-", "—", "--"} else text


def _significant(text: str) -> set[str]:
    """Mots porteurs de sens d'une phrase, accents et ponctuation retirés.

    Les mots courts partent avec la ponctuation : « de », « la », « par » se retrouvent
    dans n'importe quelle paire de phrases françaises et rendraient toute comparaison
    positive. Les nombres aussi — c'est le vocabulaire qui distingue « douleur au genou »
    d'une ligne de statistiques, pas les chiffres.
    """
    folded = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(char if char.isalnum() else " " for char in folded if not _is_accent(char))
    return {word for word in stripped.split() if len(word) >= 4 and not word.isdigit()}


def _is_accent(char: str) -> bool:
    return unicodedata.combining(char) != 0


def _echoes(note: str, lines: list[str]) -> bool:
    """Vrai si la note ne fait que redire une ligne déjà envoyée au modèle.

    Test de **contenance** et non de ressemblance : la note est écartée quand *tous* ses
    mots porteurs se retrouvent dans une même ligne du condensé. C'est exactement le cas
    qu'on veut attraper — le modèle qui recopie « séances par semaine : 2,4 » — et cela
    laisse passer « je ne peux pas courir plus de 5 km sans douleur au genou », dont
    « douleur » et « genou » ne figurent dans aucune statistique.

    Une note sans aucun mot porteur est écartée aussi : elle ne dirait rien.
    """
    words = _significant(note)
    if not words:
        return True
    return any(words <= _significant(line) for line in lines)


def read_reply(
    payload: dict[str, Any],
    *,
    context: list[str],
    known: list[str] | None = None,
) -> tuple[str, list[ProposedMemory], list[str]]:
    """Relit la réponse et rend `(réponse, notes proposées, motifs d'écart)`.

    `known` porte les notes déjà retenues : une mémoire qui se répète à chaque
    conversation remplirait le carnet de la même phrase reformulée dix fois, et le carnet
    part entier dans chaque question.

    Une réponse vide n'est pas rattrapée : compléter ce qu'un modèle n'a pas dit
    reviendrait à répondre à sa place. Le service décide plus haut ce qu'il en fait.
    """
    reply = _text(payload.get("reply"))[:MAX_REPLY]

    raw = payload.get("remember")
    if isinstance(raw, dict):
        # Un modèle rend parfois un objet là où la consigne demande une liste. L'accepter
        # coûte deux lignes ; le refuser coûterait la note, et l'appel avec.
        raw = [raw]
    if not isinstance(raw, list):
        return reply, [], []

    seen = [note.lower() for note in (known or [])]
    kept: list[ProposedMemory] = []
    dropped: list[str] = []

    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if len(kept) >= MAX_PROPOSED:
            dropped.append(f"Au-delà de {MAX_PROPOSED} notes, le reste a été ignoré.")
            break

        note = _text(entry.get("note"))[:MAX_NOTE]
        if len(note) < MIN_NOTE:
            # Ni corrigée ni complétée : une note qu'on allongerait serait une note qu'on
            # aurait écrite soi-même.
            continue

        if _echoes(note, context):
            dropped.append(f"« {note} » : les données le disaient déjà.")
            continue

        if note.lower() in seen:
            dropped.append(f"« {note} » : déjà noté.")
            continue

        kept.append(ProposedMemory(topic=normalise_topic(_text(entry.get("topic"))), note=note))
        seen.append(note.lower())

    return reply, kept, dropped


__all__ = ["INSTRUCTION", "MAX_REPLY", "MIN_NOTE", "build_prompt", "read_reply"]
