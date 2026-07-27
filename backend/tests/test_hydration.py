"""Domaine Hydratation (`HYD-01` → `HYD-05`).

Le test qui compte le plus est celui de la frontière de jour : une prise à 23 h 30
appartient au jour qu'affiche l'horloge, pas au lendemain (`HEAT-32`).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.dates import today_local, tz
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

HYDRATION = "/api/hydration"
FILE = "Metric/hydration/intake_log.csv"
HEADER = "datetime,volume_ml,kind\n"


@pytest.fixture
def app_client(client: TestClient, store: FileStore) -> TestClient:
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


def drink(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    response = client.post(HYDRATION, json={"volume_ml": 500, **fields}, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


# ── Saisie (`HYD-01`, `HYD-02`) ───────────────────────


def test_an_intake_is_written_with_its_offset(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """L'horodatage porte son décalage : sans lui, la ligne changerait de journée selon
    le fuseau de lecture."""
    drink(app_client, auth, volume_ml=500, kind="eau")

    line = dav.content_of(FILE).splitlines()[1]

    assert line.endswith(",500,eau")
    assert "+0" in line or "+1" in line, line


def test_the_kind_stays_optional(app_client: TestClient, auth: dict[str, str]) -> None:
    """Exiger le type ajouterait un geste à une saisie qui doit en tenir en un seul."""
    intake = drink(app_client, auth, volume_ml=250)

    assert intake["kind"] is None


@pytest.mark.parametrize("volume", [0, -100, 5001])
def test_an_implausible_volume_is_refused(
    app_client: TestClient, auth: dict[str, str], volume: int
) -> None:
    response = app_client.post(HYDRATION, json={"volume_ml": volume}, headers=auth)

    assert response.status_code == 422


def test_the_presets_come_from_the_settings(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`HYD-02` : raccourcis paramétrables.

    La valeur contient des virgules dans un fichier qui les utilise comme séparateur :
    elle doit donc être protégée par des guillemets. C'est ce que produisent notre
    écrivain CSV comme n'importe quel tableur — mais une ligne ajoutée à la main sans
    guillemets serait tronquée, silencieusement.
    """
    dav.seed(
        "Metric/settings/settings.csv",
        'key,value\nhydration_presets_ml,"200,400,800"\n',
    )

    presets = app_client.get(HYDRATION, headers=auth).json()["presets_ml"]

    assert presets == [200, 400, 800]


async def test_a_comma_bearing_setting_survives_our_own_writer(store: FileStore) -> None:
    """La garantie qui compte : ce que l'application écrit, elle sait le relire."""
    from app.domains.app_settings.service import SettingRow, SettingsService
    from app.storage.csv_repo import CsvRepository
    from app.storage.paths import SETTINGS

    repo: CsvRepository[SettingRow] = CsvRepository(store, SETTINGS, SettingRow)
    await repo.append(SettingRow(key="hydration_presets_ml", value="200,400,800"))

    assert (await SettingsService(store).all())["hydration_presets_ml"] == "200,400,800"


