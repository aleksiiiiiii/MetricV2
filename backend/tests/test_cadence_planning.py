"""Le pont Cadence côté planning et assistant (**D5**).

Deux règles portent tout le lot, et chacune a le même motif :

* **Le lien vit dans la note**, et nulle part ailleurs. `plan.csv` ne gagne aucune colonne.
* **Le modèle ne fabrique jamais d'adresse.** Il nomme un circuit ; le serveur construit.
  Une URL écrite par un modèle est du texte non vérifié, et le suffixe `x` du format s'y
  perd en silence — quinze répétitions deviennent quinze secondes, la séance se lance, et
  elle est fausse.
"""

from __future__ import annotations

from datetime import date as day_of
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.domains.planning import ical
from app.domains.planning.schemas import PlannedSession
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

ACTIVITY = "/api/activity"
PLANNING = "/api/planning"
PLAN_FILE = "Metric/planning/plan.csv"
SETTINGS_FILE = "Metric/settings/settings.csv"

BASE = "https://cadence.exemple.fr"

PARIS = ZoneInfo("Europe/Paris")
STAMP = datetime(2026, 8, 4, 9, 30, tzinfo=PARIS)


def planned(**fields: Any) -> PlannedSession:
    """Une séance prévue, pour éprouver le rendu iCal sans passer par le stockage."""
    base: dict[str, Any] = {
        "id": 0,
        "token": "jeton",
        "session_id": "abc123",
        "date": day_of(2026, 12, 1),
        "time": "18:30",
        "kind": "muscu",
        "title": "Gainage du soir",
        "duration_min": 20,
        "source": "manual",
    }
    return PlannedSession(**{**base, **fields})


@pytest.fixture
def app_client(client: TestClient, store: FileStore) -> TestClient:
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


@pytest.fixture
def linked(dav: FakeWebDav) -> None:
    dav.seed(SETTINGS_FILE, f"key,value\ncadence_base_url,{BASE}\n")


def make_circuit(client: TestClient, auth: dict[str, str]) -> Any:
    response = client.post(
        f"{ACTIVITY}/circuits",
        json={
            "name": "Gainage",
            "rounds": 2,
            "round_rest_s": 60,
            "exercises": [
                {"name": "Plank", "muscle_group": "abdos", "duration_s": 60, "rest_s": 30}
            ],
        },
        headers=auth,
    )
    assert response.status_code == 201, response.text
    return response.json()


