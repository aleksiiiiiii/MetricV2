"""Formes échangées pour la lecture du jour.

Trois lectures par jour depuis ce lot — matin, midi, soir. `slot` dit laquelle, et il
vient du serveur : c'est lui qui tient l'heure.

Un objet circule, et son champ décisif est `state`. Il porte la distinction que
l'invariant « aucune valeur inventée » exige ici : **« pas encore écrite » n'est pas « il
n'y a rien à dire »**, et un message vide dirait les deux à la fois.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

#: Les deux états que le serveur connaît.
#:
#: Il n'y en a pas de troisième pour « le modèle a échoué » : un échec est une **erreur**,
#: portée par un code et un message français comme partout ailleurs (`API-07`). En faire un
#: état de la vue obligerait l'écran à décider sur un texte, ce que le §2 interdit.
BriefState = Literal["ready", "absent"]

#: Les trois moments de la journée. Fermé côté API alors que le fichier tolère n'importe
#: quoi : le fichier doit survivre à un tableur, une réponse n'a pas cette excuse.
BriefSlot = Literal["matin", "midi", "soir"]


class BriefView(BaseModel):
    """La lecture du jour, telle que l'écran la reçoit."""

    day: dt.date
    #: Le moment commenté. Rendu par le serveur et **jamais déduit par l'écran** : lui
    #: n'a ni l'horloge ni le fuseau, et deux idées de « il est midi » divergeraient
    #: (`HEAT-32`).
    slot: BriefSlot
    state: BriefState
    #: Vide tant que `state` vaut `absent`. Jamais une phrase de remplacement : l'écran
    #: dit lui-même ce que coûte le prochain geste, comme tous ses autres états vides.
    message: str = ""
    #: Le condensé factuel réellement envoyé au modèle, ligne par ligne (`IA-09`).
    #:
    #: Publié pour la même raison qu'ailleurs : c'est la seule façon de vérifier à l'écran
    #: que les fichiers n'ont pas été envoyés entiers, et de voir sur quoi la lecture
    #: s'appuie. Il est **rangé** avec elle, jamais recalculé — les chiffres d'aujourd'hui
    #: ne sont pas ceux sur lesquels la lecture d'hier a été écrite.
    basis: list[str] = Field(default_factory=list)
    #: Le fil ouvert pour répondre à cette lecture, `null` tant que personne n'a répondu.
    thread_id: str | None = None


class BriefThread(BaseModel):
    """Le fil dans lequel répondre à la lecture du jour.

    Rendu par un `POST` et non par la vue : ouvrir un fil **écrit** deux lignes, et un
    `GET` qui écrirait fausserait le cache autant que la promesse du projet.
    """

    thread_id: str
