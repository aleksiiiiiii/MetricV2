"""Domaine Suppléments (`SUP-01` → `SUP-06`, `HEAT-07`, `HEAT-23`)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.dates import today_local, tz
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

SUPPLEMENTS = "/api/supplements"
SCHEDULE_FILE = "Metric/supplements/schedule.csv"
LOG_FILE = "Metric/supplements/intake_log.csv"
LOG_HEADER = "datetime,schedule_id,name,dose,unit\n"


@pytest.fixture
def app_client(client: TestClient, store: FileStore) -> TestClient:
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


def add(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    body = {"name": "Créatine", "dose": 5, "unit": "g", "time": "08:00", **fields}
    response = client.post(f"{SUPPLEMENTS}/schedule", json=body, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


def moment(day: Any, hour: int = 9) -> str:
    return datetime.combine(day, datetime.min.time(), tzinfo=tz()).replace(hour=hour).isoformat()


# ── Planning (`SUP-01`, `SUP-02`) ─────────────────────


def test_a_supplement_is_added_with_its_entry_date(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`HEAT-07` : ajouter la créatine aujourd'hui ne doit pas rendre rouges les six mois
    précédents. La date d'entrée est ce qui rendra cette règle applicable."""
    supplement = add(app_client, auth)

    assert supplement["created"] == today_local().isoformat()
    assert supplement["schedule_id"]


def test_the_schedule_is_sorted_by_time(app_client: TestClient, auth: dict[str, str]) -> None:
    """Le planning trié par horaire sert de base à la checklist (`SUP-01`)."""
    add(app_client, auth, name="Magnésium", time="21:00")
    add(app_client, auth, name="Créatine", time="08:00")
    add(app_client, auth, name="Whey", time="12:30")

    names = [
        item["name"] for item in app_client.get(f"{SUPPLEMENTS}/schedule", headers=auth).json()
    ]

    assert names == ["Créatine", "Whey", "Magnésium"]


@pytest.mark.parametrize("time", ["25:00", "8:00", "08:60", "matin"])
def test_a_malformed_time_is_refused(
    app_client: TestClient, auth: dict[str, str], time: str
) -> None:
    response = app_client.post(
        f"{SUPPLEMENTS}/schedule",
        json={"name": "X", "dose": 1, "unit": "g", "time": time},
        headers=auth,
    )

    assert response.status_code == 422


