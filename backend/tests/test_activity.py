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
WORKOUTS_FILE = "Metric/activity/workouts.csv"
LOG_FILE = "Metric/activity/exercise_log.csv"


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


# ── Séances (`ACT-03`, `ACT-04`, `ACT-18`) ────────────


def test_a_workout_gets_a_stable_identifier(app_client: TestClient, auth: dict[str, str]) -> None:
    """`ACT-03` : les exercices s'y rattachent, une position de ligne ne suffirait pas."""
    workout = create_workout(app_client, auth)

    assert workout["workout_id"]
    assert workout["workout_id"] != str(workout["id"])


def test_the_identifier_survives_a_correction(app_client: TestClient, auth: dict[str, str]) -> None:
    workout = create_workout(app_client, auth)

    corrected = app_client.patch(
        f"{ACTIVITY}/workouts/{workout['id']}",
        json={"date": "2026-07-20", "type": "musculation", "duration_min": "1h30"},
        headers={**auth, "If-Match": workout["token"]},
    ).json()

    assert corrected["workout_id"] == workout["workout_id"]


def test_the_perceived_effort_is_recorded(app_client: TestClient, auth: dict[str, str]) -> None:
    """`ACT-18` : signal de charge et de fatigue transmis à l'IA."""
    workout = create_workout(app_client, auth, rpe=8)

    assert workout["rpe"] == 8


@pytest.mark.parametrize("rpe", [0, 11, -3])
def test_an_effort_outside_the_scale_is_refused(
    app_client: TestClient, auth: dict[str, str], rpe: int
) -> None:
    response = app_client.post(
        f"{ACTIVITY}/workouts",
        json={"date": "2026-07-20", "type": "musculation", "duration_min": 60, "rpe": rpe},
        headers=auth,
    )

    assert response.status_code == 422


def test_the_workout_type_stays_free(app_client: TestClient, auth: dict[str, str]) -> None:
    """Les sept types sont des suggestions : on ne va pas interdire « escalade »."""
    workout = create_workout(app_client, auth, type="escalade")

    assert workout["type"] == "escalade"
    assert "musculation" in app_client.get(f"{ACTIVITY}/types", headers=auth).json()


