"""L'horloge de la batterie, figée pour toute la session.

## Le défaut que ce module répare

Une exécution qui chevauchait minuit rendait une vingtaine d'échecs sur des tests datés,
sans qu'une ligne de code applicatif ait bougé. La cause est un décalage de moment : chaque
fichier de test calcule son `TODAY = today_local()` **à l'import**, tandis que
l'application relit l'horloge à chaque appel pendant la course. Passé 00:00, les deux ne
parlent plus du même jour.

Ces échecs se lisaient comme une régression et n'en étaient pas — le pire genre de rouge,
celui qui fait chercher au mauvais endroit.

## Pourquoi le nom `datetime` et non les fonctions

Les modules qui ont écrit `from app.core.dates import today_local` gardent leur **propre
référence** à la fonction : la remplacer dans `app.core.dates` ne les atteindrait pas. La
fonction, elle, relit `datetime` dans les globales de son module à chaque appel. C'est donc
le seul point de passage qui couvre tous les appelants, présents et à venir.

## Pourquoi l'heure réelle et non une date en dur

Une date figée changerait aussi le jour de la semaine et la saison, ce qui ferait passer ou
échouer des cas pour des raisons sans rapport avec ce qu'ils mesurent. Ici on ne retire que
la **dérive** : le comportement reste exactement celui d'aujourd'hui.

Ce module est importé par `conftest.py`, donc avant la collecte des fichiers de test — et
c'est ce qui garantit que leur `TODAY` lit déjà l'instant gelé.
"""

from __future__ import annotations

import datetime as _stdlib

import app.core.dates as _dates

#: L'instant de démarrage de la batterie. Tout le reste de la session le lira.
FROZEN = _stdlib.datetime.now(tz=_dates.tz())


class FrozenDatetime(_stdlib.datetime):
    """`datetime` dont l'instant courant ne bouge plus."""

    @classmethod
    def now(cls, tz: _stdlib.tzinfo | None = None) -> FrozenDatetime:
        moment = FROZEN if tz is None else FROZEN.astimezone(tz)
        # Reconstruit dans la sous-classe : `datetime.now` promet de rendre `cls`, et
        # `astimezone` rend un `datetime` nu. Sans ça, le typage de la bibliothèque
        # standard est contredit — et un appelant qui compterait sur `cls` aurait tort.
        return cls.fromtimestamp(moment.timestamp(), tz=moment.tzinfo)


_dates.datetime = FrozenDatetime  # type: ignore[attr-defined]
