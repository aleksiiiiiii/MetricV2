"""Modèle CSV de la lecture du jour. `insights/brief.csv`.

**Un cache daté, pas une mesure.** Ce fichier appartient à la famille *planning* du §2 de
`docs/etat-du-projet.md` : toutes ses colonnes portent un défaut, et une ligne abîmée dans
un tableur coûte la lecture d'une journée, jamais un écran en `502`.

## Une journée, trois lignes

`day` **et** `slot` forment la clé. Le fichier n'a longtemps porté qu'une lecture par jour,
à six heures ; il en porte trois, parce qu'on ne se pose pas la même question au réveil, à
midi et le soir. Deux lignes pour le même couple rendraient « la lecture de midi du 19
août » ambiguë — c'est la règle que suivait déjà le fichier avec sa seule date.

## Pourquoi le fil est rangé ici

`thread_id` désigne la discussion ouverte le jour où l'on a répondu à cette lecture-là.
Elle est **vide tant que personne n'a répondu** : semer un fil à la génération remplirait
« Discussions » d'une entrée quotidienne que personne n'a lue. La colonne dit donc deux
choses d'un coup — où continuer, et si la lecture a servi.
"""

from __future__ import annotations

from datetime import datetime, time

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


#: Les trois créneaux d'une journée, dans l'ordre où ils viennent.
#:
#: Une lecture par jour ne pouvait dire qu'une chose, et elle la disait à six heures : ce
#: qui est acquis, et le geste du jour. Trois créneaux répondent à trois questions qu'on ne
#: se pose pas au même moment — au réveil « qu'est-ce que je vise », à midi « est-ce que je
#: tiens », le soir « qu'est-ce qui se rattrape encore ».
#:
#: Le prix est **trois appels de modèle par jour au lieu d'un**. Sur les modèles gratuits
#: d'OpenRouter, avec le repli de `ask_json`, c'est le coût assumé de la fonctionnalité.
SLOTS: tuple[str, ...] = ("matin", "midi", "soir")

#: Ce que vaut une cellule `slot` vide.
#:
#: Les lignes écrites avant que la colonne existe sont les lectures de six heures — c'était
#: le seul créneau. Les lire comme `matin` est donc exact, et non un repli de commodité
#: (`STO-04`).
DEFAULT_SLOT = "matin"


#: L'heure locale à partir de laquelle chaque créneau peut être écrit.
#:
#: Six heures : assez tôt pour que la lecture soit là au réveil, assez tard pour que la
#: veille soit close et que les chiffres commentés soient ceux de la bonne journée.
#:
#: Treize heures : le déjeuner est passé, ce qui se suit au fil des heures — repas,
#: protéines, eau — a de quoi être commenté, et il reste l'après-midi pour agir.
#:
#: Dix-neuf heures : la journée a produit ce qu'elle produira, mais il reste assez de
#: soirée pour qu'un geste de rattrapage tienne encore.
#:
#: **Les heures vivent ici et non dans l'ordonnanceur**, parce que le service en a besoin
#: aussi : c'est lui qui décide quel créneau afficher quand l'écran n'en demande aucun.
#: Deux tables donneraient deux idées de « il est midi ».
SLOT_HOURS: dict[str, time] = {
    "matin": time(6, 0),
    "midi": time(13, 0),
    "soir": time(19, 0),
}


def normalise_slot(raw: str) -> str:
    """Ramène une cellule `slot` à l'un des trois créneaux connus."""
    cleaned = raw.strip().lower()
    return cleaned if cleaned in SLOTS else DEFAULT_SLOT


def current_slot(moment: datetime) -> str:
    """Le créneau **en cours** : le dernier dont l'heure est passée.

    Avant six heures, c'est `matin` — et il sera `absent` tant qu'il n'est pas écrit. Rendre
    la lecture du soir de la veille serait montrer un texte qui commente une autre journée
    sur un écran qui affiche celle d'aujourd'hui.
    """
    passed = [name for name in SLOTS if moment.time() >= SLOT_HOURS[name]]
    return passed[-1] if passed else DEFAULT_SLOT


def due_slots(moment: datetime) -> list[str]:
    """Les créneaux dont l'heure est passée, dans l'ordre. Ce que l'ordonnanceur doit
    avoir écrit à cet instant-là."""
    return [name for name in SLOTS if moment.time() >= SLOT_HOURS[name]]


class BriefRow(CsvModel):
    """Une lecture du jour. `insights/brief.csv`."""

    #: Le jour commenté. Avec `slot`, la clé du fichier.
    day: CsvDate = None
    #: Le créneau commenté — `matin`, `midi` ou `soir`. Voir `SLOTS`.
    #:
    #: Vide sur les lignes écrites avant ce lot : elles valent `matin`, et c'est exact.
    slot: str = ""
    created: CsvDateTime = None
    message: str = ""
    #: Le condensé réellement envoyé au modèle, une ligne par élément.
    basis: str = ""
    #: Le fil ouvert pour répondre à cette lecture. Vide tant que personne n'a répondu.
    thread_id: str = ""
    #: `ai` — il n'y a pas d'autre source aujourd'hui, mais la colonne existe comme
    #: partout ailleurs : l'origine d'une ligne reste lisible jusque dans le tableur.
    source: str = "ai"
