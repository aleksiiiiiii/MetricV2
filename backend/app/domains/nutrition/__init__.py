"""Domaine Nutrition — repas, photos, macros, favoris (`NUT-01` → `NUT-10`).

`NUT-04` (analyse IA de l'assiette) et `NUT-11` (base produits) ne sont pas ici :
l'analyse arrive au lot L12, la base produits est hors périmètre v1.
"""

from app.domains.nutrition.router import router

__all__ = ["router"]
