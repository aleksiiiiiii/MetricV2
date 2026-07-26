"""Accès fichier cohérent : client WebDAV + cache (`STO-06`, `STO-07`).

Cette couche est la seule à parler au client WebDAV. Elle garantit qu'après une
écriture, aucune lecture ne peut servir l'état précédent, et fournit la lecture
« fraîche » dont dépend la garde anti-conflit (`STO-05`).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.storage.cache import FileCache
from app.storage.errors import StorageNotFoundError
from app.storage.webdav import WebDavClient


@dataclass(frozen=True, slots=True)
class FileState:
    """Contenu d'un fichier et son ETag au moment de la lecture.

    `etag is None` signale un fichier **absent** : c'est distinct d'un fichier vide, et
    la nuance compte pour décider entre créer et modifier.
    """

    content: bytes
    etag: str | None
    exists: bool


class FileStore:
    """Lectures cachées et écritures cohérentes sur un dossier Nextcloud."""

    def __init__(self, client: WebDavClient, cache: FileCache | None = None) -> None:
        self._client = client
        # `cache or FileCache()` serait un piège : `FileCache` définit `__len__`, donc un
        # cache vide est falsy et serait silencieusement remplacé.
        self._cache = FileCache() if cache is None else cache
        # Dossiers dont on sait déjà qu'ils existent — évite un MKCOL par écriture.
        self._known_collections: set[str] = set()

    @property
    def client(self) -> WebDavClient:
        return self._client

    @property
    def cache(self) -> FileCache:
        return self._cache

    # ── Lecture ───────────────────────────────────────

    async def read(self, path: str, *, fresh: bool = False) -> FileState:
        """Lit un fichier, éventuellement depuis le cache.

        `fresh=True` force une revalidation auprès du serveur : indispensable avant une
        écriture sous garde, sinon deux appareils au cache chaud passeraient tous les
        deux la garde et le second écraserait le premier.

        Un fichier absent rend `FileState(b"", None, exists=False)` plutôt qu'une erreur :
        pour un CSV, « pas encore de fichier » et « fichier sans lignes » se traitent
        pareil côté domaine.
        """
        entry = self._cache.get(path)

        if entry is not None and not fresh and self._cache.is_fresh(entry):
            return FileState(content=entry.content, etag=entry.etag, exists=True)

        try:
            fetched = await self._client.get(path, etag=entry.etag if entry else None)
        except StorageNotFoundError:
            self._cache.invalidate(path)
            return FileState(content=b"", etag=None, exists=False)

        if fetched.not_modified and entry is not None:
            refreshed = self._cache.touch(path) or entry
            return FileState(content=refreshed.content, etag=refreshed.etag, exists=True)

        content = fetched.content or b""
        self._cache.store(path, content, fetched.etag)
        return FileState(content=content, etag=fetched.etag, exists=True)

    # ── Écriture ──────────────────────────────────────

    async def write(
        self,
        path: str,
        content: bytes,
        *,
        if_match: str | None = None,
        if_none_match: str | None = None,
        content_type: str = "text/csv; charset=utf-8",
    ) -> str | None:
        """Écrit un fichier et remet le cache en phase.

        Si le serveur annonce le nouvel ETag, on mémorise directement le contenu écrit —
        la lecture suivante ne coûte rien. Sinon on invalide : mieux vaut une requête de
        plus qu'un cache qui mentirait sur l'ETag et ferait échouer la garde suivante.
        """
        await self._ensure_parent(path)
        etag = await self._client.put(
            path,
            content,
            if_match=if_match,
            if_none_match=if_none_match,
            content_type=content_type,
        )

        if etag:
            self._cache.store(path, content, etag)
        else:
            self._cache.invalidate(path)
        return etag

    async def delete(self, path: str, *, missing_ok: bool = True) -> None:
        await self._client.delete(path, missing_ok=missing_ok)
        self._cache.invalidate(path)

    async def write_binary(self, path: str, data: bytes, *, content_type: str) -> str | None:
        """Téléverse un fichier binaire — photo de repas (`STO-07`, `NUT-02`).

        Les binaires ne passent pas par le cache : ils sont volumineux, immuables, et
        servis par un endpoint dédié qui pose ses propres en-têtes de cache (`NUT-08`).
        """
        await self._ensure_parent(path)
        return await self._client.put(path, data, content_type=content_type)

    async def read_binary(self, path: str) -> bytes:
        fetched = await self._client.get(path)
        return fetched.content or b""

    # ── Interne ───────────────────────────────────────

    async def _ensure_parent(self, path: str) -> None:
        """Crée l'arborescence parente si besoin.

        Coût : un MKCOL par segment, seulement au premier passage — les suivants sont
        court-circuités par `_known_collections`.
        """
        parent = "/".join(path.strip("/").split("/")[:-1])
        if not parent or parent in self._known_collections:
            return
        await self._client.ensure_collection(parent)
        self._known_collections.add(parent)
