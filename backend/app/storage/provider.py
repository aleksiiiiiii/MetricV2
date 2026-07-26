"""Cycle de vie de la couche stockage.

Le client WebDAV détient un pool de connexions : il doit naître dans la boucle
d'événements et mourir avec l'application. D'où un fournisseur piloté par le `lifespan`
de FastAPI, plutôt qu'un singleton créé à l'import.

Sans configuration Nextcloud, le fournisseur reste inerte et toute demande d'accès lève
`StorageNotConfiguredError`. L'application démarre quand même : `/api/health` répond, la doc
s'affiche, et le message d'erreur dit quoi renseigner.
"""

from __future__ import annotations

from app.config import Settings
from app.storage.cache import FileCache
from app.storage.errors import StorageNotConfiguredError
from app.storage.files import FileStore
from app.storage.webdav import WebDavClient


class StorageProvider:
    """Détient le client WebDAV et le `FileStore` partagé."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: WebDavClient | None = None
        self._store: FileStore | None = None

    @property
    def configured(self) -> bool:
        return self._settings.storage_configured

    async def start(self) -> None:
        if not self.configured:
            return
        self._client = WebDavClient(
            base_url=self._settings.nextcloud_url,
            username=self._settings.nextcloud_username,
            password=self._settings.nextcloud_password,
            root=self._settings.nextcloud_root,
        )
        self._store = FileStore(self._client, FileCache())

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None
        self._store = None

    @property
    def store(self) -> FileStore:
        """`FileStore` prêt à l'emploi, ou `StorageNotConfiguredError`."""
        if self._store is None:
            raise StorageNotConfiguredError
        return self._store

    def use(self, store: FileStore) -> None:
        """Injecte un `FileStore` déjà construit — utilisé par les tests."""
        self._store = store
