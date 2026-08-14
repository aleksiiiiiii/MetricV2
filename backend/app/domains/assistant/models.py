"""Modèle CSV de la mémoire de santé (`IA-10`, `IA-11`).

`insights/memory.csv` : id, created, topic, note, source

**Un carnet, pas une mesure.** Ce fichier appartient à la famille *planning* du §2 de
`docs/etat-du-projet.md` : toutes ses colonnes portent un défaut, et une ligne abîmée dans
un tableur rend le carnet incomplet, jamais l'écran en `502`.

## Ce qu'on y écrit, et ce qu'on n'y écrit pas

Ce que **l'utilisateur a dit** et qu'aucun fichier ne porte : une blessure, un sommeil qui
se dégrade, un traitement en cours, une contrainte de travail, une préférence
d'entraînement.

Jamais ce que les CSV savent déjà. Une note qui figerait « 2,4 séances par semaine » serait
fausse le mois suivant et contredirait le condensé envoyé au modèle, lequel est recalculé à
chaque question. La mémoire sert exactement à ce que la mesure ne peut pas dire — et
l'inverse est vrai aussi, ce qui est la raison de les séparer.

## Pourquoi un fichier plutôt qu'un champ de réglage

Parce qu'il doit rester lisible dans un tableur dans dix ans, comme le reste. Une blessure
notée en mars 2026 explique une baisse de volume en avril mieux qu'aucun graphique, et cette
lecture-là se fait souvent longtemps après, hors de l'application.
"""

from __future__ import annotations

from app.storage.model import CsvDate, CsvDateTime, CsvModel

#: Sujets proposés à l'écran et suggérés au modèle.
#:
#: **Ouverts, pas fermés** : la colonne accepte n'importe quel texte. Une liste close
#: obligerait à ranger « je travaille de nuit trois semaines sur quatre » dans une case
#: prévue pour autre chose, et c'est précisément le genre de fait que la mémoire existe
#: pour porter. Ceux-ci ne sont que les plus fréquents, offerts en un appui.
TOPICS: tuple[str, ...] = (
    "blessure",
    "douleur",
    "sommeil",
    "traitement",
    "allergie",
    "contrainte",
    "préférence",
    "autre",
)

DEFAULT_TOPIC = "autre"

#: Longueur d'une note. Large — c'est du texte libre écrit par un humain — mais bornée :
#: le carnet entier part dans chaque question, et cinquante notes de mille signes
#: rempliraient la consigne à elles seules.
MAX_NOTE = 400
MAX_TOPIC = 40


def normalise_topic(raw: str) -> str:
    """Nettoie un sujet sans le contraindre à la liste.

    Rend le sujet en minuscules, tronqué. Vide, il retombe sur `autre` : une note sans
    sujet reste une note, et la perdre pour un champ de rangement serait absurde.
    """
    cleaned = raw.strip().lower()[:MAX_TOPIC]
    return cleaned or DEFAULT_TOPIC


class MemoryRow(CsvModel):
    """Une note de mémoire. `insights/memory.csv`."""

    #: Identifiant stable, et non la position : l'écran corrige et retire des lignes, et
    #: le modèle cite parfois une note dans sa réponse.
    id: str = ""
    created: CsvDate = None
    #: Sujet libre — voir `TOPICS` pour les plus fréquents.
    topic: str = DEFAULT_TOPIC
    note: str = ""
    #: `ai` quand la note a été **proposée** par l'assistant puis validée, `manual` quand
    #: elle a été écrite à la main. L'origine reste lisible jusque dans le fichier, comme
    #: pour un repas ou une séance (`IMP-05`).
    source: str = "manual"


# ── Les fils de discussion ────────────────────────────


#: Longueur d'un titre de fil. Cinq mots tiennent dedans, et c'est ce qu'on demande au
#: modèle : un fil nommé « Discussion du 7 août » ne se retrouve pas, « Stagnation du
#: développé couché » si.
MAX_TITLE = 80

#: Longueur d'un message stocké. La question est déjà bornée à `MAX_QUESTION` et la
#: réponse à `MAX_REPLY` ; cette borne-ci est la ceinture du fichier, pas du dialogue.
MAX_CONTENT = 4000


class ThreadRow(CsvModel):
    """Un fil de discussion. `assistant/threads.csv`.

    Famille *planning* du §2 de `docs/etat-du-projet.md` : toutes les colonnes portent un
    défaut, et une ligne abîmée dans un tableur coûte un fil, jamais un écran en `502`.
    """

    #: Identifiant stable, et non la position : les fils se suppriment, et un message
    #: doit rester rattaché au sien après la disparition d'un autre.
    id: str = ""
    #: Horodatés avec leur décalage, comme une prise d'eau : c'est ce qui range les fils
    #: dans le bon ordre quel que soit le fuseau de lecture.
    created: CsvDateTime = None
    #: Bougé à chaque message. C'est sur lui que la liste est triée — un fil rouvert
    #: remonte, ce qu'une date de création ne dirait pas.
    updated: CsvDateTime = None
    title: str = ""


class MessageRow(CsvModel):
    """Un tour de conversation. `assistant/messages.csv`.

    Un seul fichier pour tous les fils. Le lire en entier pour en afficher un seul est
    largement tenable à l'échelle d'un carnet personnel ; le jour où ça pèse, la migration
    est un partitionnement par année et non un changement de forme.
    """

    thread_id: str = ""
    #: Rang dans le fil, à partir de 0. Il ordonne les messages sans dépendre de
    #: l'horodatage, qui peut se répéter à la seconde près.
    seq: int = 0
    role: str = "user"
    content: str = ""
    created: CsvDateTime = None
    #: Les actions du tour, en JSON, avec leur résultat. Vide pour un message de
    #: l'utilisateur. C'est ce qui permet, en rouvrant un fil, de réafficher « j'ai
    #: ajouté … » et de proposer encore l'annulation.
    actions: str = ""
    #: Le condensé factuel envoyé au modèle pour produire **ce** message (`IA-09`), une
    #: ligne par élément, séparées par `\n`.
    #:
    #: Rangé avec la réponse et non recalculé à la lecture : le condensé dépend des
    #: chiffres du jour où la question a été posée. Le refabriquer trois semaines plus
    #: tard rendrait un contexte plausible, différent de celui qui a réellement servi —
    #: soit exactement ce que `IA-09` existe pour empêcher.
    context: str = ""
