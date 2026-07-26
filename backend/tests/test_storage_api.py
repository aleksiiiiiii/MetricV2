"""Traduction HTTP des pannes de stockage (`STO-09`, `API-07`).

Une panne de Nextcloud ne doit jamais sortir en 500 brute, et le corps de réponse doit
porter un code machine que le client mappe sans lire le message.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.deps import StoreDep
from app.main import create_app
from app.storage.errors import (
    StorageConflictError,
    StorageError,
    StorageSchemaError,
    StorageUnavailableError,
)


def app_with_failing_route(exc: Exception, settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.get("/api/_test/boom")
    def boom() -> None:
        raise exc

    return app


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, app_env="test")


def test_an_unconfigured_storage_says_what_to_fill_in(settings: Settings) -> None:
    """Sans Nextcloud, l'app démarre : seuls les écrans de données échouent, proprement."""
    app = create_app(settings)

    @app.get("/api/_test/store")
    def uses_store(store: StoreDep) -> None:
        del store

    with TestClient(app) as client:
        response = client.get("/api/_test/store")

    assert response.status_code == 503
    assert response.json() == {
        "code": "storage_not_configured",
        "message": "Le stockage n'est pas configuré : renseigne Nextcloud dans le fichier .env.",
    }


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (StorageUnavailableError(), 503, "storage_unavailable"),
        (StorageConflictError(), 409, "conflict"),
        (StorageSchemaError(), 502, "storage_schema_error"),
        (StorageError(), 502, "storage_error"),
    ],
)
def test_each_failure_carries_a_stable_machine_code(
    settings: Settings, error: StorageError, status: int, code: str
) -> None:
    with TestClient(app_with_failing_route(error, settings)) as client:
        response = client.get("/api/_test/boom")

    assert response.status_code == status
    assert response.json()["code"] == code
    assert response.json()["message"], "un message français accompagne toujours le code"


def test_the_response_never_leaks_paths_or_statuses(settings: Settings) -> None:
    """Le détail technique va dans les journaux : il n'aide pas l'utilisateur et
    renseigne l'arborescence du stockage."""
    error = StorageUnavailableError(detail="PUT Metric/body/weight.csv → HTTP 507")

    with TestClient(app_with_failing_route(error, settings)) as client:
        body = client.get("/api/_test/boom").text

    assert "weight.csv" not in body
    assert "507" not in body


def test_health_still_answers_without_any_storage(client: TestClient) -> None:
    """`API-04` reste public et ne dépend pas de Nextcloud (`AUTH-05`)."""
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["storage_configured"] is False
