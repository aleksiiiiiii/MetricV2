"""Import Apple Fitness (`IMP-01` → `IMP-06`, `L12-16`).

Deux moitiés, et leur séparation est tout le sujet : ce qui lit une capture n'écrit rien,
ce qui écrit ne lit aucune image. Entre les deux, un appui de l'utilisateur.
"""

from __future__ import annotations

import io
from datetime import date

import httpx2
from fastapi.testclient import TestClient
from PIL import Image

from app.domains.imports.analysis import is_unreadable, read_draft
from tests.fake_openrouter import FakeOpenRouter, Reply
from tests.fake_webdav import FakeWebDav

RUNS_FILE = "Metric/activity/runs.csv"
WORKOUTS_FILE = "Metric/activity/workouts.csv"
TODAY = date(2026, 7, 30)


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 900), "black").save(buffer, format="PNG")
    return buffer.getvalue()


def analyze(client: TestClient, auth: dict[str, str]) -> httpx2.Response:
    return client.post(
        "/api/import/apple/analyze",
        files={"screenshot": ("capture.png", png(), "image/png")},
        headers=auth,
    )


# ── Conversions (`IMP-03`) ────────────────────────────


def test_miles_become_kilometres() -> None:
    """Une montre réglée en impérial : la conversion se fait chez nous, pas chez le modèle."""
    draft = read_draft({"kind": "run", "distance": "5,20 MI", "duration": "44:12"}, today=TODAY)

    assert draft.distance_km == 8.369


def test_kilometres_stay_kilometres() -> None:
    draft = read_draft({"kind": "run", "distance": "8,40 KM", "duration": "44:12"}, today=TODAY)

    assert draft.distance_km == 8.4


def test_a_clock_duration_becomes_decimal_minutes() -> None:
    draft = read_draft({"kind": "workout", "duration": "28:45"}, today=TODAY)

    assert draft.duration_min == 28.75


def test_a_long_duration_keeps_its_hours() -> None:
    draft = read_draft({"kind": "workout", "duration": "1:18:44"}, today=TODAY)

    assert draft.duration_min == 78.73


def test_yesterday_becomes_an_absolute_date() -> None:
    draft = read_draft({"kind": "workout", "duration": "30:00", "date": "Hier"}, today=TODAY)

    assert draft.date == date(2026, 7, 29)


def test_a_relative_number_of_days_becomes_an_absolute_date() -> None:
    draft = read_draft(
        {"kind": "workout", "duration": "30:00", "date": "il y a 3 jours"}, today=TODAY
    )

    assert draft.date == date(2026, 7, 27)


def test_a_weekday_means_the_one_that_has_passed() -> None:
    """Le 30/07/2026 est un jeudi : « lundi » est trois jours plus tôt, jamais dans quatre."""
    draft = read_draft({"kind": "workout", "duration": "30:00", "date": "Lundi"}, today=TODAY)

    assert draft.date == date(2026, 7, 27)


def test_a_day_and_month_without_a_year_takes_the_one_that_is_not_future() -> None:
    draft = read_draft({"kind": "workout", "duration": "30:00", "date": "28/12"}, today=TODAY)

    assert draft.date == date(2025, 12, 28)


def test_a_future_date_is_left_empty_rather_than_corrected() -> None:
    """On ne relève pas ce qui n'a pas eu lieu, et on ne devine pas ce qui était voulu."""
    draft = read_draft({"kind": "workout", "duration": "30:00", "date": "2027-01-01"}, today=TODAY)

    assert draft.date is None
    assert "date" in draft.missing


def test_an_unreadable_date_is_left_empty() -> None:
    draft = read_draft(
        {"kind": "workout", "duration": "30:00", "date": "la semaine dernière"}, today=TODAY
    )

    assert draft.date is None


# ── Valeurs absentes (`IMP-03`) ───────────────────────


def test_a_missing_value_stays_empty_and_is_named() -> None:
    """« Les valeurs absentes restent vides plutôt qu'inventées » — et l'écran peut le dire."""
    draft = read_draft(
        {"kind": "run", "distance": "8,40 KM", "duration": "44:12", "date": "Hier"}, today=TODAY
    )

    assert draft.avg_hr is None
    assert draft.elevation_m is None
    assert draft.calories is None
    # L'allure et la cadence rejoignent la liste : une capture Apple Fitness les affiche,
    # et ne pas les nommer laisserait croire qu'on ne les a pas cherchées.
    assert draft.missing == ["pace_min_km", "cadence_spm", "avg_hr", "elevation_m", "calories"]


