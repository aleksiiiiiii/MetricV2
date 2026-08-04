"""État de l'assistance et dégradation sans clé (`IA-07`, `L12-16`).

C'est le contrat structurant du lot : **sans clé, aucune fonctionnalité n'est bloquée.**
Les tests de ce fichier vérifient les deux moitiés de cette phrase — que les fonctions IA
refusent proprement, et que tout le reste continue de fonctionner.
"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

from tests.fake_openrouter import FakeOpenRouter


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(buffer, format="PNG")
    return buffer.getvalue()


# ── Sans clé (`IA-07`) ────────────────────────────────


def test_status_says_the_assistance_is_off_without_failing(
    client: TestClient, auth: dict[str, str]
) -> None:
    """`200` et non une erreur : l'absence de clé est un **état**, pas une panne.

    Un écran qui recevrait une erreur ici cacherait son bloc IA pour la mauvaise raison —
    et ne saurait pas dire ce qui manque.
    """
    response = client.get("/api/ai/status", headers=auth)

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert "clé OpenRouter" in body["message"]


def test_analyzing_a_meal_without_a_key_refuses_with_an_actionable_message(
    client: TestClient, auth: dict[str, str]
) -> None:
    response = client.post(
        "/api/nutrition/analyze",
        files={"photo": ("assiette.png", png(), "image/png")},
        headers=auth,
    )

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "ai_unavailable"
    assert "manuelle" in body["message"] or "main" in body["message"]


def test_importing_a_screenshot_without_a_key_refuses_the_same_way(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    response = store_client.post(
        "/api/import/apple/analyze",
        files={"screenshot": ("capture.png", png(), "image/png")},
        headers=auth,
    )

    assert response.status_code == 503
    assert response.json()["code"] == "ai_unavailable"


def test_manual_entry_still_works_without_a_key(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """La moitié qui compte : **aucune fonctionnalité n'est bloquée** (`IA-07`)."""
    meal = store_client.post(
        "/api/nutrition",
        data={"meal_type": "déjeuner", "comment": "poulet riz", "protein_g": "42"},
        headers=auth,
    )
    run = store_client.post(
        "/api/activity/runs",
        json={"date": "2026-07-28", "distance_km": "8,40", "duration_min": "44:12"},
        headers=auth,
    )

    assert meal.status_code == 201
    assert run.status_code == 201
    assert meal.json()["protein_g"] == 42


def test_the_import_endpoint_writes_without_any_key(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """La validation d'un import ne dépend pas de l'IA : elle n'est plus qu'une saisie.

    C'est ce qui permet de valider un brouillon analysé il y a dix minutes — ou dont on a
    tout réécrit à la main.
    """
    response = store_client.post(
        "/api/import/apple",
        json={
            "kind": "run",
            "date": "2026-07-28",
            "distance_km": "8,40",
            "duration_min": "44:12",
        },
        headers=auth,
    )

    assert response.status_code == 201
    assert response.json()["source"] == "apple"


# ── Avec clé ──────────────────────────────────────────


def test_status_says_the_assistance_is_on(ai_app_client: TestClient, auth: dict[str, str]) -> None:
    response = ai_app_client.get("/api/ai/status", headers=auth)

    assert response.status_code == 200
    assert response.json()["enabled"] is True


def test_the_discovered_catalogue_is_published(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """`IA-02` : la découverte est consultable, ce qui la rend vérifiable à la main."""
    response = ai_app_client.get("/api/ai/models", headers=auth)

    assert response.status_code == 200
    body = response.json()
    assert [model["id"] for model in body["models"]] == [
        "vendeur/grand-vision-70b",
        "vendeur/texte-seul-13b",
        "vendeur/petit-vision-8b",
    ]
    assert body["cached"] is False
    assert openrouter.models_calls == 1


def test_the_second_read_of_the_catalogue_says_it_was_cached(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    ai_app_client.get("/api/ai/models", headers=auth)
    response = ai_app_client.get("/api/ai/models", headers=auth)

    assert response.json()["cached"] is True
    assert openrouter.models_calls == 1


def test_the_ai_routes_require_a_token() -> None:
    """Portée par le groupe protégé, comme toute route de données (`AUTH-05`)."""
    from app.domains.api import PROTECTED_PREFIXES

    assert "/api/ai" in PROTECTED_PREFIXES
    assert "/api/import" in PROTECTED_PREFIXES
