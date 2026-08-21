"""Modèle CSV de la lecture du jour. `insights/brief.csv`.

**Un cache daté, pas une mesure.** Ce fichier appartient à la famille *planning* du §2 de
`docs/etat-du-projet.md` : toutes ses colonnes portent un défaut, et une ligne abîmée dans
un tableur coûte la lecture d'une journée, jamais un écran en `502`.

## Une journée, une ligne

`day` est la clé naturelle du fichier. Deux lignes pour le même jour rendraient « la
lecture du 19 août » ambiguë, et c'est exactement la règle que suit déjà le bilan
hebdomadaire avec sa semaine.

## Pourquoi le fil est rangé ici

`thread_id` désigne la discussion ouverte le jour où l'on a répondu à cette lecture-là.
Elle est **vide tant que personne n'a répondu** : semer un fil à la génération remplirait
« Discussions » d'une entrée quotidienne que personne n'a lue. La colonne dit donc deux
choses d'un coup — où continuer, et si la lecture a servi.
"""

from __future__ import annotations

from app.storage.model import CsvDate, CsvDateTime, CsvModel

#: Longueur du message rendu. Une carte d'accueil, pas un bilan : au-delà, il faut faire
#: défiler l'écran qu'on ouvre le plus souvent pour lire une phrase qu'on n'a pas demandée.
MAX_MESSAGE = 600

#: Longueur du condensé rangé avec la lecture.
#:
#: Il est **rangé et non recalculé**, pour la raison qui vaut déjà dans `MessageRow` : le
#: condensé dépend des chiffres du jour où la lecture a été écrite, et le relire demain
#: publierait des faits que le modèle n'a jamais vus.
MAX_BASIS = 4000


class BriefRow(CsvModel):
    """Une lecture du jour. `insights/brief.csv`."""

    #: Le jour commenté. Clé naturelle du fichier.
    day: CsvDate = None
    created: CsvDateTime = None
    message: str = ""
    #: Le condensé réellement envoyé au modèle, une ligne par élément.
    basis: str = ""
    #: Le fil ouvert pour répondre à cette lecture. Vide tant que personne n'a répondu.
    thread_id: str = ""
    #: `ai` — il n'y a pas d'autre source aujourd'hui, mais la colonne existe comme
    #: partout ailleurs : l'origine d'une ligne reste lisible jusque dans le tableur.
    source: str = "ai"
