"""Texte français partagé : comparaison de noms, et écriture des nombres.

Un seul repli, dans un seul module, parce que **deux replis donneraient deux verdicts pour
la même paire de noms** — et que l'un d'eux décide de fusionner deux exercices dans
l'historique, ce que rien ne défait.

Il vit dans `core/` et non dans un domaine pour la raison qui l'a fait sortir du service
Activité : le module qui lit les notes en a besoin, le service qui range les alias aussi,
et se les passer de l'un à l'autre créait un cycle d'imports.
"""

from __future__ import annotations

import unicodedata


def fold(value: str) -> str:
    """Repli d'un nom pour la comparaison : sans accent, sans casse, sans ponctuation.

    C'est ce qui fait que « dev. couché », « Dev Couche » et « développé couché » se
    reconnaissent — trois façons d'écrire le même mouvement sur un carnet, à la main,
    entre deux séries.

    Les espaces multiples sont ramenés à un seul : `« développé  couché »` et
    `« développé couché »` sont le même exercice, et une note manuscrite recopiée par un
    modèle porte des espaces là où l'œil n'en voit pas.

    **Ce n'est pas une distance d'édition.** Le repli rend deux graphies comparables, il
    ne rend pas deux noms « proches » égaux : « développé couché » et « développé
    incliné » restent distincts, et c'est voulu.
    """
    decomposed = unicodedata.normalize("NFD", value)
    without_accents = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    keepable = "".join(c for c in without_accents.casefold() if c.isalnum() or c.isspace())
    return " ".join(keepable.split())


def fr(value: float) -> str:
    """Un nombre tel qu'il se lit en français, sans décimale inutile.

    Une décimale sous cent, aucune au-delà : « 2,4 séances » et « 78,5 kg » ont besoin de
    la leur, « 1 857,1 ml » n'a besoin de rien. La virgule est décimale — ces chaînes
    s'affichent telles quelles (`API-07`), elles ne sont pas un format d'échange.

    **Il vit ici et non dans `goals/progress.py`, où il est né**, pour la raison écrite en
    tête de ce module : les agrégats en ont besoin pour dire ce qu'il reste à boire, et
    `goals` importe déjà `aggregates` pour le registre des métriques. L'y laisser aurait
    posé un cycle, ou une seconde virgule décimale quelque part.
    """
    rounded = round(value, 0 if abs(value) >= 100 else 1)
    text = f"{rounded:g}"
    return text.replace(".", ",")
