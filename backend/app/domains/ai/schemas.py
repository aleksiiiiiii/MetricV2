"""Formes échangées par la couche IA (`IA-02`, `IA-07`)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AiStatus(BaseModel):
    """Ce que l'écran a besoin de savoir avant de proposer une estimation (`IA-07`).

    Le message vient du serveur et s'affiche tel quel : le client décide sur `enabled`,
    jamais sur le texte (`API-07`).
    """

    enabled: bool = Field(description="Une clé OpenRouter est configurée")
    message: str = Field(description="Ce qu'il y a à dire à l'écran, en français")


class AiModel(BaseModel):
    """Un modèle gratuit du catalogue découvert (`IA-02`)."""

    id: str
    name: str
    context_length: int
    vision: bool
    params_b: float | None = None


class AiModels(BaseModel):
    """Catalogue tel qu'il est servi à la cascade."""

    models: list[AiModel]
    #: Vrai quand la liste vient du cache d'une heure plutôt que d'un appel neuf.
    cached: bool
