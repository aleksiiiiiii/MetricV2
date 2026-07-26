"""Domaine Corps (`BODY-01` → `BODY-10`).

Première tranche verticale : ce que ces tests valident au-delà du domaine lui-même,
c'est la chaîne complète CSV → dépôt → service → API, gardes de concurrence comprises.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.validation import today_local
from app.domains.body.service import WeightService
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

WEIGHT = "/api/body/weight"
MEASUREMENTS = "/api/body/measurements"
WEIGHT_FILE = "Metric/body/weight.csv"


@pytest.fixture
def app_client(client: TestClient, store: FileStore) -> TestClient:
    """Client authentifié dont le stockage est branché sur le double."""
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


def payload(day: str = "2026-07-20", weight: float = 68.4, **extra: Any) -> dict[str, Any]:
    return {"date": day, "weight_kg": weight, **extra}


def post(client: TestClient, auth: dict[str, str], **kwargs: Any) -> Any:
    response = client.post(WEIGHT, json=payload(**kwargs), headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


# ── Saisie (`BODY-01`) ────────────────────────────────


def test_a_weighing_is_written_to_the_csv(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    entry = post(app_client, auth, day="2026-07-20", weight=68.4, note="à jeun")

    assert entry["weight_kg"] == 68.4
    assert entry["source"] == "manual"
    content = dav.content_of(WEIGHT_FILE)
    assert content.splitlines()[0] == "date,weight_kg,note,source"
    assert "2026-07-20,68.4,à jeun,manual" in content


def test_a_future_date_is_refused(app_client: TestClient, auth: dict[str, str]) -> None:
    """`API-06` : on ne relève pas ce qui n'a pas eu lieu."""
    tomorrow = (today_local() + timedelta(days=1)).isoformat()

    response = app_client.post(WEIGHT, json=payload(day=tomorrow), headers=auth)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_today_is_accepted(app_client: TestClient, auth: dict[str, str]) -> None:
    response = app_client.post(WEIGHT, json=payload(day=today_local().isoformat()), headers=auth)

    assert response.status_code == 201


@pytest.mark.parametrize("weight", [0, -5, 501])
def test_an_implausible_weight_is_refused(
    app_client: TestClient, auth: dict[str, str], weight: float
) -> None:
    response = app_client.post(WEIGHT, json=payload(weight=weight), headers=auth)

    assert response.status_code == 422


# ── Correction et suppression (`BODY-02`, `STO-05`) ───


def test_a_weighing_can_be_corrected(app_client: TestClient, auth: dict[str, str]) -> None:
    entry = post(app_client, auth, weight=68.4)

    response = app_client.patch(
        f"{WEIGHT}/{entry['id']}",
        json=payload(weight=70.2),
        headers={**auth, "If-Match": entry["token"]},
    )

    assert response.status_code == 200
    assert response.json()["weight_kg"] == 70.2


def test_correcting_without_the_token_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Sans cela, la garde se contournerait en omettant simplement l'en-tête."""
    entry = post(app_client, auth)

    response = app_client.patch(f"{WEIGHT}/{entry['id']}", json=payload(weight=70.2), headers=auth)

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


def test_correcting_with_a_stale_token_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Le cas qui motive `STO-05` : l'app est ouverte sur deux appareils."""
    entry = post(app_client, auth, weight=68.4)
    stale = entry["token"]

    # L'autre appareil corrige la pesée entre-temps.
    app_client.patch(
        f"{WEIGHT}/{entry['id']}",
        json=payload(weight=69.0),
        headers={**auth, "If-Match": stale},
    )

    response = app_client.patch(
        f"{WEIGHT}/{entry['id']}",
        json=payload(weight=70.2),
        headers={**auth, "If-Match": stale},
    )

    assert response.status_code == 409
    assert app_client.get(WEIGHT, headers=auth).json()["entries"][0]["weight_kg"] == 69.0


