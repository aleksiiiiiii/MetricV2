"""Contrat d'API des grilles d'assiduité (spec `HEAT` v2 §8, lot L11).

Le moteur est éprouvé sur des dictionnaires (`test_heat_engine`), la couture sur des
fichiers (`test_heat_grids`). Ce fichier-ci vérifie la **dernière marche** : que ce qui
sort du moteur arrive au client dans la forme promise, et que les paramètres d'URL ne
peuvent pas produire une réponse absurde.

Trois propriétés y sont vérifiées et nulle part ailleurs :

* `/api/heatmap/tracks` reste la configuration et **n'est pas capté** par la route de
  grille `/api/heatmap/{track_id}` — un ordre de déclaration inversé ferait chercher une
  piste nommée « tracks », et le symptôme serait un 404 inexplicable sur l'écran de
  réglages ;
* une piste `per_week` ne rend **jamais** de jour `missed` (`HEAT-11`) : c'est la semaine
  qui porte le verdict, et un écran qui chercherait des jours rouges y verrait un
  sans-faute permanent ;
* les jours `off` disent **pourquoi** ils le sont, sans quoi une piste créée hier
  montrerait un an de cellules identiques à une année d'échecs.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.dates import today_local, tz, week_start
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

GRIDS = "/api/heatmap"
TRACKS = "/api/heatmap/tracks"

TRACKS_FILE = "Metric/settings/heatmap_tracks.csv"
CADENCES_FILE = "Metric/settings/heatmap_cadences.csv"
OFF_FILE = "Metric/settings/heatmap_off_days.csv"

EXERCISE_LOG = "Metric/activity/exercise_log.csv"
HYDRATION = "Metric/hydration/intake_log.csv"

TRACK_HEADER = (
    "id,label,source,filter,validation_threshold,levels,binary,accent,position,active,created\n"
)


@pytest.fixture
def app_client(client: TestClient, store: FileStore) -> TestClient:
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


def moment(day: date, hour: int = 9) -> str:
    return datetime.combine(day, datetime.min.time(), tzinfo=tz()).replace(hour=hour).isoformat()


def seed_tracks(dav: FakeWebDav, *lines: str) -> None:
    dav.seed(TRACKS_FILE, TRACK_HEADER + "".join(lines))


def water(created: date) -> str:
    return f"eau,Eau,hydration.intake,,1500,1000;1500;2000;2500,false,signal,0,true,{created}\n"


def torso(created: date) -> str:
    return f"torse,Torse,activity.muscle_group,pectoraux,1,1;3;6;10,false,effort,1,true,{created}\n"


def get(client: TestClient, auth: dict[str, str], path: str, **params: Any) -> Any:
    response = client.get(path, headers=auth, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def cells(grid: Any) -> dict[str, Any]:
    return {day["date"]: day for day in grid["days"]}


def payload_for(
    *,
    threshold: float = 1500,
    levels: list[float] | None = None,
    cadence: str = "daily",
) -> dict[str, Any]:
    """La piste eau, telle que l'écran la renverrait après édition d'un seul champ."""
    return {
        "label": "Eau",
        "source": "hydration.intake",
        "filter": "",
        "validation_threshold": threshold,
        "levels": levels if levels is not None else [1000, 1500, 2000, 2500],
        "cadence": cadence,
    }


# ── Forme de la réponse (`HEAT-24`, spec §8) ──────────


async def test_a_grid_has_exactly_the_shape_the_spec_describes(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le §8 donne un exemple de réponse au champ près. C'est un contrat, pas une
    illustration : un client écrit contre lui ne doit rien avoir à deviner."""
    today = today_local()
    seed_tracks(dav, water(today - timedelta(days=60)))
    dav.seed(HYDRATION, f"datetime,volume_ml,kind\n{moment(today - timedelta(days=1))},1800,eau\n")

    body = get(app_client, auth, f"{GRIDS}/eau")

    assert set(body) == {"track", "cadence", "range", "days", "weeks", "stats"}
    assert body["track"] == {
        "id": "eau",
        "label": "Eau",
        "unit": "ml",
        "binary": False,
        "accent": "signal",
        "source": "hydration.intake",
        "levels": [1000.0, 1500.0, 2000.0, 2500.0],
        "validation_threshold": 1500.0,
        "created": str(today - timedelta(days=60)),
    }
    assert body["cadence"]["type"] == "daily"
    assert body["cadence"]["label"] == "tous les jours"
    assert set(body["range"]) == {"from", "to"}
    assert set(body["stats"]) == {
        "validated_days",
        "expected_days",
        "compliance",
        "longest_streak",
        "current_streak",
        "best_day",
        "best_value",
        "total",
    }

    yesterday = cells(body)[str(today - timedelta(days=1))]
    assert yesterday == {
        "date": str(today - timedelta(days=1)),
        "value": 1800.0,
        "state": "done",
        "level": 2,
        "reason": None,
    }


