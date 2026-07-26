"""Couche de stockage : CSV sur Nextcloud via WebDAV.

Aucun domaine ne parle directement à WebDAV. Le point d'entrée est `FileStore` pour les
fichiers, `CsvRepository` pour les données tabulaires.
"""

from app.storage.cache import CacheEntry, FileCache
from app.storage.csv_repo import CsvRepository, Row, Sheet
from app.storage.errors import (
    StorageAuthFailedError,
    StorageConflictError,
    StorageError,
    StorageNotConfiguredError,
    StorageNotFoundError,
    StorageSchemaError,
    StorageUnavailableError,
)
from app.storage.files import FileState, FileStore
from app.storage.model import CsvModel, format_csv_value
from app.storage.provider import StorageProvider
from app.storage.webdav import Fetched, WebDavClient

__all__ = [
    "CacheEntry",
    "CsvModel",
    "CsvRepository",
    "Fetched",
    "FileCache",
    "FileState",
    "FileStore",
    "Row",
    "Sheet",
    "StorageAuthFailedError",
    "StorageConflictError",
    "StorageError",
    "StorageNotConfiguredError",
    "StorageNotFoundError",
    "StorageProvider",
    "StorageSchemaError",
    "StorageUnavailableError",
    "WebDavClient",
    "format_csv_value",
]
