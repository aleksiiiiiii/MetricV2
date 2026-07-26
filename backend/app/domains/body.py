"""Domaine Corps — poids et mensurations (`BODY-01` → `BODY-10`).

Squelette : les endpoints de ce domaine sont construits au lot L04. Le routeur existe
dès maintenant pour que le découpage par domaine (`API-01`) soit réel et que chaque lot
n'ait qu'à y déposer ses routes.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/body", tags=["corps"])
