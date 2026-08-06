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

from app.storage.model import CsvDate, CsvModel

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
