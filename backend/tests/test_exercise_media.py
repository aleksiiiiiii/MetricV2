"""La démonstration d'un exercice, et les trois façons de ne pas en avoir.

Aucun appel réseau : un faux catalogue est monté en ASGI, comme `fake_openrouter.py` le
fait pour le modèle. Ce que ces tests défendent tient en une phrase — **une instance
éteinte ne doit jamais faire échouer l'ouverture d'une feuille de charge.**
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import httpx2
import pytest

from app.domains.activity import exercise_media

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

BASE = "https://ct.exemple.fr/?key=274"

CATALOG: dict[str, Any] = {
    "media": {"thumb": "exercise-db/images/", "gif": "exercise-db/gifs/"},
    "exercises": [
        {"i": "0001", "n": "3/4 sit-up", "f": "0001-2gPfomN"},
        {"i": "0025", "n": "Barbell Full Squat", "f": "0025-AbCdEf"},
        # Sans média : l'entrée existe dans le catalogue, mais rien à montrer.
        {"i": "0099", "n": "exercice sans image"},
    ],
}


class FakeCadence:
    """L'instance de l'utilisateur, réduite à ce qu'on lui demande ici."""

    def __init__(self, *, status: int = 200, body: Any = CATALOG) -> None:
        self.status = status
        self.body = body
        #: Les adresses demandées, dans l'ordre. C'est par là qu'on vérifie que le
        #: catalogue n'est relu ni à chaque appel, ni sans sa clé.
        self.calls: list[str] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        query = scope.get("query_string", b"").decode()
        self.calls.append(f"{scope['path']}?{query}" if query else str(scope["path"]))

        payload = json.dumps(self.body).encode()
        await send(
            {
                "type": "http.response.start",
                "status": self.status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": payload})


@pytest.fixture
def cadence() -> Any:
    """Monte le faux catalogue, et laisse le cache vide de part et d'autre du test."""
    fake = FakeCadence()
    exercise_media.forget()
    exercise_media.transport = httpx2.ASGITransport(app=fake)
    try:
        yield fake
    finally:
        exercise_media.transport = None
        exercise_media.forget()


# ── L'adresse rendue ──────────────────────────────────


async def test_the_address_keeps_the_access_key_of_the_base(cadence: FakeCadence) -> None:
    """**Sans la clé, chaque média répond 403.** L'adresse du GIF hérite donc la query
    string de la base — c'est la même exposition que le lien de séance, pas une nouvelle."""
    url = await exercise_media.demo_url(BASE, "3/4 sit-up")

    assert url == "https://ct.exemple.fr/exercise-db/gifs/0001-2gPfomN.gif?key=274"


async def test_the_catalog_is_asked_with_the_key_too(cadence: FakeCadence) -> None:
    await exercise_media.demo_url(BASE, "3/4 sit-up")

    assert cadence.calls == ["/exercise-db/catalog.json?key=274"]


async def test_a_base_without_a_query_string_still_works(cadence: FakeCadence) -> None:
    """Une instance ouverte n'a pas de clé : l'adresse ne gagne pas de `?` vide."""
    url = await exercise_media.demo_url("https://ct.exemple.fr", "3/4 sit-up")

    assert url == "https://ct.exemple.fr/exercise-db/gifs/0001-2gPfomN.gif"


async def test_the_match_ignores_case_and_punctuation(cadence: FakeCadence) -> None:
    """`fold`, et rien de plus : le catalogue écrit « Barbell Full Squat », la charge peut
    porter la même chose en minuscules."""
    assert await exercise_media.demo_url(BASE, "barbell full squat") is not None


# ── Les trois façons de n'avoir pas d'image ───────────


async def test_no_base_address_asks_nothing_at_all(cadence: FakeCadence) -> None:
    """La fonctionnalité en sommeil ne doit pas produire une requête par ouverture."""
    assert await exercise_media.demo_url("", "3/4 sit-up") is None
    assert cadence.calls == []


async def test_an_unknown_name_has_no_demonstration(cadence: FakeCadence) -> None:
    """Un nom écrit à la main sans correspondance **exacte** : c'est l'état normal, et la
    spécification de Cadence le dit bénin. On ne rapproche pas approximativement."""
    assert await exercise_media.demo_url(BASE, "développé Aleksi") is None


async def test_an_exercise_without_media_is_not_offered_a_dead_image(
    cadence: FakeCadence,
) -> None:
    assert await exercise_media.demo_url(BASE, "exercice sans image") is None


async def test_an_unreachable_instance_gives_no_url_and_no_error(cadence: FakeCadence) -> None:
    """**Le test qui porte le lot.** Une instance éteinte décore moins une feuille ; elle
    ne doit pas empêcher de lire la charge et la courbe, qui sont ce qu'on venait voir."""
    cadence.status = 503

    assert await exercise_media.demo_url(BASE, "3/4 sit-up") is None


async def test_a_catalog_that_is_not_json_gives_no_url_either(cadence: FakeCadence) -> None:
    """Une page d'erreur HTML servie en 200 par un proxy : le décodage échoue, et le
    résultat est le même qu'une panne — pas d'image, pas d'incident."""
    cadence.body = "<html>403 Forbidden</html>"

    assert await exercise_media.demo_url(BASE, "3/4 sit-up") is None


# ── Le cache ──────────────────────────────────────────


async def test_the_catalog_is_read_once_for_many_exercises(cadence: FakeCadence) -> None:
    """128 ko par ouverture de feuille rendraient un geste instantané perceptible."""
    await exercise_media.demo_url(BASE, "3/4 sit-up")
    await exercise_media.demo_url(BASE, "barbell full squat")
    await exercise_media.demo_url(BASE, "3/4 sit-up")

    assert len(cadence.calls) == 1


async def test_a_failed_read_is_not_cached(cadence: FakeCadence) -> None:
    """Une instance éteinte au premier essai ne doit pas condamner les six heures qui
    suivent : c'est le cas courant d'un serveur qui redémarre."""
    cadence.status = 503
    assert await exercise_media.demo_url(BASE, "3/4 sit-up") is None

    cadence.status = 200
    assert await exercise_media.demo_url(BASE, "3/4 sit-up") is not None


async def test_changing_the_base_address_asks_the_new_one(cadence: FakeCadence) -> None:
    """Le cache est indexé par adresse : corriger le réglage ne doit pas continuer de
    servir le catalogue de l'ancienne instance."""
    await exercise_media.demo_url(BASE, "3/4 sit-up")
    await exercise_media.demo_url("https://autre.exemple.fr/?key=999", "3/4 sit-up")

    assert len(cadence.calls) == 2