def test_correcting_preserves_the_origin_of_the_data(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`IMP-05` : corriger une valeur importée d'Apple n'en fait pas une saisie manuelle."""
    dav.seed(WEIGHT_FILE, "date,weight_kg,note,source\n2026-07-20,68.4,,apple\n")
    entry = app_client.get(WEIGHT, headers=auth).json()["entries"][0]

    response = app_client.patch(
        f"{WEIGHT}/{entry['id']}",
        json=payload(weight=68.9),
        headers={**auth, "If-Match": entry["token"]},
    )

    assert response.json()["source"] == "apple"


def test_a_weighing_can_be_deleted(app_client: TestClient, auth: dict[str, str]) -> None:
    entry = post(app_client, auth)

    response = app_client.delete(
        f"{WEIGHT}/{entry['id']}", headers={**auth, "If-Match": entry["token"]}
    )

    assert response.status_code == 204
    assert app_client.get(WEIGHT, headers=auth).json()["total"] == 0


def test_deleting_without_the_token_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    entry = post(app_client, auth)

    assert app_client.delete(f"{WEIGHT}/{entry['id']}", headers=auth).status_code == 409
    assert app_client.get(WEIGHT, headers=auth).json()["total"] == 1


# ── Indicateurs (`BODY-03`, `BODY-04`) ────────────────


def seed_series(dav: FakeWebDav, weights: list[float], start: date = date(2026, 7, 1)) -> None:
    lines = ["date,weight_kg,note,source"]
    for offset, weight in enumerate(weights):
        lines.append(f"{start + timedelta(days=offset)},{weight},,manual")
    dav.seed(WEIGHT_FILE, "\n".join(lines) + "\n")


def test_indicators_describe_the_latest_weighing(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    seed_series(dav, [70.0, 69.5, 69.0])

    stats = app_client.get(WEIGHT, headers=auth).json()["stats"]

    assert stats["latest_kg"] == 69.0
    assert stats["count"] == 3
    assert stats["min_kg"] == 69.0
    assert stats["max_kg"] == 70.0
    assert stats["amplitude_kg"] == 1.0


def test_the_change_spans_the_last_eight_weighings(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`BODY-03` : la fenêtre est de huit pesées, pas de tout l'historique."""
    seed_series(dav, [80.0, 75.0, 74.0, 73.0, 72.0, 71.0, 70.5, 70.0, 69.5, 69.0])

    stats = app_client.get(WEIGHT, headers=auth).json()["stats"]

    # Les huit dernières vont de 74,0 à 69,0 : la pesée à 80 est hors fenêtre.
    assert stats["change_kg"] == -5.0


def test_a_single_weighing_has_no_change_to_announce(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    seed_series(dav, [70.0])

    assert app_client.get(WEIGHT, headers=auth).json()["stats"]["change_kg"] is None


def test_the_gap_to_target_uses_the_configured_setting(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    dav.seed("Metric/settings/settings.csv", "key,value\ntarget_weight_kg,65\n")
    seed_series(dav, [70.0])

    stats = app_client.get(WEIGHT, headers=auth).json()["stats"]

    assert stats["target_kg"] == 65.0
    assert stats["to_target_kg"] == 5.0


def test_without_settings_the_default_target_applies(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """L'application doit être utilisable immédiatement, avant tout réglage."""
    seed_series(dav, [70.0])

    assert app_client.get(WEIGHT, headers=auth).json()["stats"]["target_kg"] == 70.0


def test_an_empty_history_answers_without_failing(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    body = app_client.get(WEIGHT, headers=auth).json()

    assert body["total"] == 0
    assert body["series"] == []
    assert body["stats"]["latest_kg"] is None


# ── Tendance lissée (`BODY-05`) ───────────────────────


def test_the_trend_averages_a_seven_day_calendar_window(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    seed_series(dav, [70.0, 68.0])

    series = app_client.get(WEIGHT, headers=auth).json()["series"]

    assert series[0]["trend_kg"] == 70.0
    assert series[1]["trend_kg"] == 69.0  # moyenne des deux, dans la fenêtre


def test_a_weighing_older_than_the_window_leaves_the_average(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """La fenêtre est calendaire et non un nombre de points : après une pause d'un mois,
    la moyenne ne doit pas encore traîner l'ancienne valeur."""
    dav.seed(
        WEIGHT_FILE,
        "date,weight_kg,note,source\n2026-06-01,80.0,,manual\n2026-07-20,70.0,,manual\n",
    )

    series = app_client.get(WEIGHT, headers=auth).json()["series"]

    assert series[1]["trend_kg"] == 70.0


def test_the_series_is_chronological_even_if_written_out_of_order(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """On peut enregistrer aujourd'hui une pesée d'avant-hier."""
    dav.seed(
        WEIGHT_FILE,
        "date,weight_kg,note,source\n2026-07-20,68.0,,manual\n2026-07-18,69.0,,manual\n",
    )

    series = app_client.get(WEIGHT, headers=auth).json()["series"]

    assert [point["date"] for point in series] == ["2026-07-18", "2026-07-20"]


# ── Historique (`BODY-06`) ────────────────────────────


def test_the_history_reads_from_the_most_recent(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    seed_series(dav, [70.0, 69.0, 68.0])

    entries = app_client.get(WEIGHT, headers=auth).json()["entries"]

    assert [entry["weight_kg"] for entry in entries] == [68.0, 69.0, 70.0]


def test_the_history_is_paginated(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    seed_series(dav, [70.0, 69.0, 68.0, 67.0])

    body = app_client.get(f"{WEIGHT}?limit=2&offset=1", headers=auth).json()

    assert [entry["weight_kg"] for entry in body["entries"]] == [68.0, 69.0]
    assert body["total"] == 4


def test_each_entry_carries_what_is_needed_to_edit_it(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    seed_series(dav, [70.0, 69.0])

    entries = app_client.get(WEIGHT, headers=auth).json()["entries"]

    assert all(isinstance(entry["id"], int) for entry in entries)
    assert len({entry["token"] for entry in entries}) == 2, "un jeton par contenu"


# ── Mensurations (`BODY-07` → `BODY-10`) ──────────────


def test_measurements_accept_a_partial_reading(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """On ne mesure pas tout à chaque fois."""
    response = app_client.post(
        MEASUREMENTS, json={"date": "2026-07-20", "waist_cm": 82.0}, headers=auth
    )

    assert response.status_code == 201
    assert response.json()["waist_cm"] == 82.0
    assert response.json()["arm_cm"] is None


def test_a_reading_without_any_measure_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`BODY-07` : une ligne datée sans valeur ne mesure rien."""
    response = app_client.post(MEASUREMENTS, json={"date": "2026-07-20"}, headers=auth)

    assert response.status_code == 422
    assert "au moins une mesure" in str(response.json()["fields"])


def test_body_fat_is_tracked_as_a_body_measure(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`BODY-10` : la composition corporelle est une mesure du domaine Corps."""
    response = app_client.post(
        MEASUREMENTS, json={"date": "2026-07-20", "body_fat_pct": 14.5}, headers=auth
    )

    assert response.status_code == 201
    assert response.json()["body_fat_pct"] == 14.5


def test_each_measure_has_its_own_previous_reading(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`BODY-08` : « le relevé précédent » d'un tour de bras n'est pas forcément la
    ligne d'avant — chaque mesure a son propre historique."""
    dav.seed(
        "Metric/body/measurements.csv",
        "date,waist_cm,arm_cm,chest_cm,hips_cm,thigh_cm,body_fat_pct,note\n"
        "2026-07-01,84,36,,,,,\n"
        "2026-07-10,83,,,,,,\n"
        "2026-07-20,82,38,,,,,\n",
    )

    indicators = {
        indicator["field"]: indicator
        for indicator in app_client.get(MEASUREMENTS, headers=auth).json()["indicators"]
    }

    assert indicators["waist_cm"]["latest"] == 82.0
    assert indicators["waist_cm"]["delta"] == -1.0  # contre 83, le relevé précédent
    assert indicators["waist_cm"]["direction"] == "down"
    # Le bras n'a pas été mesuré le 10 : son précédent est celui du 1er.
    assert indicators["arm_cm"]["delta"] == 2.0
    assert indicators["arm_cm"]["direction"] == "up"


def test_a_measure_never_taken_is_announced_as_empty(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    indicators = {
        indicator["field"]: indicator
        for indicator in app_client.get(MEASUREMENTS, headers=auth).json()["indicators"]
    }

    assert indicators["thigh_cm"]["latest"] is None
    assert indicators["thigh_cm"]["delta"] is None


def test_measurements_are_editable_like_weighings(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`BODY-09` : même cycle de vie que les pesées."""
    created = app_client.post(
        MEASUREMENTS, json={"date": "2026-07-20", "waist_cm": 82.0}, headers=auth
    ).json()

    updated = app_client.patch(
        f"{MEASUREMENTS}/{created['id']}",
        json={"date": "2026-07-20", "waist_cm": 81.5},
        headers={**auth, "If-Match": created["token"]},
    )
    assert updated.status_code == 200

    removed = app_client.delete(
        f"{MEASUREMENTS}/{created['id']}",
        headers={**auth, "If-Match": updated.json()["token"]},
    )
    assert removed.status_code == 204


# ── Chaîne complète ───────────────────────────────────


def test_the_file_stays_readable_in_a_spreadsheet(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """La promesse du projet : les données restent exploitables sans l'app (`STO-02`)."""
    post(app_client, auth, day="2026-07-20", weight=68.4, note="séance à jeun")
    post(app_client, auth, day="2026-07-21", weight=68.1)

    content = dav.content_of(WEIGHT_FILE)

    assert content == (
        "date,weight_kg,note,source\n"
        "2026-07-20,68.4,séance à jeun,manual\n"
        "2026-07-21,68.1,,manual\n"
    )
    assert dav.files[WEIGHT_FILE].content.startswith(b"\xef\xbb\xbf"), "BOM pour Excel"


async def test_the_trend_is_computed_server_side_only(store: FileStore) -> None:
    """Aucune règle de calcul ne doit être réimplémentable côté client."""
    service = WeightService(store)

    view = await service.view(limit=10, offset=0)

    assert view.series == []
    assert view.stats.count == 0
