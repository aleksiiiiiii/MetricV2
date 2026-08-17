"""Estimation assistée d'une assiette (`NUT-04`, `L12-16`).

La règle que ce fichier défend tient en une phrase : **proposé, jamais imposé.** Une
estimation ne touche pas le fichier ; c'est la validation qui écrit, et elle passe par les
mêmes endpoints que la saisie au clavier.
"""

from __future__ import annotations

import io

import httpx2
from fastapi.testclient import TestClient
from PIL import Image

from app.domains.nutrition.analysis import read_estimate
from tests.fake_openrouter import FakeOpenRouter, Reply
from tests.fake_webdav import FakeWebDav

MEALS_FILE = "Metric/nutrition/meals.csv"


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (80, 80), "green").save(buffer, format="PNG")
    return buffer.getvalue()


def analyze(client: TestClient, auth: dict[str, str]) -> httpx2.Response:
    return client.post(
        "/api/nutrition/analyze",
        files={"photo": ("assiette.png", png(), "image/png")},
        headers=auth,
    )


# ── Relecture de la réponse ───────────────────────────


def test_a_complete_answer_becomes_a_proposal() -> None:
    estimate = read_estimate(
        {"comment": "poulet, riz, brocolis", "protein_g": 42, "added_sugar_g": 3, "calories": 640}
    )

    assert estimate.comment == "poulet, riz, brocolis"
    assert estimate.protein_g == 42
    assert estimate.calories == 640
    assert estimate.empty is False


def test_a_value_the_model_could_not_estimate_stays_empty() -> None:
    """`null` reste `null` : c'est « aucune valeur inventée » appliqué à l'estimation."""
    estimate = read_estimate({"protein_g": 30, "added_sugar_g": None, "calories": None})

    assert estimate.protein_g == 30
    assert estimate.added_sugar_g is None
    assert estimate.calories is None


def test_a_number_written_with_its_unit_is_still_a_number() -> None:
    estimate = read_estimate({"protein_g": "32 g", "calories": "640 kcal"})

    assert estimate.protein_g == 32
    assert estimate.calories == 640


def test_a_range_is_not_a_number_and_is_dropped() -> None:
    """« 30 à 40 g » n'est pas une mesure, et en retenir le premier serait arbitraire."""
    estimate = read_estimate({"protein_g": "30-40", "calories": "environ 600"})

    assert estimate.protein_g is None
    assert estimate.calories is None


def test_an_absurd_value_is_dropped_not_clamped() -> None:
    """Ramener 4000 g à 500 g donnerait une valeur fausse d'apparence honnête."""
    estimate = read_estimate({"protein_g": 4000, "calories": 640})

    assert estimate.protein_g is None
    assert estimate.calories == 640


def test_an_answer_without_a_single_number_says_it_is_empty() -> None:
    """Trois champs vides sans un mot passeraient pour une panne."""
    estimate = read_estimate({"comment": "assiette", "protein_g": None})

    assert estimate.empty is True


def test_the_model_can_say_it_sees_no_food() -> None:
    estimate = read_estimate({"readable": False, "protein_g": None})

    assert estimate.readable is False


# ── Bout en bout, sur réponses simulées ───────────────


