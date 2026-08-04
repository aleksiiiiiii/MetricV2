"""Couche IA OpenRouter (`IA-01` → `IA-07`).

Domaine sans fichier CSV : il ne relève rien, il interprète. Les quatre pièces sont
`client.py` (le transport), `catalogue` et `service.py` (quel modèle, et quand renoncer),
`extract.py` (lire un JSON dans de la prose) et `images.py` (préparer une photo).
"""

from __future__ import annotations

from app.domains.ai.router import router
from app.domains.ai.service import AiProvider, AiService

__all__ = ["AiProvider", "AiService", "router"]
