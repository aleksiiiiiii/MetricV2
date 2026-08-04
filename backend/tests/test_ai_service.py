"""Découverte des modèles et cascade (`IA-02` → `IA-04`, `IA-07`, `L12-16`).

Tout se joue sur `tests/fake_openrouter.py` : c'est ce qui permet de scénariser un `429` en
cascade, un catalogue sans modèle vision ou une réponse tronquée — trois situations qu'on
ne peut pas obtenir à la demande du vrai service.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import AiQuotaError, AiUnavailableError
from app.domains.ai.client import OpenRouterClient, parse_models
from app.domains.ai.service import MAX_ATTEMPTS, AiService, ModelCatalogue
from tests.fake_openrouter import FakeOpenRouter, Reply, free_model

CONSIGNE = "Réponds en JSON."


def service(client: OpenRouterClient, *, preferred: str = "") -> AiService:
    return AiService(client, ModelCatalogue(client), preferred=preferred)


# ── Découverte du catalogue (`IA-02`) ─────────────────


def test_paid_models_are_left_out() -> None:
    payload = {"data": [free_model("libre/a"), free_model("payant/b", free=False)]}

    assert [model.id for model in parse_models(payload)] == ["libre/a"]


def test_a_variable_price_is_not_a_free_price() -> None:
    """`openrouter/auto` annonce `"-1"` : « variable », donc facturé au tarif du routage.

    Trouvé en interrogeant le **vrai** catalogue, le 2026-07-31 : le routeur y passait pour
    gratuit et la cascade aurait pu y descendre. Aucune entrée simulée n'aurait eu l'idée
    d'un prix négatif — c'est précisément ce que la passe réelle était censée révéler.
    """
    router = free_model("openrouter/auto")
    router["pricing"] = {"prompt": "-1", "completion": "-1"}

    assert parse_models({"data": [router, free_model("vendeur/vrai-gratuit-8b")]}) == [
        parse_models({"data": [free_model("vendeur/vrai-gratuit-8b")]})[0]
    ]


def test_moderation_embedding_and_speech_models_are_left_out() -> None:
    """Ils sont dans le catalogue gratuit et ne répondent à aucune consigne : les laisser
    entrer ferait échouer la cascade un modèle à la fois, en y passant du temps."""
    payload = {
        "data": [
            free_model("vendeur/chat-8b"),
            free_model("vendeur/text-embedding-3"),
            free_model("vendeur/llama-guard-3"),
            free_model("vendeur/whisper-large"),
            free_model("vendeur/rerank-2"),
        ]
    }

    assert [model.id for model in parse_models(payload)] == ["vendeur/chat-8b"]


def test_a_model_that_cannot_produce_text_is_left_out() -> None:
    entry = free_model("vendeur/image-seule")
    entry["architecture"]["output_modalities"] = ["image"]

    assert parse_models({"data": [entry]}) == []


def test_a_model_that_also_produces_something_else_is_left_out() -> None:
    """`google/lyria-3-clip-preview` annonce `["text", "audio"]` : il compose de la musique.

    Second cas trouvé sur le vrai catalogue le 2026-07-31. Un test « text est parmi les
    sorties » le laissait entrer — et il figurait dans les modèles vision retenus, donc
    joignable par la cascade d'une analyse de photo.
    """
    music = free_model("google/lyria-3-clip-preview")
    music["architecture"]["output_modalities"] = ["text", "audio"]

    assert parse_models({"data": [music]}) == []


def test_a_model_that_merely_accepts_many_inputs_stays() -> None:
    """La règle porte sur ce qui **sort**, pas sur ce qui entre.

    Les modèles « omni » acceptent audio et vidéo et ne rendent que du texte : ce sont des
    lecteurs de consigne parfaitement valables, et les écarter viderait le catalogue.
    """
    omni = free_model("nvidia/nemotron-omni-30b")
    omni["architecture"]["input_modalities"] = ["text", "audio", "image", "video"]

    assert [model.id for model in parse_models({"data": [omni]})] == ["nvidia/nemotron-omni-30b"]


def test_models_are_ranked_by_size_then_context() -> None:
    """`IA-02` demande un classement. La taille lue dans l'identifiant en est le proxy."""
    payload = {
        "data": [
            free_model("vendeur/petit-8b", context=200000),
            free_model("vendeur/grand-70b", context=32000),
            free_model("vendeur/moyen-27b", context=64000),
        ]
    }

    assert [model.id for model in parse_models(payload)] == [
        "vendeur/grand-70b",
        "vendeur/moyen-27b",
        "vendeur/petit-8b",
    ]


