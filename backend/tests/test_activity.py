"""Domaine Activité (`ACT-01` → `ACT-18`).

Le plus gros domaine du backlog. Les familles de tests suivent `docs/patron-domaine.md`,
plus ce qui lui est propre : normalisation des formats, semaines ISO, purge en cascade.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.dates import week_start
from app.core.validation import today_local
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

ACTIVITY = "/api/activity"
RUNS_FILE = "Metric/activity/runs.csv"
SESSIONS_FILE = "Metric/activity/circuit_sessions.csv"
EXERCISES_FILE = "Metric/activity/exercises.csv"
LOG_FILE = "Metric/activity/exercise_log.csv"
#: Les séries des séances tabata. Les groupes négligés y sont lus depuis le
#: rebranchement du coach — même règle (`ACT-16`), autre source.
SESSION_SETS_FILE = "Metric/activity/circuit_session_sets.csv"


@pytest.fixture
def app_client(client: TestClient, store: FileStore) -> TestClient:
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


def create_run(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    body = {"date": "2026-07-20", "distance_km": "8,40", "duration_min": "44:12", **fields}
    response = client.post(f"{ACTIVITY}/runs", json=body, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


def create_workout(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    body = {"date": "2026-07-20", "type": "musculation", "duration_min": "1h15", **fields}
    response = client.post(f"{ACTIVITY}/workouts", json=body, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


def create_exercise(client: TestClient, auth: dict[str, str], name: str, group: str) -> Any:
    response = client.post(
        f"{ACTIVITY}/exercises", json={"name": name, "muscle_group": group}, headers=auth
    )
    assert response.status_code == 201, response.text
    return response.json()


# ── Courses : formats souples (`ACT-01`, `ACT-02`) ────


def test_a_run_accepts_the_formats_actually_typed(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Virgule décimale et durée en `mm:ss`, comme sur un chronomètre."""
    run = create_run(app_client, auth, distance_km="8,40", duration_min="44:12")

    assert run["distance_km"] == pytest.approx(8.4)
    assert run["duration_min"] == pytest.approx(44.2)


