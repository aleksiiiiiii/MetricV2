"""Import Apple Fitness par capture d'écran (`IMP-01` → `IMP-06`).

Domaine sans fichier à lui : il n'écrit que dans `activity/runs.csv` et
`activity/workouts.csv`, par les services du domaine Activité. Ce qui lui appartient en
propre, c'est la lecture d'une capture et le moment où l'écriture devient légitime.
"""

from __future__ import annotations

from app.domains.imports.router import router

__all__ = ["router"]
