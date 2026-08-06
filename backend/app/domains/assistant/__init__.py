"""Domaine Assistant — conversation contextuelle et mémoire de santé (`IA-09` → `IA-12`).

Un seul routeur, monté dans le groupe protégé de `app/domains/api.py`.

Ce domaine ne calcule rien et ne possède qu'un fichier : `insights/memory.csv`, le carnet.
Tout ce qu'il raconte au modèle vient des services qui en détiennent la règle — voir
`context.py`, qui assemble sans recalculer, et `conversation.py`, qui ne lit rien.
"""

from app.domains.assistant.router import router

__all__ = ["router"]
