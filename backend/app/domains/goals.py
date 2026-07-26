"""Objectifs IA et bilan hebdomadaire (`GOAL-01` → `GOAL-06`, `IA-08`).

Squelette : les endpoints de ce domaine sont construits au lot L14. Le routeur existe
dès maintenant pour que le découpage par domaine (`API-01`) soit réel et que chaque lot
n'ait qu'à y déposer ses routes.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/goals", tags=["objectifs"])
