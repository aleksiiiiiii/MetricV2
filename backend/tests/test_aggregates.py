"""Agrégats du tableau de bord (`AGG-01` → `AGG-04`).

Trois tests portent le lot. Le premier vérifie qu'un écran d'accueil complet tient en
**une** requête. Le deuxième, que la série d'assiduité survit à un historique troué et ne
s'effondre pas chaque matin. Le troisième, que le contrat de série temporelle sert
plusieurs métriques sans code spécifique — sans quoi « générique » ne voudrait rien dire.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.dates import today_local, tz, week_start
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

DASHBOARD = "/api/aggregates/dashboard"
SERIES = "/api/aggregates/series"
METRICS = "/api/aggregates/metrics"

WEIGHT = "Metric/body/weight.csv"
MEASUREMENTS = "Metric/body/measurements.csv"
RUNS = "Metric/activity/runs.csv"
WORKOUTS = "Metric/activity/workouts.csv"
EXERCISES = "Metric/activity/exercises.csv"
EXERCISE_LOG = "Metric/activity/exercise_log.csv"
MEALS = "Metric/nutrition/meals.csv"
HYDRATION = "Metric/hydration/intake_log.csv"
SUPPLEMENT_LOG = "Metric/supplements/intake_log.csv"
SETTINGS = "Metric/settings/settings.csv"


@pytest.fixture
def app_client(client: TestClient, store: FileStore) -> TestClient:
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


def moment(day: Any, hour: int = 9) -> str:
    """Horodatage local d'un jour, tel qu'il apparaît dans un fichier."""
    return datetime.combine(day, datetime.min.time(), tzinfo=tz()).replace(hour=hour).isoformat()


@pytest.fixture
def seeded(dav: FakeWebDav) -> Any:
    """Un historique plausible : deux mois de données sur toutes les sources."""
    today = today_local()

    dav.seed(
        WEIGHT,
        "date,weight_kg,note,source\n"
        + "".join(
            f"{today - timedelta(days=offset)},{72 + offset * 0.05:.2f},,manual\n"
            for offset in range(0, 60, 3)
        ),
    )
    dav.seed(
        MEASUREMENTS,
        "date,waist_cm,arm_cm,chest_cm,hips_cm,thigh_cm,body_fat_pct,note\n"
        f"{today - timedelta(days=10)},82,36,,,,\n"
        f"{today - timedelta(days=40)},84,35,,,,\n",
    )
    dav.seed(
        RUNS,
        "date,distance_km,duration_min,pace_min_km,avg_hr,elevation_m,note,source\n"
        f"{today - timedelta(days=1)},8.4,44.2,5.26,,,,manual\n"
        f"{today - timedelta(days=8)},10.0,55.0,5.5,,,,manual\n",
    )
    dav.seed(
        WORKOUTS,
        "date,type,duration_min,calories,rpe,note,source,id\n"
        f"{today},musculation,62,,7,,manual,w1\n"
        f"{today - timedelta(days=2)},musculation,58,,6,,manual,w2\n"
        f"{today - timedelta(days=4)},yoga,45,,3,,manual,w3\n",
    )
    dav.seed(
        MEALS,
        f"datetime,meal_type,comment,photo,protein_g,added_sugar_g,calories,source\n{moment(today, 12)},déjeuner,poulet,,42,4,620,manual\n",
    )
    dav.seed(HYDRATION, f"datetime,volume_ml,kind\n{moment(today, 8)},1500,eau\n")
    dav.seed(
        SUPPLEMENT_LOG, f"datetime,schedule_id,name,dose,unit\n{moment(today, 8)},s1,Créatine,5,g\n"
    )
    dav.seed(
        "Metric/supplements/schedule.csv",
        "id,name,dose,unit,time,frequency,active,created\n"
        f"s1,Créatine,5,g,08:00,daily,true,{today - timedelta(days=90)}\n",
    )
    return today


# ── Une requête, tout l'écran (`AGG-01`) ──────────────


def test_the_dashboard_answers_every_indicator_at_once(
    app_client: TestClient, auth: dict[str, str], seeded: Any
) -> None:
    """`AGG-01` : la raison d'être du lot. Dix appels parallèles au chargement d'un écran
    signifieraient dix allers-retours vers Nextcloud."""
    body = app_client.get(DASHBOARD, headers=auth).json()

    for block in (
        "weight",
        "training",
        "nutrition",
        "hydration",
        "supplements",
        "streak",
        "series",
    ):
        assert block in body, block

    assert body["date"] == seeded.isoformat()
    assert body["weight"]["latest_kg"] == 72.0
    assert body["nutrition"]["protein_g"] == 42.0
    assert body["hydration"]["today_ml"] == 1500
    assert body["supplements"]["taken"] == 1


def test_each_source_file_is_pulled_once(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav, seeded: Any
) -> None:
    """La garde qui donne son sens à `AGG-01`.

    Huit services différents sont sollicités et plusieurs veulent le même fichier —
    `settings.csv` est lu par le poids, la nutrition et l'hydratation. Le cache de
    `FileStore` sert alors les lectures suivantes sans requête réseau (`STO-06`).

    Sans cette propriété, regrouper les indicateurs derrière un seul endpoint HTTP
    n'économiserait rien : on aurait juste déplacé les allers-retours du client vers le
    serveur, là où l'utilisateur ne les voit plus.
    """
    del seeded
    dav.reset_journal()

    app_client.get(DASHBOARD, headers=auth)

    fetched = [path for method, path in dav.requests if method == "GET"]
    assert sorted(fetched) == sorted(set(fetched)), "un fichier a été tiré deux fois"


def test_an_empty_installation_answers_without_failing(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Aucun fichier n'existe encore. L'écran doit se peindre — avec des tirets, pas des
    zéros qui passeraient pour des mesures."""
    body = app_client.get(DASHBOARD, headers=auth).json()

    assert body["weight"]["latest_kg"] is None
    assert body["weight"]["count"] == 0
    assert body["training"]["sessions_total"] == 0
    assert body["streak"]["current"] == 0
    assert body["series"]["stats"]["latest"] is None
    assert len(body["streak"]["last_seven"]) == 7