def test_the_ways_a_model_writes_nothing_are_all_nothing() -> None:
    """`null`, `"N/A"`, `"—"` : un tiret ne doit pas devenir une fréquence cardiaque."""
    draft = read_draft(
        {
            "kind": "workout",
            "duration": "30:00",
            "avg_hr": "—",
            "elevation_m": "N/A",
            "calories": "null",
        },
        today=TODAY,
    )

    assert (draft.avg_hr, draft.elevation_m, draft.calories) == (None, None, None)


def test_a_number_with_its_unit_is_read() -> None:
    draft = read_draft(
        {"kind": "workout", "duration": "30:00", "avg_hr": "152 bpm", "calories": "412 kcal"},
        today=TODAY,
    )

    assert draft.avg_hr == 152
    assert draft.calories == 412


def test_an_absurd_heart_rate_is_dropped_not_kept() -> None:
    """1852 battements par minute : le modèle a lu autre chose que la fréquence."""
    draft = read_draft({"kind": "workout", "duration": "30:00", "avg_hr": "1852"}, today=TODAY)

    assert draft.avg_hr is None


def test_a_run_without_a_distance_is_offered_as_a_workout() -> None:
    """Sinon le pré-remplissage serait impossible à valider : l'allure exige une distance."""
    draft = read_draft({"kind": "run", "duration": "30:00"}, today=TODAY)

    assert draft.kind == "workout"


# ── Analyse de bout en bout ───────────────────────────


