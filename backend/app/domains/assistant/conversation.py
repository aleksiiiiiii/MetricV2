"""Consigne et relecture de l'assistant (`IA-09`, `IA-10`, `IA-12`).

Module **pur** : une consigne à assembler, une réponse à relire. Il ne lit aucun fichier,
ne connaît ni l'horloge ni le modèle, et n'écrit rien. C'est le même parti pris que
`progress.py` et `weekly.py`, avec la même conséquence — chaque cas se vérifie sur des
valeurs fixes, sans monter d'application.

## Le partage du travail

Le modèle **répond** et **repère** ; le serveur relit. Ce qu'on lui demande de repérer est
précis : ce que l'utilisateur vient de dire sur lui-même et qu'aucun fichier ne porte. Pas
de résumé de la conversation, pas de reformulation des chiffres qu'on vient de lui donner.

## Rapporter ne suffit pas (lot 7)

La consigne a longtemps demandé « quatre phrases au plus », héritage du premier usage de
l'IA — lire une photo de repas — et jamais rediscuté quand une conversation est apparue.
Elle produisait un assistant qui **rapporte** : sur « je charge combien lundi ? », il
ouvrait par « je n'ai pas de charge prescrite pour lundi » avant de réciter l'historique.
La donnée était là depuis le lot 1 ; ce qui manquait était l'autorisation de conclure.

La longueur suit donc l'intention, et une demande de conseil appelle un conseil. Deux
choses **ne** bougent pas avec ça : on n'invente aucun chiffre, et le garde-fou ci-dessous
prime sur l'invitation à conclure — la consigne le dit dans la règle elle-même, parce
qu'une exception laissée implicite est une exception qu'un modèle ne voit pas.

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

from app.domains.assistant.models import MAX_CONTENT, MAX_NOTE, MAX_TITLE, normalise_topic
from app.domains.assistant.schemas import (
    MAX_ACTION_NAME,
    MAX_ACTIONS,
    MAX_NEED,
    MAX_PROPOSED,
    ProposedAction,
    ProposedMemory,
)

#: Longueur de la réponse rendue. Une réponse plus longue n'a pas été tronquée par le
#: modèle : elle a été coupée ici.
#:
#: **Montée de 2 000 au lot 7**, en même temps que « quatre phrases au plus » quittait la
#: consigne. Les deux disaient la même chose de deux façons, et aucun plan d'entraînement
#: n'y tenait. La borne reste — un mur de texte ne se lit pas sur un téléphone — mais elle
#: est désormais posée sur `MAX_CONTENT`, la capacité d'un message stocké, plutôt que sur
#: un nombre choisi à vue. C'est ce qui garantit qu'une réponse affichée est **exactement**
#: la réponse relue trois semaines plus tard : au-dessus, `_append_messages` la couperait
#: une seconde fois et le fil rejouerait un texte que personne n'a lu.
MAX_REPLY = MAX_CONTENT

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

{history}{actions}## Question

{question}

## Réponse attendue

{{"reply": "…", "remember": [{{"topic": "…", "note": "…"}}]{extra}}}

- "reply" : ta réponse, en français. **Sa longueur suit ce que je demande** — un chiffre se
  rend en une phrase, un plan ou une analyse se développe autant qu'il le faut. Cite les
  chiffres ci-dessus quand ils répondent ; dis que tu ne sais pas quand ils ne disent rien
  là-dessus.
- "remember" : ce que **je viens de t'apprendre sur moi** et qui vaudra encore dans six
  mois — une blessure, un sommeil, un traitement, une contrainte. Liste vide le plus
  souvent, et c'est le cas normal.
{fields}
Règles :
- **Quand je demande quoi faire, réponds par ce qu'il faut faire.** Tu es mon coach : une
  charge, un nombre de séries, un rythme, appuyés sur les chiffres ci-dessus et annoncés
  comme ta recommandation. Rappeler l'historique puis me laisser conclure ne répond pas à
  la question. Cette règle ne vaut pas pour une douleur, une blessure ou un symptôme : là,
  tu notes, tu renvoies vers un professionnel, et tu t'en tiens là.
- N'invente aucun chiffre. Si la réponse demande une donnée absente ci-dessus, dis-le.
- Ne mets **jamais** dans "remember" ce que les données ci-dessus disent déjà : elles sont
  recalculées à chaque question, une copie figée deviendrait fausse.
- Ne mets pas dans "remember" ce que tu viens de répondre. On y retient ce que je dis, pas
  ce que tu dis.
- Une douleur, une blessure ou un symptôme se note dans "remember" et se renvoie à un
  professionnel dans "reply". Les deux, pas l'un ou l'autre.
"""