async def test_the_default_range_is_53_full_weeks_ending_on_a_sunday(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`HEAT-31` et la décision **D6**.

    L'alignement prime sur les « 371 jours se terminant aujourd'hui » : une colonne
    tronquée se voit, un décalage d'un jour ne se voit pas et fausse la lecture.
    """
    today = today_local()
    seed_tracks(dav, water(today - timedelta(days=10)))

    body = get(app_client, auth, f"{GRIDS}/eau")

    start = date.fromisoformat(body["range"]["from"])
    end = date.fromisoformat(body["range"]["to"])

    assert len(body["days"]) == 371
    assert start.weekday() == 0
    assert end.weekday() == 6
    assert end == week_start(today) + timedelta(days=6)


async def test_a_range_given_in_the_url_is_honoured(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    today = today_local()
    seed_tracks(dav, water(today - timedelta(days=60)))

    body = get(
        app_client,
        auth,
        f"{GRIDS}/eau",
        **{"from": str(today - timedelta(days=6)), "to": str(today)},
    )

    assert len(body["days"]) == 7
    assert body["range"] == {"from": str(today - timedelta(days=6)), "to": str(today)}


# ── Pourquoi un jour est `off` ────────────────────────


async def test_days_after_today_are_off_because_they_have_not_happened(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le premier des deux pièges de rendu repérés au lot L10.

    La plage par défaut va jusqu'au dimanche : les cellules après aujourd'hui existent et
    valent `off`. Les peindre comme un échec serait faux, les peindre comme un trou aussi
    — d'où la nuance, qui ne change pas l'état.

    La plage est demandée explicitement et non laissée au défaut : celui-ci ne dépasse
    aujourd'hui que du lundi au samedi, et un test qui ne vérifie rien le dimanche est un
    test qui ne vérifie rien.
    """
    today = today_local()
    seed_tracks(dav, water(today - timedelta(days=60)))

    body = get(
        app_client,
        auth,
        f"{GRIDS}/eau",
        **{"from": str(today - timedelta(days=3)), "to": str(today + timedelta(days=3))},
    )
    grid = cells(body)

    ahead = [day for day in body["days"] if date.fromisoformat(day["date"]) > today]
    assert len(ahead) == 3
    assert all(day["state"] == "off" and day["reason"] == "future" for day in ahead)

    # Aujourd'hui n'est ni manqué ni à venir : la journée n'est pas finie (`HEAT-08`).
    assert grid[str(today)]["state"] == "off"
    assert grid[str(today)]["reason"] == "pending"


async def test_days_before_the_track_existed_say_so(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`HEAT-07`. Sans la nuance, une piste créée hier afficherait une année entière de
    cellules que rien ne distingue d'une année sans rien faire."""
    today = today_local()
    created = today - timedelta(days=3)
    seed_tracks(dav, water(created))

    body = get(app_client, auth, f"{GRIDS}/eau")
    grid = cells(body)

    assert grid[str(created - timedelta(days=1))]["reason"] == "before_track"
    assert grid[str(created)]["reason"] != "before_track"


async def test_a_neutralised_day_is_told_apart_from_a_day_nothing_was_expected(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`HEAT-06`. Une semaine de grippe et une semaine sans attente sont deux histoires
    différentes ; sans la nuance, elles rendent la même cellule grise."""
    today = today_local()
    sick = today - timedelta(days=5)
    seed_tracks(dav, water(today - timedelta(days=60)))
    dav.seed(
        OFF_FILE,
        f"id,track_id,date_from,date_to,reason\no1,eau,{sick},{sick},grippe\n",
    )

    body = get(app_client, auth, f"{GRIDS}/eau")
    grid = cells(body)

    assert grid[str(sick)]["state"] == "off"
    assert grid[str(sick)]["reason"] == "neutralised"
    # Le lendemain, lui, redevient jugeable — et manqué, l'eau étant quotidienne.
    assert grid[str(sick + timedelta(days=1))]["state"] == "missed"
    assert grid[str(sick + timedelta(days=1))]["reason"] is None


# ── Pistes hebdomadaires (`HEAT-11`, `HEAT-28`) ───────


async def test_a_per_week_track_never_paints_a_missed_day(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le second piège de rendu du lot L10, et le plus coûteux à découvrir tard.

    Sur « torse 2×/semaine », le rouge se pose sur la **semaine** et jamais sur le jour.
    Un écran qui chercherait des jours rouges y lirait un sans-faute permanent.
    """
    today = today_local()
    seed_tracks(dav, torso(today - timedelta(days=90)))
    dav.seed(
        CADENCES_FILE,
        "id,track_id,type,params,valid_from\n"
        f"c1,torse,per_week,count=2,{today - timedelta(days=90)}\n",
    )
    dav.seed(
        EXERCISE_LOG,
        "workout_id,date,exercise_id,exercise_name,muscle_group,weight_kg,sets,reps,note\n",
    )

    body = get(app_client, auth, f"{GRIDS}/torse")

    assert body["weeks"] is not None
    assert all(day["state"] != "missed" for day in body["days"])
    assert any(week["status"] == "missed" for week in body["weeks"])
    assert all(set(week) == {"start", "status", "done", "expected"} for week in body["weeks"])
    assert all(date.fromisoformat(week["start"]).weekday() == 0 for week in body["weeks"])


async def test_a_daily_track_has_no_weekly_statuses(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`weeks` à `null` et non une liste vide : « cette piste ne se juge pas à la
    semaine » et « aucune semaine » ne sont pas la même chose."""
    today = today_local()
    seed_tracks(dav, water(today - timedelta(days=30)))

    assert get(app_client, auth, f"{GRIDS}/eau")["weeks"] is None


# ── Lecture multi-pistes (`HEAT-25`) ──────────────────


async def test_several_tracks_come_back_in_one_call_sharing_one_range(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """La plage est remontée d'un cran, et c'est délibéré : la répéter par grille
    inviterait un client à les afficher désalignées."""
    today = today_local()
    seed_tracks(dav, water(today - timedelta(days=60)), torso(today - timedelta(days=60)))

    body = get(app_client, auth, GRIDS, tracks="eau,torse")

    assert set(body) == {"range", "grids"}
    assert [grid["track"]["id"] for grid in body["grids"]] == ["eau", "torse"]
    assert all(
        grid["range"] == body["range"] and len(grid["days"]) == 371 for grid in body["grids"]
    )


async def test_without_a_track_list_every_active_track_is_returned(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    today = today_local()
    seed_tracks(
        dav,
        water(today - timedelta(days=60)),
        f"vieux,Ancienne,activity.runs,,1,,false,signal,2,false,{today - timedelta(days=60)}\n",
    )

    body = get(app_client, auth, GRIDS)

    assert [grid["track"]["id"] for grid in body["grids"]] == ["eau"]


async def test_an_empty_installation_seeds_its_tracks_before_drawing_them(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Ouvrir l'écran pour la première fois montre des grilles peuplées de son propre
    historique, pas un formulaire de création vide."""
    body = get(app_client, auth, GRIDS)

    assert [grid["track"]["id"] for grid in body["grids"]][:5] == [
        "torse",
        "dos",
        "bras",
        "jambes",
        "abdos",
    ]


# ── Détail d'un jour (`HEAT-29`) ──────────────────────


async def test_a_cell_can_be_opened_to_see_what_composes_it(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Une grille qui ne s'explore pas ne se vérifie pas : voir « 12 séries » sans
    pouvoir demander lesquelles laisse l'utilisateur sans recours."""
    today = today_local()
    day = today - timedelta(days=2)
    seed_tracks(dav, torso(today - timedelta(days=60)))
    dav.seed(
        EXERCISE_LOG,
        "workout_id,date,exercise_id,exercise_name,muscle_group,weight_kg,sets,reps,note\n"
        f"w1,{day},e1,Développé couché,pectoraux,80,4,8,\n"
        f"w1,{day},e2,Écarté,pectoraux,20,3,12,léger\n",
    )

    body = get(app_client, auth, f"{GRIDS}/torse/day/{day}")

    assert body["track"]["id"] == "torse"
    assert body["day"]["date"] == str(day)
    assert body["day"]["value"] == 7
    assert body["day"]["state"] == "done"
    assert [entry["label"] for entry in body["entries"]] == ["Développé couché", "Écarté"]
    assert body["entries"][0]["sets"] == 4
    assert body["entries"][0]["reps"] == 8
    assert body["entries"][0]["weight_kg"] == 80
    assert body["entries"][1]["note"] == "léger"


async def test_a_day_without_entries_still_reports_its_state(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """La cellule accompagne toujours le détail. Rendre les seules lignes de saisie
    obligerait le client à retrouver l'état ailleurs — ou à le recalculer, ce que
    `HEAT-30` interdit."""
    today = today_local()
    day = today - timedelta(days=2)
    seed_tracks(dav, water(today - timedelta(days=60)))

    body = get(app_client, auth, f"{GRIDS}/eau/day/{day}")

    assert body["entries"] == []
    assert body["day"]["state"] == "missed"


async def test_a_day_still_to_come_is_refused(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    today = today_local()
    seed_tracks(dav, water(today - timedelta(days=60)))

    response = app_client.get(f"{GRIDS}/eau/day/{today + timedelta(days=1)}", headers=auth)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# ── Paramètres refusés ────────────────────────────────


@pytest.mark.parametrize(
    ("params", "why"),
    [
        ({"from": "2026-01-01"}, "une seule borne"),
        ({"to": "2026-01-01"}, "une seule borne"),
        ({"from": "2026-03-01", "to": "2026-01-01"}, "plage à l'envers"),
        ({"from": "2000-01-01", "to": "2026-01-01"}, "plage démesurée"),
    ],
)
async def test_an_unusable_range_is_refused_rather_than_guessed(
    app_client: TestClient,
    auth: dict[str, str],
    dav: FakeWebDav,
    params: dict[str, str],
    why: str,
) -> None:
    """Une borne manquante ferait dépendre l'autre extrémité d'un défaut invisible dans
    l'URL ; une plage à l'envers rendrait une grille vide que l'utilisateur lirait comme
    une année sans rien faire."""
    seed_tracks(dav, water(today_local() - timedelta(days=60)))

    response = app_client.get(f"{GRIDS}/eau", headers=auth, params=params)

    assert response.status_code == 422, why
    assert response.json()["code"] == "validation_error"


async def test_an_unknown_track_is_a_404(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    seed_tracks(dav, water(today_local() - timedelta(days=60)))

    response = app_client.get(f"{GRIDS}/inexistante", headers=auth)

    assert response.status_code == 404


async def test_the_configuration_route_is_not_captured_by_the_grid_route(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`/api/heatmap/tracks` doit rester la configuration.

    FastAPI retient la **première** route qui correspond : déclarer `/{track_id}` avant
    `/tracks` ferait chercher une piste nommée « tracks », et le symptôme — un 404 sur
    l'écran de réglages — n'a rien qui désigne l'ordre de déclaration.
    """
    seed_tracks(dav, water(today_local() - timedelta(days=60)))

    body = get(app_client, auth, TRACKS)

    assert "sources" in body and "highlight" in body


async def test_reading_a_grid_requires_a_session(app_client: TestClient) -> None:
    assert app_client.get(f"{GRIDS}/eau").status_code == 401
    assert app_client.get(GRIDS).status_code == 401


# ── Chiffrage d'un changement de seuil (`HEAT-20`, **D4**) ──


async def test_raising_a_threshold_says_how_many_days_would_turn_red(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """La dette laissée par le lot L09, et le cœur de la décision **D4**.

    « Changer un seuil réécrit tout l'historique, et doit être annoncé » — annoncé, mais
    aussi **chiffré** : « ta grille va changer » est vrai de toute modification et n'aide
    à décider d'aucune.
    """
    today = today_local()
    seed_tracks(dav, water(today - timedelta(days=60)))
    dav.seed(
        HYDRATION,
        "datetime,volume_ml,kind\n"
        + "".join(
            f"{moment(today - timedelta(days=offset))},1800,eau\n" for offset in range(1, 11)
        ),
    )

    body = app_client.post(
        "/api/heatmap/tracks/eau/preview",
        headers=auth,
        json={
            "label": "Eau",
            "source": "hydration.intake",
            "filter": "",
            "validation_threshold": 2000,
            "levels": [1000, 1500, 2000, 2500],
            "cadence": "daily",
        },
    ).json()

    assert body["retroactive"] is True
    assert body["to_missed"] == 10
    assert body["to_done"] == 0
    assert body["changed_days"] == 10
    assert body["warnings"] == ["10 journées passeraient de validée à manquée."]


async def test_lowering_a_threshold_says_how_many_days_would_be_won_back(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    today = today_local()
    seed_tracks(dav, water(today - timedelta(days=60)))
    dav.seed(
        HYDRATION,
        "datetime,volume_ml,kind\n"
        + "".join(f"{moment(today - timedelta(days=offset))},900,eau\n" for offset in range(1, 4)),
    )

    body = app_client.post(
        "/api/heatmap/tracks/eau/preview",
        headers=auth,
        json=payload_for(threshold=500),
    ).json()

    assert body["to_done"] == 3
    assert body["to_missed"] == 0
    assert body["warnings"] == ["3 journées passeraient de manquée à validée."]


async def test_a_single_day_is_written_in_the_singular(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le message est composé par le serveur et affiché tel quel : « 1 journées » se
    verrait, et une phrase fausse fait douter du chiffre qu'elle porte."""
    today = today_local()
    seed_tracks(dav, water(today - timedelta(days=60)))
    dav.seed(
        HYDRATION,
        f"datetime,volume_ml,kind\n{moment(today - timedelta(days=1))},1800,eau\n",
    )

    body = app_client.post(
        "/api/heatmap/tracks/eau/preview", headers=auth, json=payload_for(threshold=2000)
    ).json()

    assert body["warnings"] == ["1 journée passerait de validée à manquée."]


async def test_moving_only_the_gradient_says_the_grid_changes_shade(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Déplacer les bornes d'intensité sans toucher au seuil ne fait changer aucun jour
    de camp. Annoncer « aucune journée ne changerait » serait pourtant faux : la grille
    change bel et bien d'aspect, et l'utilisateur croirait son réglage sans effet."""
    today = today_local()
    seed_tracks(dav, water(today - timedelta(days=60)))
    dav.seed(
        HYDRATION,
        "datetime,volume_ml,kind\n"
        + "".join(f"{moment(today - timedelta(days=offset))},1800,eau\n" for offset in range(1, 6)),
    )

    body = app_client.post(
        "/api/heatmap/tracks/eau/preview",
        headers=auth,
        json=payload_for(levels=[100, 200, 300, 400]),
    ).json()

    assert body["changed_days"] == 0
    assert body["restyled"] == 5
    assert body["warnings"] == ["5 journées garderaient leur état mais changeraient d'intensité."]


async def test_changing_only_the_cadence_is_not_retroactive(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`HEAT-14`. Une cadence est un engagement daté : la simuler sur le passé annoncerait
    un bouleversement qui n'aura pas lieu."""
    today = today_local()
    seed_tracks(dav, water(today - timedelta(days=60)))

    body = app_client.post(
        "/api/heatmap/tracks/eau/preview",
        headers=auth,
        json=payload_for(cadence="window:min_count=1;window_days=3"),
    ).json()

    assert body["retroactive"] is False
    assert body["changed_days"] == 0
    assert body["warnings"] == []


async def test_rebranching_a_track_onto_another_source_is_retroactive(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Manquait à la liste du lot L09 : la modification passait pour non rétroactive
    alors qu'elle réécrit toute la grille."""
    today = today_local()
    seed_tracks(dav, torso(today - timedelta(days=60)))
    dav.seed(
        EXERCISE_LOG,
        "workout_id,date,exercise_id,exercise_name,muscle_group,weight_kg,sets,reps,note\n"
        + "".join(
            f"w{offset},{today - timedelta(days=offset)},e1,Développé,pectoraux,60,4,10,\n"
            for offset in range(1, 6)
        ),
    )

    body = app_client.post(
        "/api/heatmap/tracks/torse/preview",
        headers=auth,
        json={
            "label": "Torse",
            "source": "activity.muscle_group",
            "filter": "jambes",
            "validation_threshold": 1,
            "levels": [1, 3, 6, 10],
            "cadence": "daily",
        },
    ).json()

    assert body["retroactive"] is True
    assert body["to_missed"] == 5
