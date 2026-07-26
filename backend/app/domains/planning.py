"""Planning sport et export iCal (`PLAN-01` → `PLAN-06`).

Squelette : les endpoints de ce domaine sont construits au lot L13. Le routeur existe
dès maintenant pour que le découpage par domaine (`API-01`) soit réel et que chaque lot
n'ait qu'à y déposer ses routes.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/planning", tags=["planning"])
