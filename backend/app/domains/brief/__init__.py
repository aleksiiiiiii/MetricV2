"""Domaine Lecture du jour.

Une phrase par journée, écrite par le modèle à partir du condensé factuel que l'assistant
assemble déjà, rangée dans `insights/brief.csv`, servie au tableau de bord.

Ce domaine ne possède **aucun chiffre**. Il ne lit pas les pesées, ne compte pas les
séances et ne calcule aucun ratio : `assistant.context.build` lui donne les faits, les
services de chaque domaine les détiennent. Ce qu'il ajoute est une lecture datée, et le
fil dans lequel on lui répond.
"""

from app.domains.brief.router import router

__all__ = ["router"]
