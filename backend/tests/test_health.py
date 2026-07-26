"""Route de santé (`API-04`) et cohérence de la configuration (`API-02`)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings


def test_health_is_public_and_describes_the_service(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"
    assert body["timezone"] == "Europe/Paris"


def test_health_reports_an_offset_aware_local_time() -> None:
    """`HEAT-32` : le serveur raisonne en heure locale, jamais en UTC nu."""
    from app.main import create_app

    settings = Settings(_env_file=None)
    client = TestClient(create_app(settings))

    time = client.get("/api/health").json()["time"]
    assert time.endswith(("+01:00", "+02:00")), time


def test_openapi_is_served(client: TestClient) -> None:
    """`API-05` : la documentation est générée automatiquement."""
    assert client.get("/api/openapi.json").status_code == 200


def test_ai_and_storage_flags_default_to_off() -> None:
    """`IA-07` : sans clé, l'IA est annoncée absente, pas devinée."""
    settings = Settings(_env_file=None)

    assert settings.ai_enabled is False
    assert settings.storage_configured is False


def test_cors_origins_parse_from_a_comma_separated_list() -> None:
    settings = Settings(
        _env_file=None,
        cors_origins="http://localhost:5173, https://metric.example ",
    )

    assert settings.cors_origin_list == ["http://localhost:5173", "https://metric.example"]