#: Ce qui s'ajoute à la consigne quand des actions sont possibles.
#:
#: Rédigé en « je te demande / tu fais » et non en « tu peux » : un modèle à qui on offre
#: une possibilité la prend, et la plupart des questions n'appellent aucune écriture. La
#: liste vide doit être présentée comme le cas normal, sinon chaque « où j'en suis ? »
#: repart avec une séance ajoutée.
_ACTION_FIELDS = """- "actions" : ce que je te demande d'écrire dans mes données. **Liste vide le plus
  souvent** — une question est une question, pas une instruction. N'agis que si je te le
  demande explicitement, dans ce message-ci.
- "need" : ce qui te manque pour agir, à choisir dans la liste des tranches ci-dessus.
  Ne le remplis que si tu ne peux pas agir sans. Tu ne l'obtiendras qu'une fois."""

_ACTION_RULES = """- Une action est {"name": "…", "args": {…}}. N'emploie **que** les noms listés, avec
  exactement les arguments décrits. Un nom inventé est ignoré, et je ne le saurai pas.
- Ne devine jamais un identifiant, une date ni une valeur. S'il te manque de quoi agir,
  laisse "actions" vide et demande-le dans "reply", ou remplis "need".
- Ne parle dans "reply" que des actions que tu as réellement mises dans "actions".
- **Aucune action à la suite d'une douleur, d'une blessure ou d'un symptôme.** Tu notes,
  tu renvoies vers un professionnel, tu n'écris rien d'autre."""


