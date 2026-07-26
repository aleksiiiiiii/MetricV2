"""Contrat du socle API (`API-01` → `API-07`, `AUTH-05`)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.config import Settings
from app.core import exceptions
from app.core.deps import require_auth
from app.core.exceptions import MetricError
from app.core.validation import Note, PastDate, Reps, VolumeMl, WeightKg
from app.domains.api import PROTECTED_PREFIXES
from app.main import create_app

#: Les seules routes qui doivent répondre sans jeton (`AUTH-05`). Santé, documentation,
#: connexion. Le flux iCal (`PLAN-05`) les rejoindra au lot L13, protégé par sa clé.
PUBLIC_PATHS = {
    "/api/health",
    "/api/docs",
    "/api/docs/oauth2-redirect",
    "/api/redoc",
    "/api/openapi.json",
    "/api/auth/login",
}


def dependency_calls(route: APIRoute) -> set[Any]:
    """Toutes les fonctions de dépendance d'une route, y compris imbriquées."""
    found: set[Any] = set()
    pending = list(route.dependant.dependencies)
    while pending:
        dependant = pending.pop()
        if dependant.call is not None:
            found.add(dependant.call)
        pending.extend(dependant.dependencies)
    return found


# ── Découpage et protection ───────────────────────────


def test_every_data_route_requires_a_token(settings: Settings) -> None:
    """Garde structurelle de `AUTH-05`.

    Ce test grandit tout seul : chaque route ajoutée par un lot ultérieur est vérifiée
    ici sans qu'on ait à y penser. C'est le but de porter la protection sur le groupe de
    routeurs plutôt que route par route.
    """
    app = create_app(settings)

    unprotected = [
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path.startswith("/api")
        and route.path not in PUBLIC_PATHS
        and require_auth not in dependency_calls(route)
    ]

    assert unprotected == []


def test_login_and_health_stay_reachable_without_a_token(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/openapi.json").status_code == 200

    # La connexion est joignable : un mauvais couple est refusé pour ce qu'il vaut
    # (`invalid_credentials`), pas parce qu'il manquerait un jeton (`session_expired`).
    refused = client.post("/api/auth/login", json={"username": "x", "password": "y"})
    assert refused.json()["code"] == "invalid_credentials"


def test_each_domain_has_its_own_prefix(client: TestClient) -> None:
    """`API-01` : une API découpée par domaine, chaque domaine testable isolément."""
    assert "/api/body" in PROTECTED_PREFIXES
    assert "/api/heatmap" in PROTECTED_PREFIXES
    assert len(set(PROTECTED_PREFIXES)) == len(PROTECTED_PREFIXES), "préfixe en double"
    del client


def test_the_documentation_declares_the_session_scheme(client: TestClient) -> None:
    """`API-05` : chaque endpoint doit être essayable depuis le navigateur, donc le
    schéma d'authentification doit être déclaré."""
    schemes = client.get("/api/openapi.json").json()["components"]["securitySchemes"]

    assert "Session Metric" in schemes
    assert schemes["Session Metric"]["scheme"] == "bearer"


# ── Catalogue d'erreurs (`API-07`) ────────────────────


def error_classes() -> list[type[MetricError]]:
    return [
        value
        for value in vars(exceptions).values()
        if isinstance(value, type) and issubclass(value, MetricError)
    ]


def test_every_code_is_unique() -> None:
    """Deux erreurs partageant un code rendraient le mappage client ambigu."""
    codes = [cls.code for cls in error_classes()]

    assert len(codes) == len(set(codes)), sorted(codes)


def test_every_error_carries_a_french_message_and_a_snake_case_code() -> None:
    for cls in error_classes():
        assert cls.message, cls.__name__
        assert cls.code == cls.code.lower(), cls.__name__
        assert " " not in cls.code, cls.__name__


def test_an_unexpected_exception_never_leaks_its_traceback(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/api/_test/crash")
    def crash() -> None:
        raise RuntimeError("secret interne : /Metric/body/weight.csv")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/_test/crash")

    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "Une erreur inattendue s'est produite.",
    }
    assert "weight.csv" not in response.text


def test_a_route_that_does_not_exist_answers_in_the_house_format(client: TestClient) -> None:
    response = client.get("/api/nulle-part")

    assert response.status_code == 404
    assert response.json() == {
        "code": "not_found",
        "message": "Cette ressource n'existe pas.",
    }


def test_a_wrong_method_answers_in_french(client: TestClient) -> None:
    """Starlette rédige ses messages en anglais : l'API doit répondre en français."""
    response = client.get("/api/auth/login")

    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"
    assert "autorisée" in response.json()["message"]


# ── Bornes de vraisemblance (`API-06`) ────────────────


class Probe(BaseModel):
    weight_kg: WeightKg
    reps: Reps
    volume_ml: VolumeMl
    day: PastDate
    note: Note = ""


@pytest.fixture
def probe_client(settings: Settings) -> Iterator[TestClient]:
    """Application jetable exposant les types validés, hors de toute route protégée."""
    app = create_app(settings)
    router = APIRouter(prefix="/api/_test")

    @router.post("/probe")
    def probe(payload: Probe) -> Probe:
        return payload

    app.include_router(router)
    with TestClient(app) as client:
        yield client


def valid_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "weight_kg": 68.4,
        "reps": 12,
        "volume_ml": 500,
        "day": "2026-07-20",
        **overrides,
    }


