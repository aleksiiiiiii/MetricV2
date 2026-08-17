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
from datetime import date
from typing import Any, NamedTuple

from app.domains.assistant.models import MAX_CONTENT, MAX_NOTE, MAX_TITLE, normalise_topic
from app.domains.assistant.schemas import (
    MAX_ACTION_NAME,
    MAX_ACTIONS,
    MAX_NEED,
    MAX_NEED_NAME,
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

#: La consigne système, envoyée à chaque appel.
#:
#: **Le ton est un réglage, et il a été choisi.** Un assistant neutre qui récite des
#: chiffres est un tableau de bord qui parle ; ce qu'on veut est un coach qui pousse. D'où
#: l'encouragement et l'exigence de performance, explicites plutôt qu'espérés.
#:
#: Deux bornes tiennent ce ton, et elles ne sont pas décoratives :
#:
#: **L'encouragement s'appuie sur un chiffre servi, jamais sur une formule.** « Belle
#: progression » sur une semaine sans séance est une valeur inventée — la même faute qu'un
#: zéro affiché pour une mesure absente, et elle coûte plus cher ici parce qu'un compliment
#: faux décrédibilise les vrais.
#:
#: **L'exigence s'arrête net devant une douleur.** C'est le seul endroit où pousser fait un
#: dégât réel, et c'est exactement ce que `IA-12` existe pour empêcher. La règle est donc
#: rappelée *après* l'exigence, et elle la contredit explicitement.
INSTRUCTION = (
    "Tu es le coach personnel de cette application de suivi sportif — pas un tableau de "
    "bord qui parle, un coach qui pousse. "
    "Tu réponds uniquement par un objet JSON, sans phrase avant ni après, sans bloc de "
    "code. "
    "Tu vises la performance : tu donnes le prochain palier, tu demandes mieux que la "
    "dernière fois, et tu dis franchement quand quelque chose stagne. "
    "Tu es chaleureux et encourageant : tu nommes ce qui a été accompli avant de dire ce "
    "qui vient, tu traites une séance manquée comme une information et jamais comme une "
    "faute, et tu finis sur ce qui est à portée. "
    "Mais ton encouragement s'appuie toujours sur un chiffre qui t'a été donné, jamais sur "
    "une formule toute faite : félicite pour un progrès réel et cite-le, ou tais-toi. Un "
    "compliment inventé décrédibilise tous les autres. "
    "Tu n'es pas médecin : tu ne poses aucun diagnostic, tu ne recommandes aucun "
    "traitement, tu n'interprètes aucun symptôme. Devant une douleur, une blessure ou un "
    "trouble, **tout ce qui précède sur la performance s'arrête** : tu le dis franchement, "
    "tu renvoies vers un professionnel de santé, et tu ne pousses à rien — puis tu t'en "
    "tiens à ce que les données montrent."
)

_TEMPLATE = """Réponds à la question en t'appuyant sur ce qui suit, et sur rien d'autre.

{profile}## Ce que disent les données

{context}

## Ce que tu sais de moi

{memory}

{history}{actions}## Question

{question}

## Réponse attendue

{shape}

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

# ── L'ordre des champs, et pourquoi il est ce qu'il est ──
#
# **`need` et `actions` précèdent `reply`, délibérément.** Un modèle écrit son JSON de
# gauche à droite : quand `need` arrive en premier, le serveur sait **avant** le premier
# caractère de la réponse si cette passe sera remplacée par une seconde. C'est ce qui
# permet de diffuser `reply` au fil de l'eau sans jamais avoir à l'effacer — voir
# `stream_reply` et §7.1 du plan de coaching.
#
# Le bénéfice est double et le second ne doit rien au flux : décider ce qu'on écrit avant
# de rédiger sert la règle « ne parle dans "reply" que des actions réellement mises ».
#
# Rien ne *garantit* cet ordre côté modèle. Le lot 5 le garantira par `json_schema` ; en
# attendant, un modèle qui ne le respecte pas coûte la diffusion de cette passe, jamais sa
# justesse — le serveur ne diffuse que ce qu'il peut prouver final.

#: La syntaxe des périodes, décrite au modèle (lot 12.B).
#:
#: **Sans cette description, la capacité n'existe pas.** Le code sait lire
#: `repas_du_jour@2026-08-15` depuis ce lot ; un modèle à qui personne ne l'a dit ne
#: l'écrira jamais. C'est le même constat qu'au lot où le catalogue d'actions a été généré
#: depuis les schémas : une possibilité non décrite est une possibilité morte.
#:
#: L'exemple est donné en toutes lettres plutôt qu'en gabarit abstrait — cinq échecs
#: d'affilée sur un `kind` décrit comme « texte » ont montré ce que coûte une description
#: qui laisse deviner la forme.
_PERIODS = """Par défaut une tranche porte sur aujourd'hui. Pour un autre jour, ajoute
« @ » et la date : "repas_du_jour@2026-08-15". Pour une semaine entière, ajoute
« @semaine- » et n'importe quelle date de cette semaine : "repas_du_jour@semaine-2026-08-12"
— tu recevras les sept jours, un par un. Les dates s'écrivent AAAA-MM-JJ ; une date que je
ne sais pas lire ne rend aucune tranche, elle ne retombe pas sur aujourd'hui."""

#: Description de `need`. En tête parce que c'est la première décision à prendre.
_NEED_FIELD = """- "need" : ce qui te manque pour répondre ou pour agir, à choisir dans la liste des
  tranches ci-dessus. Ne le remplis que si tu ne peux pas t'en passer. Tu ne l'obtiendras
  qu'une fois, alors demande tout d'un coup."""

#: Description de `actions`.
#:
#: Rédigée en « je te demande / tu fais » et non en « tu peux » : un modèle à qui on offre
#: une possibilité la prend, et la plupart des questions n'appellent aucune écriture. La
#: liste vide doit être présentée comme le cas normal, sinon chaque « où j'en suis ? »
#: repart avec une séance ajoutée.
_ACTIONS_FIELD = """- "actions" : ce que je te demande d'écrire dans mes données. **Liste vide le plus
  souvent** — une question est une question, pas une instruction. N'agis que si je te le
  demande explicitement, dans ce message-ci."""

_REPLY_FIELD = """- "reply" : ta réponse, en français. **Sa longueur suit ce que je demande** — un chiffre se
  rend en une phrase, un plan ou une analyse se développe autant qu'il le faut. Cite les
  chiffres ci-dessus quand ils répondent ; dis que tu ne sais pas quand ils ne disent rien
  là-dessus."""

_REMEMBER_FIELD = """- "remember" : ce que **je viens de t'apprendre sur moi** et qui vaudra encore dans six
  mois — une blessure, un sommeil, un traitement, une contrainte. Liste vide le plus
  souvent, et c'est le cas normal."""

_TITLE_FIELD = '- "title" : cinq mots qui nomment cette discussion, pour la retrouver plus tard.'

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
    profile: list[str] | None = None,
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

    **L'ordre des champs est porteur** et non cosmétique : `need` et `actions` d'abord, la
    réponse ensuite. Voir la note qui précède `_NEED_FIELD` — c'est ce qui rend la
    diffusion au fil de l'eau possible sans effacement.

    `profile` est **en tête**, avant les chiffres : ce sont les constantes qui décident de
    ce qu'on peut conseiller — un plan qui suppose un rack quand il n'y en a pas ne vaut
    rien, quels que soient les chiffres qui le précèdent. Vide, la rubrique **disparaît**
    au lieu d'annoncer qu'elle est vide : un titre suivi de rien apprend qu'il n'y a rien à
    savoir, ce qui est faux — il n'y a rien de *saisi*.
    """
    who = ""
    if profile:
        listed = "\n".join(f"- {line}" for line in profile)
        who = f"## Ce que je suis\n\n{listed}\n\n"

    turns = ""
    if history:
        lines = "\n".join(
            f"- {'Moi' if role == 'user' else 'Toi'} : {content}" for role, content in history
        )
        turns = f"## Ce qu'on s'est déjà dit\n\n{lines}\n\n"

    # Le squelette et les descriptions sont construits **ensemble**, dans le même ordre :
    # deux listes qui divergeraient décriraient un champ à une place qu'il n'occupe pas.
    catalogue = ""
    rules = ""
    shape: list[str] = []
    fields: list[str] = []

    if actions:
        listed = "\n".join(f"- {line}" for line in actions)
        available = ", ".join(slices or []) or "aucune"
        catalogue = (
            f"## Ce que tu peux faire dans mes données\n\n{listed}\n\n"
            f"Tranches de contexte disponibles à la demande : {available}.\n\n"
            f"{_PERIODS}\n\n"
        )
        shape += ['"need": []', '"actions": []']
        fields += [_NEED_FIELD, _ACTIONS_FIELD]
        rules = f"\n{_ACTION_RULES}"

    shape += ['"reply": "…"', '"remember": [{"topic": "…", "note": "…"}]']
    fields += [_REPLY_FIELD, _REMEMBER_FIELD]

    if naming:
        shape.append('"title": "…"')
        fields.append(_TITLE_FIELD)

    return (
        _TEMPLATE.format(
            context="\n".join(f"- {line}" for line in context) or "- Aucune donnée relevée.",
            memory="\n".join(f"- {line}" for line in memory) or "- Rien de noté pour l'instant.",
            profile=who,
            history=turns,
            actions=catalogue,
            question=question.strip(),
            shape="{" + ", ".join(shape) + "}",
            fields="\n".join(fields),
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


#: Terminaisons françaises retirées avant de comparer deux notes, des plus longues aux
#: plus courtes — sans quoi « séances » perdrait son `s` et garderait son `e`.
#:
#: Une liste courte et assumée plutôt qu'un vrai raciniseur : les cas visés sont le pluriel
#: et la conjugaison d'un verbe recopié, pas l'analyse morphologique du français. Une
#: dépendance de racinisation coûterait un paquet de plus pour attraper les mêmes redites.
_ENDINGS = (
    "ements",
    "ement",
    "aient",
    "ions",
    "ants",
    "ent",
    "ait",
    "ons",
    "ers",
    "es",
    "s",
    "t",
    "e",
)

#: Longueur en deçà de laquelle on ne coupe plus. Trois lettres suffisent à distinguer deux
#: mots ; en dessous, on rapprocherait n'importe quoi.
_MIN_STEM = 3


def _stem(word: str) -> str:
    """Racine grossière d'un mot : « dors » et « dort » → « dor », « séances » → « séanc ».

    **Appliquée jusqu'à point fixe, et c'est la correction qui compte.** Une passe unique
    n'est pas idempotente : « nuits » perdrait son `s` et rendrait « nuit », que le même
    raciniseur réduirait pourtant à « nui » s'il le rencontrait au singulier. Les deux
    formes ne se seraient donc **pas** reconnues — soit exactement le défaut qu'on répare.

    La sur-racinisation est assumée : « base » et « bas » se confondent. Le risque qu'elle
    fait courir est borné par la nature du test appelant, qui exige que **tous** les mots
    porteurs d'une note se retrouvent dans une même ligne. Une collision isolée ne suffit
    donc pas à écarter une note ; il faudrait qu'elles collisionnent toutes.
    """
    current = word
    while True:
        for ending in _ENDINGS:
            if current.endswith(ending) and len(current) - len(ending) >= _MIN_STEM:
                current = current[: -len(ending)]
                break
        else:
            return current


def _significant(text: str) -> set[str]:
    """Mots porteurs de sens d'une phrase, accents, ponctuation et terminaisons retirés.

    Les mots courts partent avec la ponctuation : « de », « la », « par » se retrouvent
    dans n'importe quelle paire de phrases françaises et rendraient toute comparaison
    positive. Les nombres aussi — c'est le vocabulaire qui distingue « douleur au genou »
    d'une ligne de statistiques, pas les chiffres.

    **La racinisation a été ajoutée sur constat.** La comparaison portait sur des formes
    exactes : « dort » ≠ « dors », « séances » ≠ « séance ». Une conjugaison et un pluriel
    suffisaient à faire passer une redite, et le carnet se remplissait de variantes de la
    même phrase — ce que `IA-10` voulait précisément éviter en le laissant s'écrire seul.
    """
    folded = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(char if char.isalnum() else " " for char in folded if not _is_accent(char))
    return {_stem(word) for word in stripped.split() if len(word) >= 4 and not word.isdigit()}


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

    ## Ce que ce test **ne** sait pas faire, et il faut le savoir en le lisant

    Il compare du vocabulaire, racines comprises depuis le jalon 6. Il attrape donc la
    redite franche et sa variante conjuguée. Il ne rapproche **pas** deux phrases qui disent
    la même chose avec d'autres mots : « Dors mal les nuits qui suivent une séance après
    20 h » et « Dort mal les soirs où l'entraînement a lieu tard » ne partagent ni
    « nuits »/« soirs » ni « séance »/« entraînement », et aucune racinisation ne les
    rapprochera.

    C'est le cas qui a motivé la trouvaille du jalon 2, et il reste **ouvert**. Le fermer
    demande une comparaison sémantique — un modèle juge ou des plongements —, donc un lot à
    lui seul. Mieux vaut un test qui dit ce qu'il couvre qu'un test dont on croit qu'il
    couvre tout.
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


class Need(NamedTuple):
    """Une tranche réclamée, avec la période qu'elle couvre (lot 12.B).

    `day` à `None` veut dire aujourd'hui — le cas de très loin le plus fréquent, et celui
    qui existait seul avant ce lot. `week` demande les sept jours de la semaine contenant
    `day`, servis un par un : on ne fabrique **aucun agrégat** hebdomadaire ici, ce serait
    un calcul, et `context.py` n'en fait pas.
    """

    name: str
    day: date | None = None
    week: bool = False

    @property
    def label(self) -> str:
        """Ce que l'étape annonce à l'écran — lisible, pas la syntaxe brute."""
        if self.day is None:
            return self.name
        quand = f"semaine du {self.day:%d/%m}" if self.week else f"{self.day:%d/%m}"
        return f"{self.name} ({quand})"


def _read_period(suffix: str) -> tuple[date, bool] | None:
    """Analyse `2026-08-15` ou `semaine-2026-08-10`. `None` si ce n'est pas une date.

    **Rien n'est deviné**, et surtout pas un repli sur aujourd'hui : servir les chiffres du
    jour à qui a demandé le 15/08 attribuerait à cette date des mesures qui n'y ont pas eu
    lieu. C'est une valeur inventée, en pire — elle est datée. Une période illisible ne
    rend donc pas de tranche du tout, et le modèle peut redemander.
    """
    week = suffix.startswith("semaine-")
    raw = suffix.removeprefix("semaine-")
    try:
        return date.fromisoformat(raw), week
    except ValueError:
        return None


def read_need(payload: dict[str, Any], *, available: list[str]) -> list[Need]:
    """Extrait les tranches de contexte réclamées, **filtrées sur ce qui existe**.

    Le filtre est ici et non plus haut, parce qu'il est la garantie de `IA-09` : le modèle
    ne choisit pas ce qu'on lui envoie, il choisit dans ce qu'on lui a dit pouvoir
    demander. Un nom inventé ne devient pas une lecture de fichier.

    **La date, elle, est libre — et c'est sans conséquence sur cette garantie.** Le nom
    reste choisi dans la liste fermée ; seule la période varie, et elle ne désigne aucun
    fichier. `repas_du_jour@2026-08-15` lit ce que `repas_du_jour` lit déjà, un autre jour.
    """
    raw = payload.get("need")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    allowed = set(available)
    kept: list[Need] = []
    seen: set[str] = set()
    for entry in raw:
        text = _text(entry)[:MAX_NEED_NAME]
        name, _, suffix = text.partition("@")
        if name not in allowed or text in seen:
            continue

        if not suffix:
            kept.append(Need(name))
        else:
            period = _read_period(suffix)
            if period is None:
                continue
            day, week = period
            kept.append(Need(name, day, week))

        seen.add(text)
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
    "Need",
    "build_prompt",
    "read_actions",
    "read_need",
    "read_reply",
    "read_title",
]