def test_the_pace_is_derived_and_stored(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`ACT-02` : l'allure est stockée avec la course pour que le fichier se lise seul."""
    run = create_run(app_client, auth)

    assert run["pace_min_km"] == pytest.approx(5.2619, abs=1e-3)
    assert run["speed_kmh"] == pytest.approx(11.4, abs=0.05)
    assert "pace_min_km" in dav.content_of(RUNS_FILE).splitlines()[0]


def test_a_long_run_is_read_as_hours_minutes_seconds(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    run = create_run(app_client, auth, distance_km="14,2", duration_min="1:18:44")

    assert run["duration_min"] == pytest.approx(78.733, abs=1e-2)


def test_miles_are_converted_at_entry(app_client: TestClient, auth: dict[str, str]) -> None:
    run = create_run(app_client, auth, distance_km="5mi")

    assert run["distance_km"] == pytest.approx(8.047, abs=1e-3)


def test_an_unintelligible_duration_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    response = app_client.post(
        f"{ACTIVITY}/runs",
        json={"date": "2026-07-20", "distance_km": 8.4, "duration_min": "n'importe quoi"},
        headers=auth,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_a_run_detail_is_a_resource_of_its_own(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`ACT-05` : distance, temps, allure, vitesse, FC, dénivelé, note."""
    created = create_run(app_client, auth, avg_hr=152, elevation_m=120, note="vent de face")

    detail = app_client.get(f"{ACTIVITY}/runs/{created['id']}", headers=auth).json()

    assert detail["avg_hr"] == 152
    assert detail["elevation_m"] == 120
    assert detail["note"] == "vent de face"
    assert detail["speed_kmh"] is not None


def test_an_implausible_heart_rate_is_refused(app_client: TestClient, auth: dict[str, str]) -> None:
    response = app_client.post(
        f"{ACTIVITY}/runs",
        json={"date": "2026-07-20", "distance_km": 8.4, "duration_min": 44, "avg_hr": 400},
        headers=auth,
    )

    assert response.status_code == 422


# ── Agrégats hebdomadaires (`ACT-10` → `ACT-14`) ──────


def seed_week(dav: FakeWebDav, today: date) -> date:
    """Une semaine réaliste : deux courses et une séance."""
    monday = week_start(today)
    dav.seed(
        RUNS_FILE,
        "date,distance_km,duration_min,pace_min_km,avg_hr,elevation_m,note,source\n"
        f"{monday},8.4,44.2,5.262,,,,manual\n"
        f"{monday + timedelta(days=2)},6.1,32.67,5.356,,,,manual\n",
    )
    # Une séance d'entraînement est un **circuit déclaré fait** depuis la phase 5 : la
    # musculation manuelle n'existe plus, et c'est `circuit_sessions.csv` que l'écran lit.
    dav.seed(
        SESSIONS_FILE,
        "session_id,circuit_id,date,name,rounds,duration_min,rpe,source\n"
        f"s1,c1,{monday + timedelta(days=1)},Haut du corps,4,75,8,cadence\n",
    )
    return monday


def test_the_week_totals_reset_on_monday(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`ACT-11` : la semaine ISO commence le lundi."""
    monday = seed_week(dav, today_local())
    # Une séance de la semaine précédente ne doit pas compter.
    dav.seed(
        SESSIONS_FILE,
        dav.content_of(SESSIONS_FILE)
        + f"s0,c1,{monday - timedelta(days=3)},Gainage,2,60,,cadence\n",
    )

    week = app_client.get(ACTIVITY, headers=auth).json()["week"]

    assert week["week_start"] == monday.isoformat()
    assert week["sessions"] == 3
    assert week["minutes"] == pytest.approx(151.87, abs=0.1)
    assert week["distance_km"] == pytest.approx(14.5)


def test_the_average_pace_covers_running_only(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Mélanger une heure de yoga aux kilomètres n'aurait aucun sens."""
    seed_week(dav, today_local())

    week = app_client.get(ACTIVITY, headers=auth).json()["week"]

    assert week["pace_min_km"] == pytest.approx(5.3, abs=0.05)


def test_rest_days_are_distinguished_from_zero(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`ACT-10` : un jour de repos est un choix, pas un trou de données."""
    seed_week(dav, today_local())

    days = app_client.get(ACTIVITY, headers=auth).json()["days"]

    assert len(days) == 7
    assert [day["weekday"] for day in days] == [1, 2, 3, 4, 5, 6, 7]
    assert days[0]["rest"] is False
    assert days[3]["rest"] is True


def test_eight_weeks_of_history_are_returned_oldest_first(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    seed_week(dav, today_local())

    weeks = app_client.get(ACTIVITY, headers=auth).json()["weeks"]

    assert len(weeks) == 8
    assert weeks[0]["week_start"] < weeks[-1]["week_start"]
    assert weeks[-1]["sessions"] == 3


# ── Groupes négligés (`ACT-16`) ───────────────────────


def test_a_group_never_worked_is_none_not_a_huge_number(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """« Jamais » et « il y a très longtemps » ne se traitent pas pareil, et une valeur
    inventée fausserait la génération IA de planning."""
    today = today_local()
    dav.seed(
        SESSION_SETS_FILE,
        "session_id,date,exercise_name,muscle_group,sets,reps\n"
        f"s1,{today - timedelta(days=5)},Développé,pectoraux,3,8\n",
    )

    neglected = {
        item["muscle_group"]: item
        for item in app_client.get(ACTIVITY, headers=auth).json()["neglected"]
    }

    assert neglected["pectoraux"]["days_since"] == 5
    assert neglected["dos"]["days_since"] is None
    assert "autre" not in neglected, "« autre » n'est pas un groupe à solliciter"


def test_the_most_neglected_comes_first(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    today = today_local()
    dav.seed(
        SESSION_SETS_FILE,
        "session_id,date,exercise_name,muscle_group,sets,reps\n"
        f"s1,{today - timedelta(days=2)},Développé,pectoraux,3,8\n"
        f"s2,{today - timedelta(days=20)},Squat,jambes,5,5\n",
    )

    neglected = app_client.get(ACTIVITY, headers=auth).json()["neglected"]
    worked = [item for item in neglected if item["days_since"] is not None]

    assert neglected[0]["days_since"] is None, "jamais travaillé passe devant"
    assert worked[0]["muscle_group"] == "jambes"
    assert worked[-1]["muscle_group"] == "pectoraux"


# ── Historique fusionné (`ACT-13`) ────────────────────


def test_runs_and_workouts_share_one_history(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    seed_week(dav, today_local())

    history = app_client.get(ACTIVITY, headers=auth).json()["history"]

    assert {item["kind"] for item in history} == {"run", "workout"}
    dates = [item["date"] for item in history]
    assert dates == sorted(dates, reverse=True), "du plus récent au plus ancien"


# ── Progression et records (`ACT-09`, `ACT-15`) ───────


def test_the_overview_dates_itself_from_the_server(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Le jour vient du serveur, jamais de l'horloge du téléphone."""
    assert app_client.get(ACTIVITY, headers=auth).json()["today"] == today_local().isoformat()


def test_an_empty_domain_answers_without_failing(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    body = app_client.get(ACTIVITY, headers=auth).json()

    assert body["total"] == 0
    assert body["week"]["sessions"] == 0
    assert len(body["days"]) == 7


# ── Chaîne complète ───────────────────────────────────


def test_the_run_file_stays_readable_in_a_spreadsheet(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    create_run(app_client, auth, note="jambes lourdes")

    lines = dav.content_of(RUNS_FILE).splitlines()

    assert lines[0] == (
        "date,distance_km,duration_min,pace_min_km,avg_hr,elevation_m,cadence_spm,"
        # Les colonnes des lots C08 et C09 s'ajoutent **en fin d'en-tête**, ce qui est la
        # condition pour que `STO-04` remappe les lignes d'avant sans migration.
        "note,source,run_id,total_calories,active_calories,start_time,end_time,"
        "split_length_km"
    )
    assert lines[1].startswith("2026-07-20,8.4,44.2,5.262")
    # Une saisie au clavier ne porte ni identifiant stable, ni paliers, ni bornes
    # horaires : cinq cellules vides, qui sont une valeur légitime et non un trou.
    assert lines[1].endswith("jambes lourdes,manual,,,,,,")


# ── Allure, distance et cadence (C06) ─────────────────

# Distance et allure sont deux lectures du même trajet, liées par la durée. Le serveur en
# calcule toujours une depuis l'autre : c'est « aucun calcul métier côté client » appliqué
# au seul cas du domaine où le client aurait été tenté de le faire.


def test_a_distance_still_yields_its_pace(app_client: TestClient, auth: dict[str, str]) -> None:
    """Le cas historique, inchangé : on saisit une distance, l'allure en découle."""
    body = app_client.post(
        "/api/activity/runs",
        json={"date": "2026-07-20", "distance_km": "8,40", "duration_min": "44:12"},
        headers=auth,
    ).json()

    assert body["distance_km"] == 8.4
    assert body["pace_min_km"] == 5.262


def test_a_pace_alone_yields_its_distance(app_client: TestClient, auth: dict[str, str]) -> None:
    """Le cas nouveau : la capture donne une allure, pas toujours une distance."""
    body = app_client.post(
        "/api/activity/runs",
        json={"date": "2026-07-20", "pace_min_km": "5:00", "duration_min": "45"},
        headers=auth,
    ).json()

    assert body["pace_min_km"] == 5
    assert body["distance_km"] == 9


def test_a_corrected_pace_wins_over_the_distance(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Les deux ensemble : l'allure fait foi, la distance est recalculée.

    C'est le cas d'une correction — les trois nombres à l'écran deviennent incohérents
    entre eux, et il faut dire lequel on défend. C'est celui qu'on vient de toucher.
    """
    body = app_client.post(
        "/api/activity/runs",
        json={
            "date": "2026-07-20",
            "distance_km": "8,40",
            "pace_min_km": "5:00",
            "duration_min": "45",
        },
        headers=auth,
    ).json()

    assert body["pace_min_km"] == 5
    # 45 min à 5:00/km font 9 km, et non les 8,4 envoyés.
    assert body["distance_km"] == 9


def test_a_run_without_distance_nor_pace_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Une durée seule n'est pas une course incomplète : c'est une saisie illisible."""
    response = app_client.post(
        "/api/activity/runs",
        json={"date": "2026-07-20", "duration_min": "45"},
        headers=auth,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_a_pace_is_read_like_a_duration(app_client: TestClient, auth: dict[str, str]) -> None:
    """`5:16` vaut 5 min 16 s par kilomètre — la même grammaire qu'une durée.

    Un second analyseur pour la même écriture divergerait du premier au cas limite.
    """
    body = app_client.post(
        "/api/activity/runs",
        json={"date": "2026-07-20", "pace_min_km": "5:16", "duration_min": "44:12"},
        headers=auth,
    ).json()

    assert body["pace_min_km"] == 5.267


def test_the_cadence_is_stored_and_returned(app_client: TestClient, auth: dict[str, str]) -> None:
    """Rien ne la déduit : une cadence ne se calcule pas depuis une allure."""
    created = app_client.post(
        "/api/activity/runs",
        json={
            "date": "2026-07-20",
            "distance_km": "8,40",
            "duration_min": "44:12",
            "cadence_spm": "172",
        },
        headers=auth,
    ).json()

    assert created["cadence_spm"] == 172
    assert app_client.get("/api/activity/runs/0", headers=auth).json()["cadence_spm"] == 172


def test_a_run_without_cadence_keeps_an_empty_cell(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`STO-04` : une colonne ajoutée ne casse ni les lignes d'avant ni celles d'après."""
    create_run(app_client, auth)

    assert app_client.get("/api/activity/runs/0", headers=auth).json()["cadence_spm"] is None
    assert ",," in dav.content_of(RUNS_FILE).splitlines()[1]


def test_an_absurd_cadence_is_refused(app_client: TestClient, auth: dict[str, str]) -> None:
    response = app_client.post(
        "/api/activity/runs",
        json={
            "date": "2026-07-20",
            "distance_km": "8,40",
            "duration_min": "44:12",
            "cadence_spm": "9000",
        },
        headers=auth,
    )

    assert response.status_code == 422