def plan(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    body: dict[str, Any] = {
        "date": "2026-12-01",
        "kind": "muscu",
        "title": "Gainage du soir",
        "duration_min": 20,
    }
    body.update(fields)
    return client.post(f"{PLANNING}/sessions", json=body, headers=auth)


# ── Le lien dans la note (**D5**) ─────────────────────


def test_a_planned_session_carries_the_link_in_its_note(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav, linked: None
) -> None:
    """Aucune colonne nouvelle : le raccourci est assumé, et c'est la note qui porte."""
    circuit = make_circuit(app_client, auth)

    response = plan(app_client, auth, circuit_id=circuit["circuit_id"])

    assert response.status_code == 201, response.text
    assert circuit["url"] in response.json()["note"]
    assert dav.content_of(PLAN_FILE).splitlines()[0] == (
        "id,date,time,kind,title,duration_min,note,source"
    )


def test_the_server_extracts_the_link_so_the_screen_does_not(
    app_client: TestClient, auth: dict[str, str], linked: None
) -> None:
    """Reconnaître une adresse Cadence dans du texte libre est une règle du format.

    La laisser au client en ferait une seconde implémentation, qui divergerait de
    celle-ci au premier cas limite.
    """
    circuit = make_circuit(app_client, auth)
    created = plan(app_client, auth, circuit_id=circuit["circuit_id"]).json()

    assert created["workout_url"] == circuit["url"]


def test_a_link_typed_by_hand_into_a_note_is_recognised_too(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """L'extraction ne connaît pas la provenance de la note — seulement le format."""
    created = plan(
        app_client,
        auth,
        note=f"À faire au réveil : {BASE}?w=Gainage~1~0~Plank:60s:0 (léger)",
    ).json()

    assert created["workout_url"] == f"{BASE}?w=Gainage~1~0~Plank:60s:0"


def test_a_note_without_a_readable_workout_has_no_link(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """C'est `parse_url` qui tranche, pas « ça ressemble à une URL » : l'écran ne doit
    jamais proposer d'ouvrir un lien mort."""
    created = plan(app_client, auth, note="Voir https://exemple.fr/notes").json()

    assert created["workout_url"] is None


def test_an_unknown_circuit_is_ignored_rather_than_losing_the_session(
    app_client: TestClient, auth: dict[str, str], linked: None
) -> None:
    """Refuser toute la séance prévue parce qu'un modèle a nommé un circuit supprimé
    coûterait plus que ça ne protège : le jour, l'heure et le titre sont justes."""
    response = plan(app_client, auth, circuit_id="fantome")

    assert response.status_code == 201
    assert response.json()["workout_url"] is None
    assert response.json()["title"] == "Gainage du soir"


def test_without_a_base_address_no_link_is_pasted(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Sans adresse réglée, le circuit n'a pas d'URL — donc rien à coller (**D1**)."""
    circuit = make_circuit(app_client, auth)

    created = plan(app_client, auth, circuit_id=circuit["circuit_id"]).json()

    assert created["note"] is None
    assert created["workout_url"] is None


def test_deleting_the_circuit_leaves_the_planned_session_openable(
    app_client: TestClient, auth: dict[str, str], linked: None
) -> None:
    """Une URL Cadence porte la séance entière : c'est le seul endroit où l'absence de
    base de données joue en notre faveur."""
    circuit = make_circuit(app_client, auth)
    plan(app_client, auth, circuit_id=circuit["circuit_id"])

    app_client.delete(
        f"{ACTIVITY}/circuits/{circuit['id']}", headers={**auth, "If-Match": circuit["token"]}
    )

    month = app_client.get(f"{PLANNING}/month?month=2026-12", headers=auth).json()
    planned = [item for day in month["days"] for item in day["planned"]]
    assert planned[0]["workout_url"] == circuit["url"]


# ── Le flux iCal ──────────────────────────────────────


def test_the_calendar_feed_carries_the_link_as_a_real_url() -> None:
    """`URL` est une propriété standard d'un `VEVENT` (§3.8.4.6), et les calendriers
    l'affichent en lien ouvrable.

    Conséquence concrète : une séance prévue s'ouvre dans Cadence **depuis le calendrier
    iOS**, sans passer par Metric. Vu le geste réel — on regarde son calendrier le matin —
    c'est probablement le chemin le plus emprunté du lot, pour une ligne de rendu.
    """
    url = f"{BASE}?w=Gainage~2~60~Plank:60s:30"
    body = ical.render(
        [planned(note=f"Séance du soir {url}", workout_url=url)], stamp=STAMP, tz=PARIS
    )

    # Le dépliage des lignes longues (§3.1) coupe l'URL : on le défait avant de comparer.
    assert f"URL:{url}" in body.replace("\r\n ", "")


def test_a_session_without_a_link_has_no_url_property() -> None:
    body = ical.render([planned(note="Séance libre")], stamp=STAMP, tz=PARIS)

    assert "URL:" not in body


def test_the_link_is_not_escaped_like_free_text() -> None:
    """La RFC type `URL` en `URI`, où le point-virgule et la virgule ne sont pas des
    séparateurs. Les échapper comme du texte donnerait une adresse que le calendrier
    ouvrirait sur une page d'erreur."""
    url = f"{BASE}?w=A%2CB~1~0~Plank:60s:0"
    body = ical.render([planned(note=url, workout_url=url)], stamp=STAMP, tz=PARIS)

    assert f"URL:{url}" in body.replace("\r\n ", "")