def test_a_screenshot_prefills_a_run(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """La DoD du lot : une capture pré-remplit une course en une action."""
    openrouter.say(
        '{"kind": "run", "activity": "Course à pied", "date": "Hier", '
        '"distance": "5,20 MI", "duration": "44:12", "avg_hr": "152", "calories": "620"}'
    )

    response = analyze(ai_app_client, auth)

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "run"
    assert body["distance_km"] == 8.369
    assert body["duration_min"] == 44.2
    assert body["avg_hr"] == 152
    assert body["workout_type"] == "Course à pied"


def test_analyzing_a_screenshot_writes_nothing(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, dav: FakeWebDav, auth: dict[str, str]
) -> None:
    """`IMP-01` : l'endpoint analyse seulement."""
    openrouter.say('{"kind": "run", "date": "Hier", "distance": "8,40 KM", "duration": "44:12"}')
    before = dict(dav.files)

    analyze(ai_app_client, auth)

    assert dict(dav.files) == before


def test_a_chatty_answer_is_still_read(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    openrouter.say(
        "<think>Je vois un écran Apple Fitness. La distance est en miles.</think>\n"
        'Voici : {"kind": "run", "date": "Hier", "distance": "3,10 MI", "duration": "28:45"}'
    )

    body = analyze(ai_app_client, auth).json()

    assert body["duration_min"] == 28.75


# ── Capture illisible (`IMP-06`) ──────────────────────


def test_a_screenshot_that_is_not_an_activity_says_so(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    openrouter.say('{"readable": false}')

    response = analyze(ai_app_client, auth)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "ai_unreadable"
    # Le message dit quoi faire ensuite : refaire la capture, ou saisir à la main.
    assert "main" in body["message"]


def test_a_screenshot_without_a_duration_or_a_distance_is_unreadable(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """Un formulaire vide présenté comme un import réussi serait pire qu'un refus."""
    openrouter.say('{"kind": "workout", "activity": "Musculation"}')

    assert analyze(ai_app_client, auth).status_code == 422


def test_a_quota_is_still_told_apart_from_an_unreadable_capture(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    openrouter.replies = [Reply.quota(), Reply.quota(), Reply.quota()]

    response = analyze(ai_app_client, auth)

    assert response.status_code == 503
    assert response.json()["code"] == "ai_quota"


# ── Doublon probable (`IMP-04`) ───────────────────────


def test_an_activity_of_the_same_day_and_duration_raises_a_warning(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, dav: FakeWebDav, auth: dict[str, str]
) -> None:
    dav.seed(
        RUNS_FILE,
        "date,distance_km,duration_min,pace_min_km,avg_hr,elevation_m,note,source\n"
        "2026-07-29,8.40,44.2,5.26,,,,manual\n",
    )
    openrouter.say(
        '{"kind": "run", "date": "2026-07-29", "distance": "8,40 KM", "duration": "44:15"}'
    )

    body = analyze(ai_app_client, auth).json()

    assert body["duplicate"] is not None
    assert body["duplicate"]["date"] == "2026-07-29"
    assert body["duplicate"]["kind"] == "run"


def test_a_duration_more_than_a_minute_apart_is_not_a_duplicate(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, dav: FakeWebDav, auth: dict[str, str]
) -> None:
    dav.seed(
        RUNS_FILE,
        "date,distance_km,duration_min,pace_min_km,avg_hr,elevation_m,note,source\n"
        "2026-07-29,8.40,44.2,5.26,,,,manual\n",
    )
    openrouter.say(
        '{"kind": "run", "date": "2026-07-29", "distance": "6,10 KM", "duration": "32:40"}'
    )

    assert analyze(ai_app_client, auth).json()["duplicate"] is None


def test_the_same_duration_on_another_day_is_not_a_duplicate(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, dav: FakeWebDav, auth: dict[str, str]
) -> None:
    dav.seed(
        RUNS_FILE,
        "date,distance_km,duration_min,pace_min_km,avg_hr,elevation_m,note,source\n"
        "2026-07-20,8.40,44.2,5.26,,,,manual\n",
    )
    openrouter.say(
        '{"kind": "run", "date": "2026-07-29", "distance": "8,40 KM", "duration": "44:12"}'
    )

    assert analyze(ai_app_client, auth).json()["duplicate"] is None


def test_a_duplicate_does_not_block_the_import(
    ai_app_client: TestClient, dav: FakeWebDav, auth: dict[str, str]
) -> None:
    """Un avertissement, jamais un refus : deux sorties le même jour, cela existe."""
    dav.seed(
        RUNS_FILE,
        "date,distance_km,duration_min,pace_min_km,avg_hr,elevation_m,note,source\n"
        "2026-07-29,8.40,44.2,5.26,,,,manual\n",
    )

    response = ai_app_client.post(
        "/api/import/apple",
        json={
            "kind": "run",
            "date": "2026-07-29",
            "distance_km": "8,40",
            "duration_min": "44:12",
        },
        headers=auth,
    )

    assert response.status_code == 201


# ── Écriture après validation (`IMP-01`, `IMP-05`) ────


def test_a_validated_run_is_written_with_its_source(
    store_client: TestClient, dav: FakeWebDav, auth: dict[str, str]
) -> None:
    """`IMP-05` : l'origine d'une donnée est lisible jusque dans le fichier."""
    response = store_client.post(
        "/api/import/apple",
        json={
            "kind": "run",
            "date": "2026-07-28",
            "distance_km": "8,40",
            "duration_min": "44:12",
            "avg_hr": "152",
        },
        headers=auth,
    )

    assert response.status_code == 201
    assert response.json()["source"] == "apple"
    content = dav.content_of(RUNS_FILE)
    assert content.rstrip().endswith(",apple")


def test_a_validated_workout_is_written_with_its_source(
    store_client: TestClient, dav: FakeWebDav, auth: dict[str, str]
) -> None:
    response = store_client.post(
        "/api/import/apple",
        json={
            "kind": "workout",
            "date": "2026-07-28",
            "duration_min": "48:00",
            "type": "Vélo",
        },
        headers=auth,
    )

    assert response.status_code == 201
    assert response.json()["source"] == "apple"
    assert "apple" in dav.content_of(WORKOUTS_FILE)


def test_corrected_values_are_the_ones_written(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """`IMP-02` : le pré-remplissage est intégralement modifiable. Rien n'est réappliqué."""
    response = store_client.post(
        "/api/import/apple",
        json={
            "kind": "run",
            "date": "2026-07-28",
            "distance_km": "10",
            "duration_min": "50",
            "avg_hr": "140",
        },
        headers=auth,
    )

    body = response.json()
    assert body["distance_km"] == 10
    assert body["duration_min"] == 50


def test_an_imported_run_gets_its_pace_like_any_other(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """L'import passe par le service du domaine : il ne réinvente pas le format du fichier."""
    store_client.post(
        "/api/import/apple",
        json={
            "kind": "run",
            "date": "2026-07-28",
            "distance_km": "8,40",
            "duration_min": "44:12",
        },
        headers=auth,
    )

    history = store_client.get("/api/activity", headers=auth).json()
    assert history["history"][0]["pace_min_km"] is not None
    assert history["history"][0]["source"] == "apple"


def test_correcting_an_imported_run_does_not_make_it_manual(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """La provenance survit à une correction — c'est déjà la règle du domaine Corps."""
    created = store_client.post(
        "/api/import/apple",
        json={
            "kind": "run",
            "date": "2026-07-28",
            "distance_km": "8,40",
            "duration_min": "44:12",
        },
        headers=auth,
    )
    row_id = created.json()["id"]
    token = store_client.get(f"/api/activity/runs/{row_id}", headers=auth).json()["token"]

    corrected = store_client.patch(
        f"/api/activity/runs/{row_id}",
        json={"date": "2026-07-28", "distance_km": "8,50", "duration_min": "44:12"},
        headers={**auth, "If-Match": token},
    )

    assert corrected.json()["source"] == "apple"


def test_a_run_without_a_distance_is_refused_with_a_way_out(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    response = store_client.post(
        "/api/import/apple",
        json={"kind": "run", "date": "2026-07-28", "duration_min": "44:12"},
        headers=auth,
    )

    assert response.status_code == 422
    assert "séance" in response.text


def test_a_future_date_is_refused_like_any_other_entry(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """Un import ne mérite pas des règles plus laxistes qu'une saisie au clavier."""
    response = store_client.post(
        "/api/import/apple",
        json={
            "kind": "workout",
            "date": "2099-01-01",
            "duration_min": "30",
        },
        headers=auth,
    )

    assert response.status_code == 422


# ── Allure et cadence (C06) ───────────────────────────


def test_the_pace_is_read_from_the_screenshot_not_deduced() -> None:
    """Ce que l'écran montre en pointillé doit venir de l'image.

    Déduire l'allure de la distance et de la durée en ferait un calcul de notre propre
    code présenté comme une lecture — soit exactement ce que la marque « proposée » sert
    à distinguer.
    """
    draft = read_draft(
        {"kind": "run", "distance": "8,40 KM", "duration": "44:12", "pace": "5:16"}, today=TODAY
    )

    assert draft.pace_min_km == 5.267
    assert "pace_min_km" not in draft.missing


def test_a_pace_written_with_an_apostrophe_is_still_a_pace() -> None:
    """Apple écrit parfois `5'16"` plutôt que `5:16`."""
    draft = read_draft({"kind": "run", "duration": "44:12", "pace": "5’16"}, today=TODAY)

    assert draft.pace_min_km == 5.267


def test_an_absurd_pace_is_dropped() -> None:
    draft = read_draft({"kind": "run", "duration": "44:12", "pace": "0:12"}, today=TODAY)

    assert draft.pace_min_km is None


def test_the_cadence_is_read_and_bounded() -> None:
    assert read_draft({"kind": "run", "cadence_spm": "172"}, today=TODAY).cadence_spm == 172
    # 1720 pas par minute : le modèle a lu autre chose que la cadence.
    assert read_draft({"kind": "run", "cadence_spm": "1720"}, today=TODAY).cadence_spm is None


def test_a_run_with_only_a_pace_stays_a_run() -> None:
    """Le serveur calcule la distance depuis l'allure : la capture n'a plus à la porter.

    Avant, une capture sans distance était rétrogradée en séance — donc écrite dans le
    mauvais fichier, sans allure ni distance.
    """
    draft = read_draft({"kind": "run", "duration": "45", "pace": "5:00"}, today=TODAY)

    assert draft.kind == "run"


def test_a_screenshot_with_only_a_pace_is_not_unreadable() -> None:
    payload = {"kind": "run", "pace": "5:00", "duration": "45"}

    assert is_unreadable(payload, read_draft(payload, today=TODAY)) is False
