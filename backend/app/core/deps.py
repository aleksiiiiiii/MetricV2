"""Dépendances FastAPI partagées."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.storage.files import FileStore
from app.storage.provider import StorageProvider


def get_storage_provider(request: Request) -> StorageProvider:
    """Fournisseur de stockage attaché à l'application par le `lifespan`."""
    provider = getattr(request.app.state, "storage", None)
    if not isinstance(provider, StorageProvider):  # pragma: no cover - erreur de câblage
        raise RuntimeError("La couche stockage n'a pas été initialisée par le lifespan.")
    return provider


def get_store(provider: Annotated[StorageProvider, Depends(get_storage_provider)]) -> FileStore:
    """`FileStore` prêt à l'emploi.

    Lève `StorageNotConfiguredError` — traduite en `503` avec un message actionnable — si
    Nextcloud n'est pas renseigné.
    """
    return provider.store


SettingsDep = Annotated[Settings, Depends(get_settings)]
StoreDep = Annotated[FileStore, Depends(get_store)]