def test_a_plausible_payload_passes(probe_client: TestClient) -> None:
    assert probe_client.post("/api/_test/probe", json=valid_payload()).status_code == 200


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("weight_kg", 0),  # borne basse exclue
        ("weight_kg", 501),  # poids 0-500 kg
        ("reps", 0),  # reps 1-200
        ("reps", 201),
        ("volume_ml", 0),  # volume 0-5000 ml
        ("volume_ml", 5001),
        ("day", "2099-01-01"),  # date jamais future
        ("note", "x" * 501),
    ],
)
def test_an_aberrant_value_is_rejected_before_storage(
    probe_client: TestClient, field: str, value: Any
) -> None:
    response = probe_client.post("/api/_test/probe", json=valid_payload(**{field: value}))

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_a_rejection_says_which_field_to_highlight(probe_client: TestClient) -> None:
    """C'est la seule erreur qui détaille : l'information vient de la requête de
    l'utilisateur et ne révèle rien de l'infrastructure."""
    response = probe_client.post("/api/_test/probe", json=valid_payload(weight_kg=900))

    fields = response.json()["fields"]
    assert any("weight_kg" in field["field"] for field in fields), fields


def test_today_is_accepted_as_a_past_date(probe_client: TestClient) -> None:
    """La borne est « pas dans le futur », pas « strictement avant aujourd'hui »."""
    from app.core.validation import today_local

    response = probe_client.post(
        "/api/_test/probe", json=valid_payload(day=today_local().isoformat())
    )

    assert response.status_code == 200


# ── Durcissement de la configuration (`API-02`) ───────


def test_production_refuses_the_development_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(_env_file=None, app_env="production")


def test_production_lists_everything_that_is_missing() -> None:
    with pytest.raises(ValueError) as caught:
        Settings(_env_file=None, app_env="production", jwt_secret="x" * 40)

    message = str(caught.value)
    assert "AUTH_USERNAME" in message
    assert "AUTH_PASSWORD_HASH" in message
    assert "Nextcloud" in message


def test_a_complete_production_configuration_is_accepted(password_hash: str) -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret="x" * 48,
        auth_username="aleksi",
        auth_password_hash=password_hash,
        nextcloud_url="https://nextcloud.example/remote.php/dav/files/aleksi",
        nextcloud_username="aleksi",
        nextcloud_password="mot-de-passe-application",
    )

    assert settings.is_production is True


def test_development_stays_permissive() -> None:
    """L'application doit démarrer sans rien configurer : c'est ce qui permet de lancer
    les tests et la référence visuelle sans Nextcloud."""
    assert Settings(_env_file=None).is_production is False


def test_the_app_starts_without_any_configuration() -> None:
    app: FastAPI = create_app(Settings(_env_file=None))

    with TestClient(app) as client:
        body = client.get("/api/health").json()

    assert body["auth_configured"] is False
    assert body["storage_configured"] is False
