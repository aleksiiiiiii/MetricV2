"""Fixtures partagées."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.storage.cache import FileCache
from app.storage.files import FileStore
from app.storage.webdav import WebDavClient
from tests.fake_webdav import FakeWebDav


@pytest.fixture
def settings() -> Settings:
    """Réglages de test, isolés de tout `.env` local."""
    return Settings(
        _env_file=None,
        app_env="test",
        cors_origins="http://localhost:5173",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    # `with` déclenche le lifespan : sans lui, la couche stockage ne serait pas montée.
    with TestClient(create_app(settings)) as test_client:
        yield test_client


# ── Couche stockage ───────────────────────────────────


@pytest.fixture
def dav() -> FakeWebDav:
    """Faux serveur WebDAV, avec les dossiers de données déjà créés."""
    server = FakeWebDav()
    server.collections.update(
        {
            "Metric",
            "Metric/body",
            "Metric/activity",
            "Metric/settings",
            "Metric/hydration",
            "Metric/supplements",
        }
    )
    return server


@pytest.fixture
def sleeps() -> list[float]:
    """Délais d'attente demandés par le client, au lieu d'être subis."""
    return []


@pytest.fixture
async def webdav(dav: FakeWebDav, sleeps: list[float]) -> AsyncIterator[WebDavClient]:
    """Client WebDAV branché sur le double, sans attente réelle."""

    async def record(delay: float) -> None:
        sleeps.append(delay)

    client = WebDavClient(
        base_url="http://nextcloud.test",
        username="aleksi",
        password="secret",
        root="Metric",
        sleep=record,
        transport=httpx2.ASGITransport(app=dav),
    )
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def cache() -> FileCache:
    return FileCache()


@pytest.fixture
def store(webdav: WebDavClient, cache: FileCache) -> FileStore:
    store = FileStore(webdav, cache)
    # Les dossiers du double existent déjà : on évite un MKCOL par écriture dans les
    # tests qui comptent les requêtes.
    store._known_collections.update({"body", "activity", "settings", "hydration", "supplements"})
    return store
