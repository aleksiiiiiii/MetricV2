"""Fixtures partagées."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Réglages de test, isolés de tout `.env` local."""
    return Settings(
        _env_file=None,
        app_env="test",
        cors_origins="http://localhost:5173",
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