def test_deleting_a_workout_purges_its_exercises(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`ACT-04` : sans cela, le journal garderait des performances orphelines."""
    workout = create_workout(app_client, auth)
    exercise = create_exercise(app_client, auth, "Développé couché", "pectoraux")
    app_client.post(
        f"{ACTIVITY}/workouts/{workout['id']}/exercises",
        json={"exercise_id": exercise["exercise_id"], "weight_kg": 80, "sets": 3, "reps": 8},
        headers=auth,
    )
    assert "Développé couché" in dav.content_of(LOG_FILE)

    app_client.delete(
        f"{ACTIVITY}/workouts/{workout['id']}", headers={**auth, "If-Match": workout["token"]}
    )

    assert "Développé couché" not in dav.content_of(LOG_FILE)


def test_a_refused_deletion_leaves_the_exercises_alone(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """L'ordre compte : purger d'abord laisserait des orphelins si la garde refuse."""
    workout = create_workout(app_client, auth)
    exercise = create_exercise(app_client, auth, "Squat", "jambes")
    app_client.post(
        f"{ACTIVITY}/workouts/{workout['id']}/exercises",
        json={"exercise_id": exercise["exercise_id"], "weight_kg": 100, "sets": 5, "reps": 5},
        headers=auth,
    )

    refused = app_client.delete(f"{ACTIVITY}/workouts/{workout['id']}", headers=auth)

    assert refused.status_code == 409
    assert "Squat" in dav.content_of(LOG_FILE)


# ── Catalogue et journal (`ACT-06` → `ACT-08`) ────────


def test_an_unknown_muscle_group_is_refused(app_client: TestClient, auth: dict[str, str]) -> None:
    response = app_client.post(
        f"{ACTIVITY}/exercises", json={"name": "Tirage", "muscle_group": "avant-bras"}, headers=auth
    )

    assert response.status_code == 422


def test_the_taxonomy_has_its_nine_values(app_client: TestClient, auth: dict[str, str]) -> None:
    """`ACT-06` : neuf valeurs, et le regroupement en pistes est un réglage posé
    par-dessus, pas une contrainte sur cette liste."""
    groups = app_client.get(f"{ACTIVITY}/muscle-groups", headers=auth).json()

    assert len(groups) == 9
    assert "autre" in groups


def test_removing_an_exercise_keeps_the_history(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`ACT-06` : c'est pourquoi le journal duplique le nom et le groupe."""
    workout = create_workout(app_client, auth)
    exercise = create_exercise(app_client, auth, "Rowing", "dos")
    app_client.post(
        f"{ACTIVITY}/workouts/{workout['id']}/exercises",
        json={"exercise_id": exercise["exercise_id"], "weight_kg": 60, "sets": 4, "reps": 10},
        headers=auth,
    )

    app_client.delete(
        f"{ACTIVITY}/exercises/{exercise['id']}", headers={**auth, "If-Match": exercise["token"]}
    )

    assert app_client.get(f"{ACTIVITY}/exercises", headers=auth).json() == []
    assert "Rowing" in dav.content_of(LOG_FILE)
    assert "dos" in dav.content_of(LOG_FILE)


def test_bodyweight_is_a_legitimate_load(app_client: TestClient, auth: dict[str, str]) -> None:
    """`ACT-07` : charge 0 = poids du corps, pas une donnée manquante."""
    workout = create_workout(app_client, auth)
    exercise = create_exercise(app_client, auth, "Traction", "dos")

    entry = app_client.post(
        f"{ACTIVITY}/workouts/{workout['id']}/exercises",
        json={"exercise_id": exercise["exercise_id"], "weight_kg": 0, "sets": 4, "reps": 8},
        headers=auth,
    ).json()

    assert entry["weight_kg"] == 0
    assert entry["volume_kg"] == 0
    assert entry["one_rep_max_kg"] is None


def test_the_catalogue_recalls_the_last_performance(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`ACT-08` : choisir sa charge sans consulter l'historique."""
    workout = create_workout(app_client, auth)
    exercise = create_exercise(app_client, auth, "Développé couché", "pectoraux")
    app_client.post(
        f"{ACTIVITY}/workouts/{workout['id']}/exercises",
        json={"exercise_id": exercise["exercise_id"], "weight_kg": 82.5, "sets": 3, "reps": 8},
        headers=auth,
    )

    catalogue = app_client.get(f"{ACTIVITY}/exercises", headers=auth).json()

    assert catalogue[0]["last_weight_kg"] == 82.5
    assert catalogue[0]["last_reps"] == 8
    assert catalogue[0]["last_date"] == "2026-07-20"


def test_logging_an_unknown_exercise_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    workout = create_workout(app_client, auth)

    response = app_client.post(
        f"{ACTIVITY}/workouts/{workout['id']}/exercises",
        json={"exercise_id": "inexistant", "weight_kg": 60, "sets": 3, "reps": 10},
        headers=auth,
    )

    assert response.status_code == 404


# ── Duplication (`ACT-17`) ────────────────────────────


def test_duplicating_a_workout_brings_its_exercises(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Saisir une répétition de routine devient une action au lieu d'une dizaine."""
    workout = create_workout(app_client, auth)
    exercise = create_exercise(app_client, auth, "Squat", "jambes")
    app_client.post(
        f"{ACTIVITY}/workouts/{workout['id']}/exercises",
        json={"exercise_id": exercise["exercise_id"], "weight_kg": 100, "sets": 5, "reps": 5},
        headers=auth,
    )

    copy = app_client.post(
        f"{ACTIVITY}/workouts/{workout['id']}/duplicate",
        json={"date": today_local().isoformat()},
        headers=auth,
    ).json()

    assert copy["workout_id"] != workout["workout_id"]
    assert len(copy["exercises"]) == 1
    assert copy["exercises"][0]["weight_kg"] == 100
    assert copy["volume_kg"] == 2500


def test_a_duplicate_does_not_inherit_the_perceived_effort(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """L'effort perçu appartient à la séance vécue, pas au modèle."""
    workout = create_workout(app_client, auth, rpe=9)

    copy = app_client.post(
        f"{ACTIVITY}/workouts/{workout['id']}/duplicate", json={}, headers=auth
    ).json()

    assert copy["rpe"] is None


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
    dav.seed(
        WORKOUTS_FILE,
        "date,type,duration_min,calories,rpe,note,source,id\n"
        f"{monday + timedelta(days=1)},musculation,75,,8,,manual,w1\n",
    )
    return monday


def test_the_week_totals_reset_on_monday(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`ACT-11` : la semaine ISO commence le lundi."""
    monday = seed_week(dav, today_local())
    # Une séance de la semaine précédente ne doit pas compter.
    dav.seed(
        WORKOUTS_FILE,
        dav.content_of(WORKOUTS_FILE) + f"{monday - timedelta(days=3)},yoga,60,,,,manual,w0\n",
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


def test_the_tonnage_is_grouped_by_muscle(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`ACT-14` : les minutes ne distinguent pas trois séries de huit d'une heure de
    repos entre les séries."""
    monday = week_start(today_local())
    dav.seed(
        LOG_FILE,
        "workout_id,date,exercise_id,exercise_name,muscle_group,weight_kg,sets,reps,note\n"
        f"w1,{monday},e1,Développé,pectoraux,80,3,8,\n"
        f"w1,{monday},e2,Squat,jambes,100,5,5,\n",
    )

    muscles = {
        item["muscle_group"]: item
        for item in app_client.get(ACTIVITY, headers=auth).json()["muscles"]
    }

    assert muscles["pectoraux"]["volume_kg"] == 1920  # 80 × 3 × 8
    assert muscles["jambes"]["volume_kg"] == 2500  # 100 × 5 × 5
    assert muscles["pectoraux"]["sets"] == 3


# ── Groupes négligés (`ACT-16`) ───────────────────────


def test_a_group_never_worked_is_none_not_a_huge_number(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """« Jamais » et « il y a très longtemps » ne se traitent pas pareil, et une valeur
    inventée fausserait la génération IA de planning."""
    today = today_local()
    dav.seed(
        LOG_FILE,
        "workout_id,date,exercise_id,exercise_name,muscle_group,weight_kg,sets,reps,note\n"
        f"w1,{today - timedelta(days=5)},e1,Développé,pectoraux,80,3,8,\n",
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
        LOG_FILE,
        "workout_id,date,exercise_id,exercise_name,muscle_group,weight_kg,sets,reps,note\n"
        f"w1,{today - timedelta(days=2)},e1,Développé,pectoraux,80,3,8,\n"
        f"w1,{today - timedelta(days=20)},e2,Squat,jambes,100,5,5,\n",
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


def test_the_progression_tracks_the_heaviest_load_per_session(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Une séance peut contenir plusieurs lignes du même exercice : la charge du jour est
    la plus lourde, pas la dernière consignée."""
    dav.seed(
        LOG_FILE,
        "workout_id,date,exercise_id,exercise_name,muscle_group,weight_kg,sets,reps,note\n"
        "w1,2026-07-01,e1,Développé,pectoraux,80,3,8,\n"
        "w1,2026-07-01,e1,Développé,pectoraux,85,1,3,\n"
        "w2,2026-07-08,e1,Développé,pectoraux,90,3,8,\n",
    )

    progress = app_client.get(f"{ACTIVITY}/progress", headers=auth).json()[0]

    assert progress["max_series"] == [85, 90]
    assert progress["last_weight_kg"] == 90
    assert progress["delta_kg"] == 5


def test_records_include_the_estimated_one_rep_max(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`ACT-15` : Epley — 100 kg × 5 réps donne mieux que 105 kg × 1."""
    dav.seed(
        LOG_FILE,
        "workout_id,date,exercise_id,exercise_name,muscle_group,weight_kg,sets,reps,note\n"
        "w1,2026-07-01,e1,Squat,jambes,105,1,1,\n"
        "w2,2026-07-08,e1,Squat,jambes,100,1,5,\n",
    )

    progress = app_client.get(f"{ACTIVITY}/progress", headers=auth).json()[0]

    assert progress["best_weight_kg"] == 105
    assert progress["best_one_rep_max_kg"] == pytest.approx(116.67, abs=0.01)


def test_a_first_performance_has_no_delta(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    dav.seed(
        LOG_FILE,
        "workout_id,date,exercise_id,exercise_name,muscle_group,weight_kg,sets,reps,note\n"
        "w1,2026-07-01,e1,Squat,jambes,100,5,5,\n",
    )

    assert app_client.get(f"{ACTIVITY}/progress", headers=auth).json()[0]["delta_kg"] is None


def test_an_empty_domain_answers_without_failing(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    body = app_client.get(ACTIVITY, headers=auth).json()

    assert body["total"] == 0
    assert body["week"]["sessions"] == 0
    assert len(body["days"]) == 7
    assert app_client.get(f"{ACTIVITY}/progress", headers=auth).json() == []


# ── Chaîne complète ───────────────────────────────────


def test_the_run_file_stays_readable_in_a_spreadsheet(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    create_run(app_client, auth, note="jambes lourdes")

    lines = dav.content_of(RUNS_FILE).splitlines()

    assert lines[0] == "date,distance_km,duration_min,pace_min_km,avg_hr,elevation_m,note,source"
    assert lines[1].startswith("2026-07-20,8.4,44.2,5.262")
    assert lines[1].endswith("jambes lourdes,manual")
