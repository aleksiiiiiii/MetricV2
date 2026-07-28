"""Agrégats du tableau de bord (`AGG-01` → `AGG-04`).

Le seul domaine qui ne possède aucun fichier. Il lit ceux des autres et assemble ; toute
règle de calcul reste chez le domaine qui la détient.
"""

from app.domains.aggregates.router import router

__all__ = ["router"]