def test_a_bogus_preset_setting_falls_back(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Un réglage saisi à la main dans un tableur ne doit pas casser l'écran."""
    dav.seed("Metric/settings/settings.csv", "key,value\nhydration_presets_ml,abc;;-5\n")

    assert app_client.get(HYDRATION, headers=auth).json()["presets_ml"] == [250, 500, 750]


# ── Frontière de jour (`HEAT-32`) ─────────────────────


def test_an_intake_at_half_past_eleven_belongs_to_the_displayed_day(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le test central du lot.

    23 h 30 à Paris, c'est 21 h 30 UTC le même jour en été — mais en hiver, ou pour un
    fuseau négatif, un découpage en UTC ferait basculer la prise d'un jour. On vérifie
    que la journée affichée est celle de l'horloge.
    """
    today = today_local()
    late = datetime.combine(today, datetime.min.time(), tzinfo=tz()).replace(hour=23, minute=30)
    dav.seed(FILE, HEADER + f"{late.isoformat()},700,eau\n")

    body = app_client.get(HYDRATION, headers=auth).json()

    assert body["stats"]["today_ml"] == 700
    assert body["series"][-1]["date"] == today.isoformat()
    assert body["series"][-1]["volume_ml"] == 700


def test_an_intake_just_after_midnight_belongs_to_the_new_day(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le symétrique : 0 h 30 appartient au jour qui commence, pas à celui qui finit."""
    today = today_local()
    yesterday = today - timedelta(days=1)
    early = datetime.combine(today, datetime.min.time(), tzinfo=tz()).replace(minute=30)
    dav.seed(FILE, HEADER + f"{early.isoformat()},300,eau\n")

    series = {
        day["date"]: day["volume_ml"]
        for day in app_client.get(HYDRATION, headers=auth).json()["series"]
    }

    assert series[today.isoformat()] == 300
    assert series[yesterday.isoformat()] == 0


def test_a_timestamp_without_offset_is_read_as_local(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Cas d'une ligne saisie à la main dans un tableur : la supposer UTC décalerait
    silencieusement la journée."""
    today = today_local()
    dav.seed(FILE, HEADER + f"{today}T23:30:00,600,eau\n")

    assert app_client.get(HYDRATION, headers=auth).json()["stats"]["today_ml"] == 600


# ── Total, objectif et ratio (`HYD-03`) ───────────────


def test_the_daily_total_is_compared_to_the_target(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    dav.seed("Metric/settings/settings.csv", "key,value\ntarget_hydration_ml,2000\n")
    drink(app_client, auth, volume_ml=500)
    drink(app_client, auth, volume_ml=750)

    stats = app_client.get(HYDRATION, headers=auth).json()["stats"]

    assert stats["today_ml"] == 1250
    assert stats["target_ml"] == 2000
    assert stats["ratio"] == pytest.approx(0.625)


def test_the_ratio_is_capped_but_the_total_is_not(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Dépasser l'objectif ne doit pas produire un anneau à 150 % — mais le volume réel
    reste lisible."""
    for _ in range(6):
        drink(app_client, auth, volume_ml=500)

    stats = app_client.get(HYDRATION, headers=auth).json()["stats"]

    assert stats["today_ml"] == 3000
    assert stats["ratio"] == 1.0


def test_the_default_target_applies_without_settings(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    assert app_client.get(HYDRATION, headers=auth).json()["stats"]["target_ml"] == 2000


# ── Série et moyennes (`HYD-05`) ──────────────────────


def test_the_series_returns_a_complete_range(app_client: TestClient, auth: dict[str, str]) -> None:
    """Les jours sans prise valent zéro et sont retournés : le client n'a aucun trou à
    combler, comme l'exige `HEAT-24` pour les grilles."""
    body = app_client.get(f"{HYDRATION}?days=10", headers=auth).json()

    assert len(body["series"]) == 10
    assert all(day["volume_ml"] == 0 for day in body["series"])


def test_the_averages_cover_seven_and_thirty_days(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    today = today_local()
    lines = [
        f"{datetime.combine(today - timedelta(days=offset), datetime.min.time(), tzinfo=tz()).replace(hour=9).isoformat()},"
        f"{2100 if offset < 7 else 700},eau"
        for offset in range(30)
    ]
    dav.seed(FILE, HEADER + "\n".join(lines) + "\n")

    stats = app_client.get(HYDRATION, headers=auth).json()["stats"]

    assert stats["average_7d_ml"] == 2100
    assert stats["average_30d_ml"] == pytest.approx(1026, abs=2)


def test_days_reaching_the_target_are_counted(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    today = today_local()
    lines = [
        f"{datetime.combine(today - timedelta(days=offset), datetime.min.time(), tzinfo=tz()).replace(hour=9).isoformat()},"
        f"{2500 if offset % 2 == 0 else 500},eau"
        for offset in range(10)
    ]
    dav.seed(FILE, HEADER + "\n".join(lines) + "\n")

    stats = app_client.get(f"{HYDRATION}?days=10", headers=auth).json()["stats"]

    assert stats["days_reached"] == 5
    assert stats["days_counted"] == 10


def test_an_empty_history_answers_without_failing(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    stats = app_client.get(HYDRATION, headers=auth).json()["stats"]

    assert stats["today_ml"] == 0
    assert stats["average_7d_ml"] == 0
    assert stats["days_reached"] == 0


# ── Correction (`HYD-04`) ─────────────────────────────


def test_an_intake_of_the_day_can_be_removed(app_client: TestClient, auth: dict[str, str]) -> None:
    drink(app_client, auth, volume_ml=500)
    entry = app_client.get(HYDRATION, headers=auth).json()["today"][0]

    response = app_client.delete(
        f"{HYDRATION}/{entry['id']}", headers={**auth, "If-Match": entry["token"]}
    )

    assert response.status_code == 204
    assert app_client.get(HYDRATION, headers=auth).json()["stats"]["today_ml"] == 0


def test_removing_without_the_token_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    drink(app_client, auth, volume_ml=500)
    entry = app_client.get(HYDRATION, headers=auth).json()["today"][0]

    assert app_client.delete(f"{HYDRATION}/{entry['id']}", headers=auth).status_code == 409
    assert app_client.get(HYDRATION, headers=auth).json()["stats"]["today_ml"] == 500


def test_only_the_intakes_of_the_day_are_offered_for_correction(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    today = today_local()
    yesterday = datetime.combine(today - timedelta(days=1), datetime.min.time(), tzinfo=tz())
    dav.seed(FILE, HEADER + f"{yesterday.isoformat()},400,eau\n")
    drink(app_client, auth, volume_ml=500)

    today_entries = app_client.get(HYDRATION, headers=auth).json()["today"]

    assert len(today_entries) == 1
    assert today_entries[0]["volume_ml"] == 500
