"""Moteur d'assiduité multi-pistes (spec `HEAT` v2).

Lot L09 : le modèle de piste et son cycle de vie — sources, cadences versionnées, jours
neutralisés, amorçage. Le calcul des états `off` / `missed` / `done` / `bonus` et les
statistiques arrivent au lot L10.

**Principe directeur de toute la spec** : une heatmap ne mesure pas l'activité, elle
mesure le respect d'un engagement. Un jour vide n'est un échec que si quelque chose était
attendu ce jour-là.
"""

from app.domains.heatmap.router import router

__all__ = ["router"]
