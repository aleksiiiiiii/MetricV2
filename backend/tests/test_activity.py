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


# ── Correction d'un exercice (`ACT-06`) ───────────────


def log_series(
    client: TestClient, auth: dict[str, str], workout: Any, exercise: Any, **fields: Any
) -> Any:
    body = {"exercise_id": exercise["exercise_id"], "weight_kg": 80, "sets": 3, "reps": 8, **fields}
    response = client.post(
        f"{ACTIVITY}/workouts/{workout['id']}/exercises", json=body, headers=auth
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_correcting_an_exercise_keeps_its_identifier(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """La ligne la plus dangereuse du module : `exercise_id` porte tout l'historique."""
    exercise = create_exercise(app_client, auth, "Développé couhé", "pectoraux")

    corrected = app_client.patch(
        f"{ACTIVITY}/exercises/{exercise['id']}",
        json={"name": "Développé couché", "muscle_group": "pectoraux"},
        headers={**auth, "If-Match": exercise["token"]},
    )

    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["name"] == "Développé couché"
    assert corrected.json()["exercise_id"] == exercise["exercise_id"]


def test_correcting_an_exercise_follows_through_to_the_log(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Sans cela, la progression garderait la faute pendant que le catalogue affiche la
    forme corrigée — le même exercice, deux noms, le même écran."""
    workout = create_workout(app_client, auth)
    exercise = create_exercise(app_client, auth, "Développé couhé", "pectoraux")
    log_series(app_client, auth, workout, exercise)

    app_client.patch(
        f"{ACTIVITY}/exercises/{exercise['id']}",
        json={"name": "Développé couché", "muscle_group": "pectoraux"},
        headers={**auth, "If-Match": exercise["token"]},
    )

    assert "Développé couché" in dav.content_of(LOG_FILE)
    assert "Développé couhé" not in dav.content_of(LOG_FILE)


def test_correcting_an_exercise_leaves_the_others_alone(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    workout = create_workout(app_client, auth)
    corrected = create_exercise(app_client, auth, "Rowing", "dos")
    untouched = create_exercise(app_client, auth, "Squat", "jambes")
    log_series(app_client, auth, workout, corrected)
    log_series(app_client, auth, workout, untouched, weight_kg=100)

    app_client.patch(
        f"{ACTIVITY}/exercises/{corrected['id']}",
        json={"name": "Rowing barre", "muscle_group": "dos"},
        headers={**auth, "If-Match": corrected["token"]},
    )

    log = dav.content_of(LOG_FILE)
    assert "Rowing barre" in log
    assert "Squat,jambes" in log


def test_the_progression_names_the_exercise_as_corrected(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`stats.progress` lit le nom sur le journal, pas sur le catalogue."""
    workout = create_workout(app_client, auth)
    exercise = create_exercise(app_client, auth, "Développé couhé", "pectoraux")
    log_series(app_client, auth, workout, exercise)

    app_client.patch(
        f"{ACTIVITY}/exercises/{exercise['id']}",
        json={"name": "Développé couché", "muscle_group": "pectoraux"},
        headers={**auth, "If-Match": exercise["token"]},
    )

    assert app_client.get(f"{ACTIVITY}/progress", headers=auth).json()[0]["name"] == (
        "Développé couché"
    )


def test_changing_a_muscle_group_moves_the_past_tonnage(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Sinon le même exercice compterait dans deux groupes, selon la date de la série."""
    workout = create_workout(app_client, auth, date=today_local().isoformat())
    exercise = create_exercise(app_client, auth, "Tirage vertical", "biceps")
    log_series(app_client, auth, workout, exercise)

    app_client.patch(
        f"{ACTIVITY}/exercises/{exercise['id']}",
        json={"name": "Tirage vertical", "muscle_group": "dos"},
        headers={**auth, "If-Match": exercise["token"]},
    )

    muscles = app_client.get(ACTIVITY, headers=auth).json()["muscles"]
    assert [item["muscle_group"] for item in muscles] == ["dos"]


def test_correcting_an_exercise_without_a_token_is_refused(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Un `If-Match` absent est un conflit, jamais une permission (`STO-05`)."""
    workout = create_workout(app_client, auth)
    exercise = create_exercise(app_client, auth, "Rowing", "dos")
    log_series(app_client, auth, workout, exercise)

    refused = app_client.patch(
        f"{ACTIVITY}/exercises/{exercise['id']}",
        json={"name": "Rowing barre", "muscle_group": "dos"},
        headers=auth,
    )

    assert refused.status_code == 409
    assert "Rowing barre" not in dav.content_of(LOG_FILE)
    assert app_client.get(f"{ACTIVITY}/exercises", headers=auth).json()[0]["name"] == "Rowing"


def test_correcting_an_exercise_with_a_stale_token_is_refused(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    exercise = create_exercise(app_client, auth, "Rowing", "dos")
    app_client.patch(
        f"{ACTIVITY}/exercises/{exercise['id']}",
        json={"name": "Rowing barre", "muscle_group": "dos"},
        headers={**auth, "If-Match": exercise["token"]},
    )

    replayed = app_client.patch(
        f"{ACTIVITY}/exercises/{exercise['id']}",
        json={"name": "Rowing haltère", "muscle_group": "dos"},
        headers={**auth, "If-Match": exercise["token"]},
    )

    assert replayed.status_code == 409
    assert "Rowing haltère" not in dav.content_of(EXERCISES_FILE)


def test_correcting_an_exercise_to_an_unknown_group_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    exercise = create_exercise(app_client, auth, "Tirage", "dos")

    refused = app_client.patch(
        f"{ACTIVITY}/exercises/{exercise['id']}",
        json={"name": "Tirage", "muscle_group": "avant-bras"},
        headers={**auth, "If-Match": exercise["token"]},
    )

    assert refused.status_code == 422


def test_correcting_an_exercise_never_logged_writes_only_the_catalogue(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    exercise = create_exercise(app_client, auth, "Fente", "jambes")

    corrected = app_client.patch(
        f"{ACTIVITY}/exercises/{exercise['id']}",
        json={"name": "Fente bulgare", "muscle_group": "fessiers"},
        headers={**auth, "If-Match": exercise["token"]},
    )

    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["muscle_group"] == "fessiers"


def test_the_catalogue_counts_what_a_removal_would_leave_behind(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Le compte est fait par le serveur : l'écran dit ce que le geste coûte sans dériver."""
    workout = create_workout(app_client, auth)
    exercise = create_exercise(app_client, auth, "Squat", "jambes")
    log_series(app_client, auth, workout, exercise, weight_kg=100)
    log_series(app_client, auth, workout, exercise, weight_kg=110)
    create_exercise(app_client, auth, "Fente", "jambes")

    catalogue = app_client.get(f"{ACTIVITY}/exercises", headers=auth).json()

    assert {item["name"]: item["entries"] for item in catalogue} == {"Squat": 2, "Fente": 0}


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


def test_a_workout_row_says_how_many_series_it_carries(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Supprimer une séance purge ses séries (`ACT-04`) : la ligne doit pouvoir dire ce
    qu'elle emporte avant que le geste ne s'arme."""
    workout = create_workout(app_client, auth)
    exercise = create_exercise(app_client, auth, "Squat", "jambes")
    log_series(app_client, auth, workout, exercise, weight_kg=100)
    log_series(app_client, auth, workout, exercise, weight_kg=110)
    create_run(app_client, auth)

    history = app_client.get(ACTIVITY, headers=auth).json()["history"]

    assert {item["kind"]: item["entries"] for item in history} == {"workout": 2, "run": 0}


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
    assert app_client.get(f"{ACTIVITY}/progress", headers=auth).json() == []


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


# ── Une séance et ses exercices d'un seul geste (C06) ──


def test_a_workout_can_be_created_with_its_exercises(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """L'assistant de saisie construit la séance entière avant de rien écrire."""
    exercise = app_client.post(
        "/api/activity/exercises",
        json={"name": "Développé couché", "muscle_group": "pectoraux"},
        headers=auth,
    ).json()

    response = app_client.post(
        "/api/activity/workouts",
        json={
            "date": "2026-07-20",
            "type": "musculation",
            "duration_min": "1h15",
            "exercises": [
                {"exercise_id": exercise["exercise_id"], "weight_kg": "60", "sets": 4, "reps": 8},
                {"exercise_id": exercise["exercise_id"], "weight_kg": "0", "sets": 3, "reps": 12},
            ],
        },
        headers=auth,
    )

    assert response.status_code == 201
    body = response.json()
    assert len(body["exercises"]) == 2
    assert body["exercises"][0]["weight_kg"] == 60
    # Le tonnage de la séance suit, calculé par le serveur comme pour toute autre.
    assert body["volume_kg"] == 60 * 4 * 8


def test_an_unknown_exercise_writes_absolutely_nothing(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le seul échec courant de cette route, et il ne doit pas laisser de séance vide.

    C'est tout l'intérêt d'écrire la séance et ses exercices d'un geste : abandonner ou
    se tromper ne laisse rien derrière soi.
    """
    before = dict(dav.files)

    response = app_client.post(
        "/api/activity/workouts",
        json={
            "date": "2026-07-20",
            "type": "musculation",
            "duration_min": "1h15",
            "exercises": [{"exercise_id": "inconnu", "weight_kg": "60", "sets": 4, "reps": 8}],
        },
        headers=auth,
    )

    assert response.status_code >= 400
    assert dict(dav.files) == before


def test_a_workout_without_exercises_is_unchanged(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Les appelants d'avant ne changent pas d'un caractère : la liste vaut `[]`."""
    response = app_client.post(
        "/api/activity/workouts",
        json={"date": "2026-07-20", "type": "musculation", "duration_min": "1h15"},
        headers=auth,
    )

    assert response.status_code == 201
    assert response.json()["exercises"] == []
