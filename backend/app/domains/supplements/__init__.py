"""Domaine Suppléments (`SUP-01` → `SUP-06`).

La colonne `frequency` du planning porte la cadence (`HEAT-23`) : un seul endroit décrit
« je prends de la whey un jour sur deux », et la heatmap ne pourra pas en diverger.
"""

from app.domains.supplements.router import router

__all__ = ["router"]