def test_removing_a_supplement_keeps_its_intake_history(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`SUP-02` : c'est pourquoi le journal duplique le nom, la dose et l'unité."""
    supplement = add(app_client, auth)
    app_client.post(
        f"{SUPPLEMENTS}/today", json={"schedule_id": supplement["schedule_id"]}, headers=auth
    )

    app_client.delete(
        f"{SUPPLEMENTS}/schedule/{supplement['id']}",
        headers={**auth, "If-Match": supplement["token"]},
    )

    assert app_client.get(f"{SUPPLEMENTS}/schedule", headers=auth).json() == []
    assert "Créatine" in dav.content_of(LOG_FILE)


def test_correcting_a_supplement_keeps_its_identity(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """L'identifiant et la date d'entrée survivent : le journal s'y rattache, et la
    non-rétroactivité ne doit pas se réinitialiser à chaque correction."""
    supplement = add(app_client, auth)

    corrected = app_client.patch(
        f"{SUPPLEMENTS}/schedule/{supplement['id']}",
        json={"name": "Créatine", "dose": 3, "unit": "g", "time": "07:30"},
        headers={**auth, "If-Match": supplement["token"]},
    ).json()

    assert corrected["schedule_id"] == supplement["schedule_id"]
    assert corrected["created"] == supplement["created"]
    assert corrected["dose"] == 3


# ── Cadence (`HEAT-23`, décision D3) ──────────────────


def test_the_cadence_lives_in_the_schedule(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Un seul endroit décrit « je prends de la whey un jour sur deux » : le planning de
    compléments et la heatmap ne pourront pas diverger."""
    supplement = add(app_client, auth, name="Whey", frequency="window:min_count=1;window_days=2")

    assert supplement["cadence_label"] == "un jour sur deux"
    assert "window:min_count=1;window_days=2" in dav.content_of(SCHEDULE_FILE)


def test_an_absent_cadence_means_daily(app_client: TestClient, auth: dict[str, str]) -> None:
    assert add(app_client, auth)["cadence_label"] == "tous les jours"


def test_an_impossible_cadence_is_refused_at_entry(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Mieux vaut le dire à la saisie qu'afficher une piste éternellement rouge."""
    response = app_client.post(
        f"{SUPPLEMENTS}/schedule",
        json={
            "name": "X",
            "dose": 1,
            "unit": "g",
            "time": "08:00",
            "frequency": "window:min_count=3;window_days=2",
        },
        headers=auth,
    )

    assert response.status_code == 422


def test_an_equivalent_cadence_is_stored_identically(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Sinon le journal d'historisation (`HEAT-14`) enregistrerait un changement de
    cadence qui n'en est pas un."""
    first = add(app_client, auth, name="A", frequency="window:window_days=2;min_count=1")
    second = add(app_client, auth, name="B", frequency="window:min_count=1;window_days=2")

    assert first["frequency"] == second["frequency"]


# ── Checklist (`SUP-03`, `SUP-05`, `SUP-06`) ──────────


def test_the_checklist_lists_active_supplements_only(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    add(app_client, auth, name="Créatine")
    add(app_client, auth, name="Ancien", active=False)

    items = app_client.get(f"{SUPPLEMENTS}/today", headers=auth).json()["items"]

    assert [item["name"] for item in items] == ["Créatine"]


def test_checking_writes_a_timestamped_intake(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    supplement = add(app_client, auth)

    view = app_client.post(
        f"{SUPPLEMENTS}/today", json={"schedule_id": supplement["schedule_id"]}, headers=auth
    ).json()

    assert view["items"][0]["taken"] is True
    assert view["items"][0]["taken_at"] is not None
    assert "Créatine,5.0,g" in dav.content_of(LOG_FILE)


def test_checking_twice_writes_one_intake(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Deux clics rapides ne doivent pas produire deux prises."""
    supplement = add(app_client, auth)
    body = {"schedule_id": supplement["schedule_id"]}

    app_client.post(f"{SUPPLEMENTS}/today", json=body, headers=auth)
    app_client.post(f"{SUPPLEMENTS}/today", json=body, headers=auth)

    assert dav.content_of(LOG_FILE).strip().count("Créatine") == 1


def test_unchecking_removes_the_intake_of_the_day(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`SUP-05` : décocher supprime la prise du jour correspondante."""
    supplement = add(app_client, auth)
    app_client.post(
        f"{SUPPLEMENTS}/today", json={"schedule_id": supplement["schedule_id"]}, headers=auth
    )

    view = app_client.delete(
        f"{SUPPLEMENTS}/today/{supplement['schedule_id']}", headers=auth
    ).json()

    assert view["items"][0]["taken"] is False
    assert "Créatine" not in dav.content_of(LOG_FILE)


def test_unchecking_leaves_yesterday_alone(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Décocher aujourd'hui ne doit pas effacer la prise d'hier."""
    supplement = add(app_client, auth)
    yesterday = moment(today_local() - timedelta(days=1))
    dav.seed(LOG_FILE, LOG_HEADER + f"{yesterday},{supplement['schedule_id']},Créatine,5.0,g\n")
    app_client.post(
        f"{SUPPLEMENTS}/today", json={"schedule_id": supplement["schedule_id"]}, headers=auth
    )

    app_client.delete(f"{SUPPLEMENTS}/today/{supplement['schedule_id']}", headers=auth)

    assert dav.content_of(LOG_FILE).count("Créatine") == 1


def test_the_checklist_starts_blank_each_day(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`SUP-03` : l'état repart vierge chaque jour — rien n'est mémorisé, tout est déduit
    du journal."""
    supplement = add(app_client, auth)
    yesterday = moment(today_local() - timedelta(days=1))
    dav.seed(LOG_FILE, LOG_HEADER + f"{yesterday},{supplement['schedule_id']},Créatine,5.0,g\n")

    items = app_client.get(f"{SUPPLEMENTS}/today", headers=auth).json()["items"]

    assert items[0]["taken"] is False


def test_a_late_evening_intake_counts_for_the_displayed_day(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Même règle que l'hydratation : 23 h 30 appartient au jour de l'horloge (`HEAT-32`)."""
    supplement = add(app_client, auth, time="21:00")
    late = moment(today_local(), hour=23)
    dav.seed(LOG_FILE, LOG_HEADER + f"{late},{supplement['schedule_id']},Créatine,5.0,g\n")

    assert app_client.get(f"{SUPPLEMENTS}/today", headers=auth).json()["items"][0]["taken"] is True


# ── Ratio du jour (`SUP-06`) ──────────────────────────


def test_the_day_ratio_counts_taken_over_planned(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Base de la piste d'assiduité des suppléments."""
    first = add(app_client, auth, name="Créatine", time="08:00")
    add(app_client, auth, name="Magnésium", time="21:00")

    view = app_client.post(
        f"{SUPPLEMENTS}/today", json={"schedule_id": first["schedule_id"]}, headers=auth
    ).json()

    assert view["ratio"] == {"taken": 1, "planned": 2, "ratio": 0.5, "complete": False}


def test_a_complete_day_requires_everything(app_client: TestClient, auth: dict[str, str]) -> None:
    """« Journée complète » exige que tout ait été coché, pas la majorité."""
    first = add(app_client, auth, name="Créatine", time="08:00")
    second = add(app_client, auth, name="Magnésium", time="21:00")

    app_client.post(
        f"{SUPPLEMENTS}/today", json={"schedule_id": first["schedule_id"]}, headers=auth
    )
    view = app_client.post(
        f"{SUPPLEMENTS}/today", json={"schedule_id": second["schedule_id"]}, headers=auth
    ).json()

    assert view["ratio"]["complete"] is True


def test_an_empty_schedule_is_not_a_complete_day(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Sans rien de planifié, la journée n'est pas « complète » — elle est vide."""
    ratio = app_client.get(f"{SUPPLEMENTS}/today", headers=auth).json()["ratio"]

    assert ratio == {"taken": 0, "planned": 0, "ratio": 0.0, "complete": False}


# ── Série par item ────────────────────────────────────


def test_the_streak_counts_consecutive_days(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    supplement = add(app_client, auth)
    today = today_local()
    lines = [
        f"{moment(today - timedelta(days=offset))},{supplement['schedule_id']},Créatine,5.0,g"
        for offset in range(1, 6)
    ]
    dav.seed(LOG_FILE, LOG_HEADER + "\n".join(lines) + "\n")

    items = app_client.get(f"{SUPPLEMENTS}/today", headers=auth).json()["items"]

    # Cinq jours jusqu'à hier : la journée en cours ne casse pas encore la série.
    assert items[0]["streak"] == 5


def test_today_extends_the_streak_once_taken(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    supplement = add(app_client, auth)
    yesterday = moment(today_local() - timedelta(days=1))
    dav.seed(LOG_FILE, LOG_HEADER + f"{yesterday},{supplement['schedule_id']},Créatine,5.0,g\n")

    view = app_client.post(
        f"{SUPPLEMENTS}/today", json={"schedule_id": supplement["schedule_id"]}, headers=auth
    ).json()

    assert view["items"][0]["streak"] == 2


def test_a_gap_breaks_the_streak(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    supplement = add(app_client, auth)
    today = today_local()
    dav.seed(
        LOG_FILE,
        LOG_HEADER
        + f"{moment(today - timedelta(days=1))},{supplement['schedule_id']},Créatine,5.0,g\n"
        + f"{moment(today - timedelta(days=3))},{supplement['schedule_id']},Créatine,5.0,g\n",
    )

    assert app_client.get(f"{SUPPLEMENTS}/today", headers=auth).json()["items"][0]["streak"] == 1


def test_checking_an_unknown_supplement_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    response = app_client.post(
        f"{SUPPLEMENTS}/today", json={"schedule_id": "inexistant"}, headers=auth
    )

    assert response.status_code == 404


# ── Lignes partielles (`STO-04`) ──────────────────────


def test_a_schedule_row_without_a_time_stays_readable(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Trouvé en production, sur le fichier réel.

    Une cellule `time` vide rendait **tout** le fichier illisible, et avec lui la
    checklist, l'écran Routine et le tableau de bord — qui lit le planning pour son ratio
    du jour. Un `502 storage_schema_error` pour un horaire manquant.

    C'était aussi une violation de `STO-04` : la promesse « ajouter une colonne
    n'invalide aucune ligne ancienne » ne tient pas si la colonne ajoutée est obligatoire.
    """
    dav.seed(
        SCHEDULE_FILE,
        "id,name,dose,unit,time,frequency,active,created\ns1,Créatine,5,g,,daily,true,\n",
    )

    response = app_client.get("/api/supplements/schedule", headers=auth)

    assert response.status_code == 200, response.text
    assert response.json()[0]["time"] == ""


def test_a_barely_filled_schedule_row_does_not_break_the_file(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Aucune colonne du planning n'est obligatoire : le fichier s'ouvre dans un tableur,
    et une ligne en chantier y est une possibilité normale."""
    dav.seed(SCHEDULE_FILE, "id,name,dose,unit,time,frequency,active,created\ns1,,,,,,,\n")

    body = app_client.get("/api/supplements/schedule", headers=auth).json()

    assert len(body) == 1
    assert body[0]["dose"] == 0
    assert body[0]["cadence_label"] == "tous les jours", "repli de cadence"


def test_a_schedule_row_without_an_identifier_is_skipped(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le cochage et le journal des prises s'y rattachent : afficher une telle ligne
    produirait une case à cocher qui ne mène nulle part. Elle survit dans le fichier."""
    dav.seed(
        SCHEDULE_FILE,
        "id,name,dose,unit,time,frequency,active,created\n"
        ",Orpheline,5,g,08:00,daily,true,\n"
        "s2,Whey,30,g,12:30,daily,true,\n",
    )

    body = app_client.get("/api/supplements/schedule", headers=auth).json()

    assert [item["name"] for item in body] == ["Whey"]
    assert "Orpheline" in dav.content_of(SCHEDULE_FILE)


def test_the_dashboard_survives_a_partial_schedule(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """La régression telle qu'elle s'est manifestée : l'écran d'accueil tombait en
    entier à cause d'une cellule vide dans un fichier de planning."""
    dav.seed(
        SCHEDULE_FILE,
        "id,name,dose,unit,time,frequency,active,created\ns1,Créatine,5,g,,daily,true,\n",
    )

    response = app_client.get("/api/aggregates/dashboard", headers=auth)

    assert response.status_code == 200, response.text
    assert response.json()["supplements"]["planned"] == 1
