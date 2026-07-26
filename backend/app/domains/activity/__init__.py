"""Domaine Activité — courses, séances, exercices (`ACT-01` → `ACT-18`).

Le plus gros domaine du backlog, et la source de six des neuf pistes d'assiduité.
Structure conforme à `docs/patron-domaine.md`, avec un fichier de plus : les agrégats
hebdomadaires vivent dans `stats.py` pour que `service.py` reste lisible.
"""

from app.domains.activity.router import router

__all__ = ["router"]
