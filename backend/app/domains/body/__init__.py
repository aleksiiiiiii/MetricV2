"""Domaine Corps — poids et mensurations (`BODY-01` → `BODY-10`).

Premier domaine construit, et donc **patron de référence** des suivants. Sa structure
est décrite dans `docs/patron-domaine.md` :

    models.py     ce que contient le fichier CSV
    schemas.py    ce qui circule sur l'API, avec ses bornes de vraisemblance
    service.py    les calculs, jamais dans le client
    router.py     les endpoints, minces
"""

from app.domains.body.router import router

__all__ = ["router"]
