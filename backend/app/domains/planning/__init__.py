"""Domaine Planning sport (`PLAN-01` → `PLAN-06`).

Deux routeurs sortent d'ici, et il faut les monter tous les deux : `router` dans le
groupe protégé de `app/domains/api.py`, `calendar_router` au niveau de l'application.
Le second publie le flux `.ics` abonnable, qu'un client de calendrier va chercher sans
pouvoir porter d'en-tête `Authorization` — voir `router.py` pour ce que cela impose.
"""

from app.domains.planning.router import calendar_router, router

__all__ = ["calendar_router", "router"]
