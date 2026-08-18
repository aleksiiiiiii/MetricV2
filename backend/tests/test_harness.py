"""Le harnais lui-même — ce dont la batterie dépend pour dire vrai.

Un test qui vérifie la batterie plutôt que l'application, et il a une raison précise
d'exister : une exécution qui chevauchait minuit rendait une vingtaine d'échecs sur des
tests datés, sans qu'une ligne de code applicatif ait bougé. Les échecs se lisaient comme
une régression et n'en étaient pas — le pire genre de rouge, celui qui fait chercher au
mauvais endroit.

Le gel de l'horloge vit dans `conftest.py`, à l'import. Ce fichier le tient : sans lui, la
protection pourrait disparaître dans un déplacement de fixture et la fragilité reviendrait
sans que rien ne la signale, jusqu'à la prochaine exécution nocturne.
"""

from __future__ import annotations

import time

from app.core.dates import now_local, today_local


def test_le_jour_ne_change_pas_en_cours_de_batterie() -> None:
    """La cause exacte des dix-huit échecs.

    Chaque fichier calcule son `TODAY = today_local()` **à l'import** ; l'application relit
    l'horloge à chaque appel pendant la course. Passé 00:00, les deux ne parlaient plus du
    même jour, et les tests datés comparaient hier à aujourd'hui.
    """
    premier = today_local()
    time.sleep(0.05)

    assert today_local() == premier


def test_l_instant_courant_ne_bouge_pas_non_plus() -> None:
    """Le gel porte sur l'instant et non sur la seule date.

    Geler la date en laissant l'heure avancer aurait rendu la fragilité plus rare sans la
    supprimer : deux horodatages écrits à cheval sur minuit auraient encore porté deux
    jours différents dans le même test.
    """
    premier = now_local()
    time.sleep(0.05)

    assert now_local() == premier


def test_l_instant_gele_reste_celui_du_demarrage_reel() -> None:
    """**Pas une date en dur**, et la distinction compte.

    Une date figée changerait aussi le jour de la semaine et la saison, ce qui ferait
    passer ou échouer des cas pour des raisons sans rapport avec ce qu'ils mesurent. Ici on
    ne retire que la dérive : le comportement reste celui d'aujourd'hui, à la seconde près.
    """
    from datetime import datetime

    from app.core.dates import tz

    ecart = abs((datetime.now(tz=tz()) - now_local()).total_seconds())

    # Large : la batterie entière tient en une minute, et cette borne dit seulement que
    # l'instant gelé est celui de *cette* exécution, pas une constante écrite dans le code.
    assert ecart < 3600
