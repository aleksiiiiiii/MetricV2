"""Moteur d'assiduité multi-pistes (spec `HEAT` v2).

**Principe directeur de toute la spec** : une heatmap ne mesure pas l'activité, elle
mesure le respect d'un engagement. Un jour vide n'est un échec que si quelque chose était
attendu ce jour-là.

Six modules, et la frontière entre les deux premiers est ce qui rend la justesse
vérifiable :

| Module | Rôle |
|---|---|
| `engine` | **juge** — pur, sans fichier ni horloge. Toute règle d'assiduité vit ici |
| `grids` | **coud** — rassemble les ingrédients, appelle le moteur, met en forme |
| `sources` | registre des sources : une source rend un nombre par jour, rien d'autre |
| `service` | cycle de vie des pistes, cadences versionnées, jours neutralisés |
| `cache` | mémorisation des grilles, invalidée par la version de leurs sources |
| `router` | les endpoints du §8 |
"""

from app.domains.heatmap.router import router

__all__ = ["router"]
