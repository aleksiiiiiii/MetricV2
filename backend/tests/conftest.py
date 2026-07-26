"""Fixtures partagées."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.security import hash_password
from app.main import create_app
from app.storage.cache import FileCache
from app.storage.files import FileStore
from app.storage.webdav import WebDavClient
from tests.fake_webdav import FakeWebDav

#: Compte de test. Le hash est calculé une fois pour toute la session : Argon2 est lent
#: par conception, et le recalculer par test coûterait plusieurs secondes.
TEST_USERNAME = "aleksi"
TEST_PASSWORD = "un mot de passe de test"


@pytest.fixture(scope="session")
def password_hash() -> str:
    return hash_password(TEST_PASSWORD)


@pytest.fixture
def settings(password_hash: str) -> Settings:
    """Réglages de test, isolés de tout `.env` local."""
    return Settings(
        _env_file=None,
        app_env="test",
        cors_origins="http://localhost:5173",
        auth_username=TEST_USERNAME,
        auth_password_hash=password_hash,
        jwt_secret="secret-de-test-suffisamment-long-pour-etre-credible",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    # `with` déclenche le lifespan : sans lui, ni la couche stockage ni les objets de
    # sécurité ne seraient montés.
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def token(client: TestClient) -> str:
    """Jeton d'une session ouverte, pour les tests qui ont juste besoin d'être authentifiés."""
    response = client.post(
        "/api/auth/login",
        json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


@pytest.fixture
def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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