def test_the_dashboard_carries_its_own_series(
    app_client: TestClient, auth: dict[str, str], seeded: Any
) -> None:
    """La série est incluse pour que la première peinture — graphique compris — n'exige
    pas un second appel."""
    del seeded
    series = app_client.get(DASHBOARD, headers=auth).json()["series"]

    assert series["metric"] == "weight"
    assert series["unit"] == "kg"
    assert len(series["points"]) > 0


def test_the_highlighted_metric_comes_from_the_settings(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`HEAT-08` : la métrique mise en avant est un réglage, pas une constante du code."""
    dav.seed(SETTINGS, "key,value\nheatmap_metric,hydration\n")

    assert app_client.get(DASHBOARD, headers=auth).json()["highlight"] == "hydration"


# ── Totaux d'entraînement (`AGG-02`) ──────────────────


def test_training_totals_cover_everything_and_the_current_week(
    app_client: TestClient, auth: dict[str, str], seeded: Any
) -> None:
    training = app_client.get(DASHBOARD, headers=auth).json()["training"]

    assert training["sessions_total"] == 5  # 2 courses + 3 séances
    assert training["week"]["week_start"] == week_start(seeded).isoformat()
    assert len(training["weeks"]) == 8


def test_the_split_names_what_is_neither_a_run_nor_strength(
    app_client: TestClient, auth: dict[str, str], seeded: Any
) -> None:
    """Ranger une heure de yoga sous « musculation » pour n'afficher que deux parts
    donnerait un chiffre faux."""
    del seeded
    split = {
        part["kind"]: part
        for part in app_client.get(DASHBOARD, headers=auth).json()["training"]["split"]
    }

    assert split["run"]["sessions"] == 2
    assert split["strength"]["sessions"] == 2
    assert split["other"]["sessions"] == 1
    assert split["other"]["label"] == "Autre"
    assert sum(part["ratio"] for part in split.values()) == pytest.approx(1.0)


def test_an_empty_part_disappears_from_the_split(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    dav.seed(
        RUNS,
        "date,distance_km,duration_min,pace_min_km,avg_hr,elevation_m,note,source\n"
        f"{today_local()},5.0,25.0,5.0,,,,manual\n",
    )

    split = app_client.get(DASHBOARD, headers=auth).json()["training"]["split"]

    assert [part["kind"] for part in split] == ["run"]


def test_the_weekly_history_stops_at_eight_weeks(
    app_client: TestClient, auth: dict[str, str], seeded: Any
) -> None:
    """`ACT-12` : la borne est exacte, pas « à peu près »."""
    weeks = app_client.get(DASHBOARD, headers=auth).json()["training"]["weeks"]

    assert len(weeks) == 8
    assert weeks[-1]["week_start"] == week_start(seeded).isoformat()
    assert weeks[0]["week_start"] == (week_start(seeded) - timedelta(weeks=7)).isoformat()


# ── Série d'assiduité (`AGG-03`) ──────────────────────


def days_file(dav: FakeWebDav, *offsets: int) -> None:
    """Sème des pesées aux jours indiqués, en nombre de jours avant aujourd'hui."""
    today = today_local()
    dav.seed(
        WEIGHT,
        "date,weight_kg,note,source\n"
        + "".join(f"{today - timedelta(days=offset)},72.0,,manual\n" for offset in offsets),
    )


def test_the_streak_counts_consecutive_days_of_any_source(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    days_file(dav, 0, 1, 2, 3)

    assert app_client.get(DASHBOARD, headers=auth).json()["streak"]["current"] == 4


def test_yesterday_stays_valid_while_today_is_not_over(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le test qui compte.

    Sans cette règle, une série de quarante jours tomberait à zéro chaque matin au
    réveil pour remonter à quarante et un le soir venu — un compteur qui ment la moitié
    du temps.
    """
    days_file(dav, 1, 2, 3)

    assert app_client.get(DASHBOARD, headers=auth).json()["streak"]["current"] == 3


def test_a_hole_of_two_days_ends_the_streak(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Un jour manqué avant-hier ne se rattrape pas : la série repart d'hier."""
    days_file(dav, 1, 2, 4, 5, 6, 7)

    body = app_client.get(DASHBOARD, headers=auth).json()["streak"]

    assert body["current"] == 2
    assert body["longest"] == 4
    assert body["active_days"] == 6


def test_the_streak_mixes_all_seven_sources(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """« Au moins une donnée, toutes sources confondues » : trois jours tenus par trois
    domaines différents forment bien une série de trois."""
    today = today_local()
    dav.seed(WEIGHT, f"date,weight_kg,note,source\n{today},72.0,,manual\n")
    dav.seed(
        RUNS,
        "date,distance_km,duration_min,pace_min_km,avg_hr,elevation_m,note,source\n"
        f"{today - timedelta(days=1)},5.0,25.0,5.0,,,,manual\n",
    )
    dav.seed(HYDRATION, f"datetime,volume_ml,kind\n{moment(today - timedelta(days=2))},500,eau\n")

    body = app_client.get(DASHBOARD, headers=auth).json()["streak"]

    assert body["current"] == 3
    assert body["last_seven"][-1]["sources"] == ["weight"]
    assert body["last_seven"][-2]["sources"] == ["runs"]


def test_the_recent_window_is_complete_even_when_empty(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Les sept jours sont retournés quoi qu'il arrive : le client n'a aucun trou à
    combler, comme l'exige `HEAT-24` pour les grilles."""
    days_file(dav, 0)

    last_seven = app_client.get(DASHBOARD, headers=auth).json()["streak"]["last_seven"]

    assert len(last_seven) == 7
    assert last_seven[-1]["active"] is True
    assert all(day["active"] is False for day in last_seven[:-1])
    assert last_seven[0]["sources"] == []


def test_an_hydration_day_at_zero_does_not_count(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Une prise supprimée laisse le jour sans donnée : il ne doit pas tenir la série."""
    dav.seed(HYDRATION, "datetime,volume_ml,kind\n")

    assert app_client.get(DASHBOARD, headers=auth).json()["streak"]["current"] == 0


# ── Séries temporelles génériques (`AGG-04`) ──────────


@pytest.mark.parametrize(
    ("metric", "unit"),
    [("weight", "kg"), ("hydration", "ml"), ("weekly_minutes", "min"), ("waist_cm", "cm")],
)
def test_one_contract_serves_several_metrics(
    app_client: TestClient, auth: dict[str, str], seeded: Any, metric: str, unit: str
) -> None:
    """La DoD du lot : `AGG-04` sert au moins trois métriques **sans code spécifique**."""
    del seeded
    body = app_client.get(f"{SERIES}?metric={metric}&range=all", headers=auth).json()

    assert body["metric"] == metric
    assert body["unit"] == unit
    assert body["stats"]["count"] == len(body["points"])
    assert body["points"] == sorted(body["points"], key=lambda point: point["date"])


def test_the_statistics_describe_the_returned_range(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    today = today_local()
    dav.seed(
        WEIGHT,
        "date,weight_kg,note,source\n"
        f"{today - timedelta(days=20)},74.0,,manual\n"
        f"{today - timedelta(days=10)},73.0,,manual\n"
        f"{today},71.0,,manual\n",
    )

    stats = app_client.get(f"{SERIES}?metric=weight&range=1m", headers=auth).json()["stats"]

    assert stats["latest"] == 71.0
    assert stats["latest_date"] == today.isoformat()
    assert stats["change"] == -3.0
    assert stats["average"] == pytest.approx(72.67, abs=0.01)
    assert stats["minimum"] == 71.0
    assert stats["maximum"] == 74.0
    assert stats["count"] == 3


def test_a_narrower_range_changes_the_variation(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """C'est ce que le sélecteur de période promet de montrer : la variation **sur la
    plage**, pas depuis toujours."""
    today = today_local()
    dav.seed(
        WEIGHT,
        "date,weight_kg,note,source\n"
        f"{today - timedelta(days=80)},80.0,,manual\n"
        f"{today - timedelta(days=20)},74.0,,manual\n"
        f"{today},71.0,,manual\n",
    )

    over_three = app_client.get(f"{SERIES}?metric=weight&range=3m", headers=auth).json()
    over_one = app_client.get(f"{SERIES}?metric=weight&range=1m", headers=auth).json()

    assert over_three["stats"]["change"] == -9.0
    assert over_one["stats"]["change"] == -3.0


def test_the_range_is_counted_from_today_not_from_the_last_entry(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Ancrée sur le dernier point, une fenêtre d'un mois couvrirait un an après une
    pause — et « rien ce mois-ci » s'afficherait comme un mois plein."""
    today = today_local()
    dav.seed(
        WEIGHT,
        "date,weight_kg,note,source\n"
        f"{today - timedelta(days=200)},80.0,,manual\n"
        f"{today - timedelta(days=190)},79.0,,manual\n",
    )

    body = app_client.get(f"{SERIES}?metric=weight&range=1m", headers=auth).json()

    assert body["points"] == []
    assert body["stats"]["latest"] is None
    assert body["stats"]["count"] == 0


def test_a_weekly_metric_is_dated_on_the_monday(
    app_client: TestClient, auth: dict[str, str], seeded: Any
) -> None:
    body = app_client.get(f"{SERIES}?metric=weekly_minutes&range=all", headers=auth).json()

    assert body["granularity"] == "week"
    for point in body["points"]:
        assert week_start(seeded).weekday() == 0
        assert datetime.fromisoformat(point["date"]).weekday() == 0


def test_a_parameterised_metric_needs_its_subject(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`AGG-04` sert aussi la charge d'un exercice donné, sans endpoint dédié."""
    today = today_local()
    dav.seed(EXERCISES, "id,name,muscle_group\ne1,Développé couché,pectoraux\ne2,Squat,jambes\n")
    dav.seed(
        EXERCISE_LOG,
        "workout_id,date,exercise_id,exercise_name,muscle_group,weight_kg,sets,reps,note\n"
        f"w1,{today},e1,Développé couché,pectoraux,80,3,8,\n"
        f"w1,{today},e2,Squat,jambes,120,3,5,\n",
    )

    bench = app_client.get(
        f"{SERIES}?metric=exercise_load&subject=e1&range=all", headers=auth
    ).json()

    assert bench["subject"] == "e1"
    assert [point["value"] for point in bench["points"]] == [80.0]


def test_an_unknown_metric_is_refused(app_client: TestClient, auth: dict[str, str]) -> None:
    response = app_client.get(f"{SERIES}?metric=humeur", headers=auth)

    assert response.status_code == 404
    assert response.json()["code"] == "storage_not_found"


def test_an_unknown_range_is_refused_by_the_contract(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Déclarée en `Literal`, la plage est validée par le schéma : pas de code de garde,
    et un message de validation utile."""
    response = app_client.get(f"{SERIES}?metric=weight&range=6m", headers=auth)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_the_metric_catalogue_is_published(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le sélecteur de l'écran ne code aucune liste : ajouter une métrique au serveur la
    rend choisissable sans toucher au client."""
    dav.seed(EXERCISES, "id,name,muscle_group\ne1,Développé couché,pectoraux\n")

    catalogue = app_client.get(METRICS, headers=auth).json()
    keys = {entry["key"] for entry in catalogue}

    assert {"weight", "hydration", "weekly_minutes", "weekly_volume_kg", "waist_cm"} <= keys

    parameterised = next(entry for entry in catalogue if entry["key"] == "exercise_load")
    assert parameterised["subjects"] == [{"key": "e1", "label": "Développé couché"}]
    assert all(entry["subjects"] == [] for entry in catalogue if entry["key"] != "exercise_load")


def test_a_measurement_series_ignores_the_days_it_was_not_taken(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Chaque mesure a son propre historique : une série de tours de bras ne se troue pas
    parce qu'un jour seul le tour de taille a été relevé."""
    today = today_local()
    dav.seed(
        MEASUREMENTS,
        "date,waist_cm,arm_cm,chest_cm,hips_cm,thigh_cm,body_fat_pct,note\n"
        f"{today - timedelta(days=5)},82,,,,,\n"
        f"{today},81,36,,,,\n",
    )

    waist = app_client.get(f"{SERIES}?metric=waist_cm&range=all", headers=auth).json()
    arm = app_client.get(f"{SERIES}?metric=arm_cm&range=all", headers=auth).json()

    assert [point["value"] for point in waist["points"]] == [82.0, 81.0]
    assert [point["value"] for point in arm["points"]] == [36.0]
