"""Domaine Activité — courses, séances, exercices (`ACT-01` → `ACT-18`).

Squelette : les endpoints de ce domaine sont construits au lot L05. Le routeur existe
dès maintenant pour que le découpage par domaine (`API-01`) soit réel et que chaque lot
n'ait qu'à y déposer ses routes.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/activity", tags=["activité"])