def test_analyzing_a_photo_proposes_macros(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    openrouter.say(
        '{"comment": "saumon, quinoa", "protein_g": 38, "added_sugar_g": 0, "calories": 520}'
    )

    response = analyze(ai_app_client, auth)

    assert response.status_code == 200
    body = response.json()
    assert body["protein_g"] == 38
    assert body["comment"] == "saumon, quinoa"


def test_a_chatty_model_is_still_understood(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """`L12-16` : JSON bavard. C'est le comportement **normal** d'un modèle gratuit."""
    openrouter.say(
        "Avec plaisir ! Voici mon analyse de ton assiette :\n"
        '```json\n{"comment": "pâtes bolognaise", "protein_g": 26, "calories": 700}\n```\n'
        "Bon appétit !"
    )

    body = analyze(ai_app_client, auth).json()

    assert body["protein_g"] == 26
    assert body["comment"] == "pâtes bolognaise"


def test_analyzing_writes_absolutely_nothing(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, dav: FakeWebDav, auth: dict[str, str]
) -> None:
    """`NUT-04` : proposé, jamais imposé. Ni ligne de repas, ni photo rangée."""
    openrouter.say('{"protein_g": 38, "calories": 520}')
    files_before = dict(dav.files)

    analyze(ai_app_client, auth)

    assert dict(dav.files) == files_before


def test_the_photo_reaches_the_model_reduced_and_in_jpeg(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """`IA-06` : ce qui part n'est jamais le fichier d'origine."""
    openrouter.say('{"protein_g": 20}')

    analyze(ai_app_client, auth)

    assert openrouter.calls[0].with_image
    assert openrouter.calls[0].image_url is not None
    assert openrouter.calls[0].image_url.startswith("data:image/jpeg;base64,")


def test_an_estimate_keeps_the_temperature_the_assistant_dropped(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """La contrepartie du lot 7, et c'est elle qui en fait un réglage plutôt qu'un retrait.

    La même photo ne doit pas rendre 32 g de protéines puis 41 g selon l'humeur du tirage.
    L'assistant, lui, ne veut surtout pas de cette reproductibilité-là. Sans ce test, un
    retrait par mégarde sur cette route ne se verrait qu'en réestimant deux fois la même
    assiette — c'est-à-dire jamais.
    """
    from app.domains.ai.client import EXTRACTION_TEMPERATURE

    openrouter.say('{"protein_g": 20}')

    analyze(ai_app_client, auth)

    assert openrouter.calls[0].body["temperature"] == EXTRACTION_TEMPERATURE


def test_a_saturated_quota_is_told_apart_from_a_failure(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """`IA-03` : les deux mènent à un échec, mais l'un se résout en attendant."""
    openrouter.replies = [Reply.quota(), Reply.quota(), Reply.quota()]

    response = analyze(ai_app_client, auth)

    assert response.status_code == 503
    assert response.json()["code"] == "ai_quota"


def test_a_file_that_is_not_an_image_is_refused_before_any_call(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    response = ai_app_client.post(
        "/api/nutrition/analyze",
        files={"photo": ("notes.txt", b"ceci n'est pas une image", "text/plain")},
        headers=auth,
    )

    assert response.status_code == 422
    assert openrouter.calls == []


# ── Validation par l'utilisateur ──────────────────────


def test_an_accepted_estimate_is_written_with_its_provenance(
    ai_app_client: TestClient, dav: FakeWebDav, auth: dict[str, str]
) -> None:
    """`IMP-05` appliqué à la nutrition : l'origine reste lisible dans le fichier."""
    response = ai_app_client.post(
        "/api/nutrition",
        data={
            "meal_type": "déjeuner",
            "comment": "saumon, quinoa",
            "protein_g": "38",
            "calories": "520",
            "source": "ai",
        },
        headers=auth,
    )

    assert response.status_code == 201
    assert response.json()["source"] == "ai"
    assert ",ai\n" in dav.content_of(MEALS_FILE)


def test_a_refused_estimate_leaves_the_meal_manual(
    ai_app_client: TestClient, auth: dict[str, str]
) -> None:
    """« Pas d'accord » vide les champs : ce qui s'enregistre ensuite est une saisie."""
    response = ai_app_client.post(
        "/api/nutrition",
        data={"meal_type": "déjeuner", "comment": "saumon, quinoa"},
        headers=auth,
    )

    assert response.json()["source"] == "manual"


def test_an_unknown_provenance_is_refused(ai_app_client: TestClient, auth: dict[str, str]) -> None:
    """La colonne ne prend que `manual` ou `ai` : le fichier doit rester lisible seul."""
    response = ai_app_client.post(
        "/api/nutrition",
        data={"meal_type": "déjeuner", "comment": "x", "source": "openrouter"},
        headers=auth,
    )

    assert response.status_code == 422


# ── Estimer un repas déjà enregistré ──────────────────


def test_a_meal_photographed_earlier_can_be_estimated_afterwards(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """L'écran promet « les macros peuvent attendre » : voici la porte pour « après »."""
    created = ai_app_client.post(
        "/api/nutrition",
        data={"meal_type": "dîner"},
        files={"photo": ("assiette.png", png(), "image/png")},
        headers=auth,
    )
    assert created.status_code == 201
    assert created.json()["protein_g"] is None

    openrouter.say('{"protein_g": 31, "calories": 480}')
    response = ai_app_client.post(f"/api/nutrition/{created.json()['id']}/analyze", headers=auth)

    assert response.status_code == 200
    assert response.json()["protein_g"] == 31


def test_estimating_a_stored_meal_does_not_modify_it(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, dav: FakeWebDav, auth: dict[str, str]
) -> None:
    created = ai_app_client.post(
        "/api/nutrition",
        data={"meal_type": "dîner"},
        files={"photo": ("assiette.png", png(), "image/png")},
        headers=auth,
    )
    before = dav.content_of(MEALS_FILE)

    openrouter.say('{"protein_g": 31}')
    ai_app_client.post(f"/api/nutrition/{created.json()['id']}/analyze", headers=auth)

    assert dav.content_of(MEALS_FILE) == before


def test_estimating_a_meal_without_a_photo_says_so(
    ai_app_client: TestClient, auth: dict[str, str]
) -> None:
    created = ai_app_client.post(
        "/api/nutrition",
        data={"meal_type": "déjeuner", "comment": "sandwich"},
        headers=auth,
    )

    response = ai_app_client.post(f"/api/nutrition/{created.json()['id']}/analyze", headers=auth)

    assert response.status_code == 404
    assert "photo" in response.json()["message"]


# ── Estimer sans photo, ou avec les deux (C05) ────────

# Quatre modes de saisie à l'écran — photo, photo + description, description, manuel — et
# un seul endpoint pour les trois premiers. Ce qui suit vérifie que le mode ne remonte
# nulle part : seule compte la matière envoyée.


def test_a_description_alone_is_enough_to_estimate(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    openrouter.say('{"comment": "pâtes au thon", "protein_g": 28, "calories": 620}')

    response = ai_app_client.post(
        "/api/nutrition/analyze",
        data={"comment": "une assiette de pâtes au thon"},
        headers=auth,
    )

    assert response.status_code == 200
    assert response.json()["protein_g"] == 28


def test_a_description_alone_does_not_ask_a_vision_model(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """`IA-04` pris à l'endroit : sans image, la cascade n'a pas à se restreindre.

    C'est le bénéfice caché du mode « description seule » — tout le catalogue gratuit est
    candidat, et non sa seule moitié qui lit les images.
    """
    openrouter.say('{"protein_g": 28}')

    ai_app_client.post("/api/nutrition/analyze", data={"comment": "pâtes au thon"}, headers=auth)

    assert openrouter.calls
    assert all(not call.with_image for call in openrouter.calls)


def test_a_description_reaches_the_model_as_written(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    openrouter.say('{"protein_g": 28}')

    ai_app_client.post(
        "/api/nutrition/analyze",
        data={"comment": "deux œufs et une tranche de pain complet"},
        headers=auth,
    )

    assert "deux œufs et une tranche de pain complet" in openrouter.calls[0].prompt


def test_a_photo_and_a_description_travel_together(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """La photo montre la quantité, le texte nomme ce que l'image ne dit pas."""
    openrouter.say('{"protein_g": 40, "calories": 700}')

    response = ai_app_client.post(
        "/api/nutrition/analyze",
        data={"comment": "cuisson à l'huile d'olive"},
        files={"photo": ("assiette.png", png(), "image/png")},
        headers=auth,
    )

    assert response.status_code == 200
    assert openrouter.calls[0].with_image is True
    assert "huile d'olive" in openrouter.calls[0].prompt


def test_estimating_nothing_at_all_is_refused(
    ai_app_client: TestClient, auth: dict[str, str]
) -> None:
    """Les deux entrées sont facultatives séparément, jamais ensemble."""
    response = ai_app_client.post("/api/nutrition/analyze", headers=auth)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_a_blank_description_is_not_a_description(
    ai_app_client: TestClient, auth: dict[str, str]
) -> None:
    response = ai_app_client.post("/api/nutrition/analyze", data={"comment": "   "}, headers=auth)

    assert response.status_code == 422
