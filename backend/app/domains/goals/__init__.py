"""Domaine Objectifs et bilan hebdomadaire (`GOAL-01` → `GOAL-06`, `IA-08`).

Un seul routeur, monté dans le groupe protégé de `app/domains/api.py`.

Ce domaine ne possède aucune métrique : il en désigne cinq dans le registre
`aggregates.METRICS`, qui en détient les définitions et les sert déjà aux séries
génériques. Voir `metrics.py` pour ce que le domaine ajoute, et `progress.py` — qui ne lit
rien — pour ce qu'« avancer vers une cible » veut dire ici.
"""

from app.domains.goals.router import router

__all__ = ["router"]