def build_prompt(
    *,
    question: str,
    context: list[str],
    memory: list[str],
    history: list[tuple[str, str]] | None = None,
    actions: list[str] | None = None,
    slices: list[str] | None = None,
    naming: bool = False,
) -> str:
    """Assemble la consigne. **Aucun fichier n'est envoyé au modèle** (`IA-09`).

    `context` et `memory` sont déjà des phrases : ce module ne sait pas les produire, et
    c'est ce qui permet de le tester sur des valeurs fixes. `actions` suit la même règle —
    ce sont des lignes de description **déjà rendues** par le catalogue, que ce module se
    contente d'insérer. Il ne connaît donc aucun nom d'action, et le catalogue reste la
    seule autorité sur ce qui existe.

    Sans `actions`, la consigne est exactement celle d'avant : un assistant qui répond. Ce
    n'est pas une commodité de test, c'est le comportement voulu quand rien n'est
    exécutable — inviter à agir sans pouvoir agir ne produirait que des promesses.

    L'historique est rendu tel quel, rôle par rôle. Le condensé, lui, est renvoyé **entier**
    à chaque tour et non résumé : il est recalculé, et une réponse au dixième tour doit
    porter sur les chiffres du moment, pas sur ceux d'il y a dix minutes.

    `naming` n'est vrai qu'au premier tour : c'est là qu'un fil se nomme. Le redemander à
    chaque tour coûterait des jetons et inviterait le modèle à rebaptiser une discussion
    en cours, ce qu'on ne cherche pas.
    """
    turns = ""
    if history:
        lines = "\n".join(
            f"- {'Moi' if role == 'user' else 'Toi'} : {content}" for role, content in history
        )
        turns = f"## Ce qu'on s'est déjà dit\n\n{lines}\n\n"

    catalogue = ""
    extra = ""
    fields = ""
    rules = ""
    if actions:
        listed = "\n".join(f"- {line}" for line in actions)
        available = ", ".join(slices or []) or "aucune"
        catalogue = (
            f"## Ce que tu peux faire dans mes données\n\n{listed}\n\n"
            f"Tranches de contexte disponibles à la demande : {available}.\n\n"
        )
        extra = ', "actions": [], "need": []'
        fields = f"{_ACTION_FIELDS}\n"
        rules = f"\n{_ACTION_RULES}"

    if naming:
        extra = f'{extra}, "title": "…"'
        fields = f'{fields}- "title" : cinq mots qui nomment cette discussion, pour la retrouver plus tard.\n'

    return (
        _TEMPLATE.format(
            context="\n".join(f"- {line}" for line in context) or "- Aucune donnée relevée.",
            memory="\n".join(f"- {line}" for line in memory) or "- Rien de noté pour l'instant.",
            history=turns,
            actions=catalogue,
            question=question.strip(),
            extra=extra,
            fields=fields,
        ).rstrip()
        + f"{rules}\n"
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

    **La comparaison est sémantique et non littérale**, et elle le devient parce que rien
    ne valide plus avant l'écriture. Tant qu'un appui séparait la proposition du carnet,
    une redite se voyait et se refusait d'un geste ; maintenant elle s'écrit. « Je dors
    mal » et « je dors mal les soirs de séance tardive » ne sont pas la même chaîne, mais
    la seconde n'apprend rien que la première ne disait — c'est le test de contenance de
    `_echoes`, exactement celui qui écarte déjà les redites du condensé.

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

    seen = list(known or [])
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

        if _echoes(note, seen):
            dropped.append(f"« {note} » : déjà noté.")
            continue

        kept.append(ProposedMemory(topic=normalise_topic(_text(entry.get("topic"))), note=note))
        seen.append(note)

    return reply, kept, dropped


def read_actions(payload: dict[str, Any]) -> list[ProposedAction]:
    """Extrait les actions demandées. **Rien n'est validé ni exécuté ici.**

    Trois fonctions séparées plutôt qu'un `read_reply` qui rendrait cinq valeurs : chacune
    se teste sur son propre cas limite, et l'ajout des actions n'a pas touché une ligne de
    la relecture des notes — qui a ses vingt tests.

    Ce que cette fonction garantit, et c'est tout : ce qui sort est une liste bornée
    d'objets ayant un nom non vide et un dictionnaire d'arguments. Que le nom existe, que
    les arguments soient les bons, que l'action soit permise — c'est l'affaire de
    l'exécuteur, qui connaît le catalogue.

    Un modèle rend parfois un objet là où la consigne demande une liste ; on l'accepte,
    comme pour `remember`. Refuser coûterait l'action *et* l'appel.
    """
    raw = payload.get("actions")
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    kept: list[ProposedAction] = []
    for entry in raw:
        if len(kept) >= MAX_ACTIONS:
            # Un modèle qui en demande plus de cinq n'a pas compris la question — et le
            # tour où il se trompe est celui où on ne veut pas qu'il écrive vingt lignes.
            break
        if not isinstance(entry, dict):
            continue
        name = _text(entry.get("name"))[:MAX_ACTION_NAME]
        if not name:
            continue
        args = entry.get("args")
        kept.append(ProposedAction(name=name, args=args if isinstance(args, dict) else {}))

    return kept


def read_need(payload: dict[str, Any], *, available: list[str]) -> list[str]:
    """Extrait les tranches de contexte réclamées, **filtrées sur ce qui existe**.

    Le filtre est ici et non plus haut, parce qu'il est la garantie de `IA-09` : le modèle
    ne choisit pas ce qu'on lui envoie, il choisit dans ce qu'on lui a dit pouvoir
    demander. Un nom inventé ne devient pas une lecture de fichier.
    """
    raw = payload.get("need")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    allowed = set(available)
    kept: list[str] = []
    for entry in raw:
        name = _text(entry)[:MAX_ACTION_NAME]
        if name in allowed and name not in kept:
            kept.append(name)
        if len(kept) >= MAX_NEED:
            break
    return kept


def read_title(payload: dict[str, Any], *, fallback: str) -> str:
    """Le nom du fil, ou le repli si le modèle n'en a pas rendu d'utilisable.

    Le repli est la question elle-même, tronquée : il vaut toujours mieux qu'un titre vide,
    et c'est ce sur quoi on retrouve un fil trois mois plus tard.
    """
    title = " ".join(_text(payload.get("title")).split())[:MAX_TITLE]
    return title or fallback


__all__ = [
    "INSTRUCTION",
    "MAX_REPLY",
    "MIN_NOTE",
    "build_prompt",
    "read_actions",
    "read_need",
    "read_reply",
    "read_title",
]
