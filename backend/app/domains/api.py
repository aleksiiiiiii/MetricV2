"""Assemblage des routeurs de domaine (`API-01`, `AUTH-05`).

Deux groupes, et la frontière entre eux est la règle de sécurité du projet :

* **public** — la connexion, et rien d'autre. La santé (`API-04`), la documentation
  (`API-05`) et le futur flux iCal protégé par clé (`PLAN-05`) sont déclarés hors de ce
  module, au niveau de l'application.
* **protégé** — tout le reste, derrière une dépendance d'authentification unique.

Poser la protection sur le groupe plutôt que route par route est délibéré : un endpoint
ajouté au lot L07 est protégé parce qu'il est dans le groupe, pas parce que son auteur a
pensé à ajouter un décorateur. L'oubli est structurellement impossible.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import require_auth
from app.domains import (
    activity,
    aggregates,
    ai,
    app_settings,
    assistant,
    auth,
    body,
    goals,
    heatmap,
    hydration,
    imports,
    notifications,
    nutrition,
    planning,
    supplements,
)

#: Routes accessibles sans jeton.
public_router = APIRouter(prefix="/api")
public_router.include_router(auth.router)

#: Routes de données, jeton obligatoire (`AUTH-05`).
protected_router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])

for domain in (
    body,
    activity,
    hydration,
    supplements,
    nutrition,
    aggregates,
    heatmap,
    planning,
    goals,
    imports,
    ai,
    assistant,
    notifications,
    app_settings,
):
    protected_router.include_router(domain.router)


#: Préfixes de domaine qui doivent tous exiger un jeton — sert de garde en test.
PROTECTED_PREFIXES = tuple(
    f"/api{domain.router.prefix}"
    for domain in (
        body,
        activity,
        hydration,
        supplements,
        nutrition,
        aggregates,
        heatmap,
        planning,
        goals,
        imports,
        ai,
        assistant,
        notifications,
        app_settings,
    )
)