def test_a_model_without_an_announced_size_comes_last_but_stays() -> None:
    payload = {"data": [free_model("vendeur/anonyme"), free_model("vendeur/dit-sa-taille-8b")]}

    assert [model.id for model in parse_models(payload)] == [
        "vendeur/dit-sa-taille-8b",
        "vendeur/anonyme",
    ]


def test_a_malformed_entry_does_not_break_the_catalogue() -> None:
    """Le catalogue est un fichier distant que personne ici ne contrôle."""
    payload = {"data": ["texte", {"pas_d_id": True}, None, free_model("vendeur/valide-8b")]}

    assert [model.id for model in parse_models(payload)] == ["vendeur/valide-8b"]


async def test_the_catalogue_is_fetched_once_and_kept_an_hour(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    """`IA-02` : mémorisé une heure. Sans cela, chaque photo coûterait un appel de plus."""
    catalogue = ModelCatalogue(ai_client)

    await catalogue.all()
    await catalogue.all()

    assert openrouter.models_calls == 1


async def test_the_catalogue_is_refetched_once_the_hour_has_passed(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    now = 0.0
    catalogue = ModelCatalogue(ai_client, clock=lambda: now)

    await catalogue.all()
    now = 3601.0
    await catalogue.all()

    assert openrouter.models_calls == 2


# ── Cascade (`IA-03`) ─────────────────────────────────


async def test_the_first_usable_answer_wins(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    openrouter.say('{"protein_g": 32}')

    result = await service(ai_client).ask_json(instruction=CONSIGNE, prompt="…")

    assert result == {"protein_g": 32}
    assert len(openrouter.calls) == 1


async def test_a_saturated_model_hands_over_to_the_next(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    """`L12-16` : `429` en cascade. Le second modèle répond, l'utilisateur ne voit rien.

    L'ordre est celui du classement — par taille — et non celui du catalogue reçu : le
    `13b` texte passe avant le `8b` vision, puisque l'appel ne porte pas d'image.
    """
    openrouter.replies = [Reply.quota(), Reply.says('{"protein_g": 30}')]

    result = await service(ai_client).ask_json(instruction=CONSIGNE, prompt="…")

    assert result == {"protein_g": 30}
    assert [call.model for call in openrouter.calls] == [
        "vendeur/grand-vision-70b",
        "vendeur/texte-seul-13b",
    ]


async def test_a_quota_announced_inside_a_200_is_still_a_quota(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    """OpenRouter le fait : le routage réussit, le fournisseur en aval refuse."""
    openrouter.replies = [Reply.quota_in_200(), Reply.says('{"ok": 1}')]

    assert await service(ai_client).ask_json(instruction=CONSIGNE, prompt="…") == {"ok": 1}


async def test_an_unusable_answer_hands_over_to_the_next(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    """`L12-16` : JSON tronqué. Rien n'est complété — on passe au modèle suivant."""
    openrouter.replies = [
        Reply.says('{"protein_g": 32, "calories": 6'),
        Reply.says('{"protein_g": 31}'),
    ]

    assert await service(ai_client).ask_json(instruction=CONSIGNE, prompt="…") == {"protein_g": 31}


async def test_a_mute_model_hands_over_to_the_next(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    openrouter.replies = [Reply.mute(), Reply.says('{"protein_g": 29}')]

    assert await service(ai_client).ask_json(instruction=CONSIGNE, prompt="…") == {"protein_g": 29}


async def test_every_model_saturated_says_quota_and_not_failure(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    """La distinction que `IA-03` exige : attendre y changera quelque chose."""
    openrouter.replies = [Reply.quota(), Reply.quota(), Reply.quota()]

    with pytest.raises(AiQuotaError) as caught:
        await service(ai_client).ask_json(instruction=CONSIGNE, prompt="…")

    assert caught.value.code == "ai_quota"
    assert "Réessaie" in caught.value.message


async def test_one_real_failure_among_the_quotas_is_not_a_quota(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    """Attendre ne réparerait pas une panne : le message ne doit pas le laisser croire."""
    openrouter.replies = [Reply.quota(), Reply.broken(), Reply.quota()]

    with pytest.raises(AiUnavailableError) as caught:
        await service(ai_client).ask_json(instruction=CONSIGNE, prompt="…")

    assert caught.value.code == "ai_unavailable"


async def test_the_cascade_stops_after_three_models(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    """Bornée : l'utilisateur préfère un refus clair à trois minutes d'attente."""
    openrouter.models = [free_model(f"vendeur/modele-{index}b") for index in range(9, 0, -1)]
    openrouter.replies = [Reply.quota() for _ in range(9)]

    with pytest.raises(AiQuotaError):
        await service(ai_client).ask_json(instruction=CONSIGNE, prompt="…")

    assert len(openrouter.calls) == MAX_ATTEMPTS


# ── Vision (`IA-04`) ──────────────────────────────────


async def test_an_image_only_goes_to_models_that_read_images(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    """Un modèle texte répondrait quand même — en inventant depuis le seul énoncé."""
    openrouter.replies = [Reply.quota(), Reply.quota()]

    with pytest.raises(AiQuotaError):
        await service(ai_client).ask_json(
            instruction=CONSIGNE, prompt="…", image_url="data:image/jpeg;base64,AAA"
        )

    tried = [call.model for call in openrouter.calls]
    assert tried == ["vendeur/grand-vision-70b", "vendeur/petit-vision-8b"]
    assert "vendeur/texte-seul-13b" not in tried


async def test_the_image_travels_with_the_prompt(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    openrouter.say('{"ok": 1}')

    await service(ai_client).ask_json(
        instruction=CONSIGNE, prompt="…", image_url="data:image/jpeg;base64,AAA"
    )

    assert openrouter.calls[0].with_image
    assert openrouter.calls[0].image_url == "data:image/jpeg;base64,AAA"


async def test_a_catalogue_without_any_vision_model_says_so_rather_than_guessing(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    openrouter.models = [free_model("vendeur/texte-13b", vision=False)]

    with pytest.raises(AiUnavailableError):
        await service(ai_client).ask_json(
            instruction=CONSIGNE, prompt="…", image_url="data:image/jpeg;base64,AAA"
        )

    assert openrouter.calls == []


# ── Modèle préféré (`IA-01`) ──────────────────────────


async def test_the_configured_model_is_tried_first(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    openrouter.replies = [Reply.quota(), Reply.says('{"ok": 1}')]

    await service(ai_client, preferred="vendeur/petit-vision-8b").ask_json(
        instruction=CONSIGNE, prompt="…"
    )

    assert openrouter.calls[0].model == "vendeur/petit-vision-8b"


async def test_a_configured_model_absent_from_the_catalogue_is_still_tried(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    """Il peut être payant — auquel cas il a été choisi en connaissance de cause."""
    openrouter.say('{"ok": 1}')

    await service(ai_client, preferred="vendeur/paye-par-l-utilisateur").ask_json(
        instruction=CONSIGNE, prompt="…"
    )

    assert openrouter.calls[0].model == "vendeur/paye-par-l-utilisateur"


async def test_an_unreachable_catalogue_does_not_sink_the_configured_model(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    """C'est justement le cas où ce réglage sert à quelque chose."""
    openrouter.models_status = 503
    openrouter.say('{"ok": 1}')

    result = await service(ai_client, preferred="vendeur/grand-vision-70b").ask_json(
        instruction=CONSIGNE, prompt="…"
    )

    assert result == {"ok": 1}


async def test_an_unreachable_catalogue_without_a_configured_model_fails_clearly(
    ai_client: OpenRouterClient, openrouter: FakeOpenRouter
) -> None:
    openrouter.models_status = 503

    with pytest.raises(AiUnavailableError) as caught:
        await service(ai_client).ask_json(instruction=CONSIGNE, prompt="…")

    assert "manuelle" in caught.value.message
