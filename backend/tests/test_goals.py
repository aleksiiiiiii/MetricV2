"""Domaine Objectifs (`GOAL-03` → `GOAL-06`).

Les huit familles du patron de domaine, plus deux qui n'existent que pour ce lot-ci :

* **la progression sur les cinq métriques** de `GOAL-04`, chacune avec son point de
  départ, ses données manquantes et son cas dégénéré ;
* **`goals.csv` est un fichier de planning**, pas de mesure. Une cellule vide y est un cas
  normal — et c'est le défaut qui a fait tomber le tableau de bord entier en `502` au
  premier usage réel, sur un fichier de la même famille.

Le calcul lui-même se teste sans rien monter : `progress.py` ne lit ni fichier, ni horloge.
C'est le même parti pris que le moteur d'assiduité, et il a la même conséquence — les cas
limites tiennent en cinq lignes.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.dates import today_local, week_start
from app.domains.aggregates.service import METRICS
from app.domains.goals.metrics import GOAL_METRICS
from app.domains.goals.progress import current_value, ratio, summary, window
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

GOALS = "/api/goals"
GOALS_FILE = "Metric/goals/goals.csv"
GOALS_HEADER = "id,created,title,metric,target,unit,deadline,rationale,source,status,outcome"
WEEKLY_FILE = "Metric/insights/weekly.csv"
WEIGHT_FILE = "Metric/body/weight.csv"
RUNS_FILE = "Metric/activity/runs.csv"
WORKOUTS_FILE = "Metric/activity/workouts.csv"

TODAY = today_local()
#: Échéance par défaut : six semaines, au milieu de la fenêtre de `GOAL-01`.
DEADLINE = TODAY + timedelta(weeks=6)


@pytest.fixture
def app_client(client: TestClient, store: FileStore) -> TestClient:
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


def adopt(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    body = {
        "title": "Trois séances par semaine",
        "metric": "weekly_sessions",
        "target": 3,
        "deadline": DEADLINE.isoformat(),
        "rationale": "1,8 séance par semaine sur les quatre dernières",
        **fields,
    }
    return client.post(GOALS, json=body, headers=auth)


def adopted(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    response = adopt(client, auth, **fields)
    assert response.status_code == 201, response.text
    return response.json()


def view(client: TestClient, auth: dict[str, str]) -> Any:
    response = client.get(GOALS, headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def seed_workouts(dav: FakeWebDav, days: list[date]) -> None:
    """Séances effectuées, une par jour donné."""
    lines = "".join(
        f"{day.isoformat()},musculation,60,,,,manual,w{index}\n" for index, day in enumerate(days)
    )
    dav.seed(WORKOUTS_FILE, "date,type,duration_min,calories,rpe,note,source,id\n" + lines)


# ── 1. Écriture réelle dans le CSV ────────────────────


def test_an_adopted_goal_is_written_with_the_annex_columns(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Colonnes et ordre de l'annexe du backlog, accents et BOM compris."""
    adopted(app_client, auth, rationale="Parce qu'on en est à 1,8")

    header, line = dav.content_of(GOALS_FILE).splitlines()[:2]

    assert header == GOALS_HEADER
    assert dav.files[GOALS_FILE].content.startswith(b"\xef\xbb\xbf")
    assert "Trois séances par semaine" in line
    assert line.endswith(",ai,active,")  # source, status, résultat encore vide


def test_the_unit_is_written_by_the_server_not_by_the_client(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """« Une valeur partagée est servie, jamais recopiée ».

    Le client n'envoie pas d'unité : un client qui le pourrait écrirait « kg » sur un
    objectif de protéines, et le fichier mentirait pour toujours — y compris ouvert dans un
    tableur dans dix ans, où plus rien ne permettrait de le corriger.
    """
    entry = adopted(app_client, auth, metric="daily_protein_g", target=150)

    assert entry["unit"] == METRICS["daily_protein_g"].unit == "g"
    assert ",g," in dav.content_of(GOALS_FILE).splitlines()[1]


# ── 2. Bornes refusées ────────────────────────────────


@pytest.mark.parametrize("weeks", [1, 3, 9, 20])
def test_a_deadline_outside_four_to_eight_weeks_is_refused(
    app_client: TestClient, auth: dict[str, str], weeks: int
) -> None:
    """`GOAL-01` : « daté sur 4 à 8 semaines ». La borne vaut à l'adoption aussi.

    Personne n'a tapé ces chiffres — ils viennent d'un modèle, puis d'un écran. Ils
    méritent plutôt plus de méfiance que moins.
    """
    response = adopt(app_client, auth, deadline=(TODAY + timedelta(weeks=weeks)).isoformat())

    assert response.status_code == 422


def test_a_deadline_in_the_past_is_refused(app_client: TestClient, auth: dict[str, str]) -> None:
    """Un objectif se date devant soi : c'est la seconde colonne du projet à porter une
    date future, après `planning/plan.csv`."""
    response = adopt(app_client, auth, deadline=(TODAY - timedelta(days=2)).isoformat())

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("metric", "target"),
    [("weekly_sessions", 40), ("weight", 4), ("daily_protein_g", 4000), ("hydration", 90000)],
)
def test_a_target_outside_the_plausible_bounds_is_refused(
    app_client: TestClient, auth: dict[str, str], metric: str, target: float
) -> None:
    """Hors bornes, on refuse ; on ne ramène pas à la borne.

    Quarante séances par semaine rabotées à quatorze donneraient un objectif faux
    d'apparence honnête, et il resterait affiché six semaines.
    """
    assert adopt(app_client, auth, metric=metric, target=target).status_code == 422


def test_an_unmeasurable_metric_is_refused(app_client: TestClient, auth: dict[str, str]) -> None:
    """Rien ne mesure le sommeil dans Metric : un tel objectif afficherait un tiret
    jusqu'à son échéance."""
    response = adopt(app_client, auth, metric="sommeil")

    assert response.status_code == 422
    assert "sommeil" in response.json()["message"]


# ── 3. Garde anti-conflit ─────────────────────────────


def test_closing_without_the_header_is_a_conflict_not_a_permission(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    entry = adopted(app_client, auth)

    response = app_client.post(f"{GOALS}/{entry['id']}/close", headers=auth)

    assert response.status_code == 409
    assert ",active," in dav.content_of(GOALS_FILE)


def test_a_stale_token_leaves_the_file_untouched(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    entry = adopted(app_client, auth)
    before = dav.content_of(GOALS_FILE)

    response = app_client.post(
        f"{GOALS}/{entry['id']}/abandon", headers={**auth, "If-Match": "jeton-perime"}
    )

    assert response.status_code == 409
    assert dav.content_of(GOALS_FILE) == before


# ── 4. Un seul objectif à la fois (`GOAL-01`) ─────────


def test_a_second_goal_cannot_be_adopted_while_one_is_running(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """« Objectif unique » n'est pas une préférence d'affichage : deux objectifs à la fois,
    c'est aucun objectif."""
    adopted(app_client, auth)

    response = adopt(app_client, auth, title="Et courir 20 km", metric="weekly_distance_km")

    assert response.status_code == 409
    assert "déjà en cours" in response.json()["message"]


def test_a_goal_can_be_adopted_once_the_previous_one_is_closed(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    entry = adopted(app_client, auth)
    closed = app_client.post(
        f"{GOALS}/{entry['id']}/abandon", headers={**auth, "If-Match": entry["token"]}
    )
    assert closed.status_code == 200

    assert adopt(app_client, auth, metric="weekly_distance_km", target=20).status_code == 201


def test_closing_an_already_closed_goal_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    entry = adopted(app_client, auth)
    first = app_client.post(
        f"{GOALS}/{entry['id']}/abandon", headers={**auth, "If-Match": entry["token"]}
    ).json()

    again = app_client.post(
        f"{GOALS}/{entry['id']}/close", headers={**auth, "If-Match": first["token"]}
    )

    assert again.status_code == 409


# ── 5. Les trois états (`GOAL-05`) ────────────────────


def test_without_a_goal_the_state_says_so_and_invents_nothing(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    body = view(app_client, auth)

    assert body["state"] == "none"
    assert body["active"] is None
    assert body["history"] == []


def test_an_active_goal_comes_with_its_deadline_and_its_progress(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    adopted(app_client, auth)

    active = view(app_client, auth)["active"]

    assert active["days_left"] == 42
    assert active["expired"] is False
    assert active["progress"]["metric"] == "weekly_sessions"
    assert active["progress"]["target"] == 3


def test_an_expired_goal_stays_active_in_the_file_until_a_gesture_closes_it(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Une lecture n'écrit pas. Un `GET` qui clôturerait fausserait le cache autant que la
    promesse « rien sans validation » — et rendrait la clôture invisible."""
    dav.seed(
        GOALS_FILE,
        f"{GOALS_HEADER}\n"
        f"abc123,{(TODAY - timedelta(weeks=10)).isoformat()},Vieil objectif,weekly_sessions,"
        f"3,séances,{(TODAY - timedelta(days=3)).isoformat()},,ai,active,\n",
    )

    active = view(app_client, auth)["active"]

    assert active["expired"] is True
    assert active["days_left"] == -3
    assert active["goal"]["status"] == "active"
    assert ",active," in dav.content_of(GOALS_FILE)


# ── 6. Résultat final et historique (`GOAL-06`) ───────


def test_closing_a_goal_that_reached_its_target_records_it_as_reached(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le résultat est **calculé**, pas choisi : laisser l'écran cocher « atteint »
    reviendrait à laisser cocher « atteint » un objectif qui ne l'est pas.

    L'objectif est antidaté de cinq semaines et les séances sont postérieures : c'est le
    seul montage qui produit un vrai progrès, puisqu'un objectif adopté aujourd'hui part
    par construction de la valeur d'aujourd'hui.
    """
    monday = week_start(TODAY)
    # Quatre semaines révolues à quatre séances : la cadence dépasse la cible de trois.
    days = [monday - timedelta(weeks=week, days=day) for week in range(1, 5) for day in range(4)]
    seed_workouts(dav, days)
    dav.seed(
        GOALS_FILE,
        f"{GOALS_HEADER}\n"
        f"abc123,{(TODAY - timedelta(weeks=5)).isoformat()},Trois séances,weekly_sessions,"
        f"3,séances,{DEADLINE.isoformat()},,ai,active,\n",
    )

    entry = view(app_client, auth)["active"]["goal"]
    closed = app_client.post(
        f"{GOALS}/{entry['id']}/close", headers={**auth, "If-Match": entry["token"]}
    ).json()

    assert closed["outcome"] == "reached"
    assert closed["outcome_label"] == "atteint"


def test_a_target_below_the_starting_point_is_read_as_a_target_to_come_back_down_to() -> None:
    """Le coin qu'il faut connaître, et qu'aucun écran ne rend visible tout seul.

    La formule tire le **sens** de l'objectif de l'écart entre le point de départ et la
    cible : elle ne sait pas qu'une cadence est un plancher (« au moins trois séances »)
    là où un poids est une valeur (« descendre à 78 »). Se fixer trois séances alors qu'on
    en fait quatre se lit donc « redescendre à trois », et l'avancement vaut zéro tant
    qu'on reste à quatre.

    C'est assumé plutôt que corrigé : déclarer un sens par métrique ajouterait une donnée
    qui peut mentir, et le libellé chiffré — « 4 sur 3 séances » — dit déjà la situation
    sans ambiguïté. Le cas est de toute façon rare, la consigne demandant au modèle de
    partir de la valeur courante.
    """
    assert ratio(baseline=4, current=4, target=3) == 0.0


def test_closing_a_goal_short_of_its_target_records_it_as_partial(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    entry = adopted(app_client, auth, target=3)

    closed = app_client.post(
        f"{GOALS}/{entry['id']}/close", headers={**auth, "If-Match": entry["token"]}
    ).json()

    assert closed["outcome"] == "partial"


def test_an_abandoned_goal_is_not_a_partial_one(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """La distinction sert la génération suivante : « abandonné » dit qu'on n'en voulait
    plus, « partiel » qu'on n'y est pas arrivé."""
    entry = adopted(app_client, auth)

    closed = app_client.post(
        f"{GOALS}/{entry['id']}/abandon", headers={**auth, "If-Match": entry["token"]}
    ).json()

    assert closed["outcome"] == "abandoned"
    assert closed["outcome_label"] == "abandonné"


def test_closed_goals_move_to_the_history(app_client: TestClient, auth: dict[str, str]) -> None:
    entry = adopted(app_client, auth)
    app_client.post(f"{GOALS}/{entry['id']}/abandon", headers={**auth, "If-Match": entry["token"]})

    body = view(app_client, auth)

    assert body["state"] == "none"
    assert [item["outcome"] for item in body["history"]] == ["abandoned"]


# ── 7. `goals.csv` est un fichier de planning ─────────


def test_an_empty_cell_does_not_bring_the_screen_down(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le contrôle direct de la décision qui a coûté le tableau de bord entier au premier
    usage réel, sur `supplements/schedule.csv`."""
    dav.seed(
        GOALS_FILE,
        f"{GOALS_HEADER}\n"
        f"abc123,,Objectif sans date de création,weekly_sessions,3,,{DEADLINE.isoformat()},,,,\n",
    )

    body = view(app_client, auth)

    assert body["state"] == "active"
    assert body["active"]["goal"]["unit"] == "séances", "l'unité manquante se relit du registre"


def test_a_line_without_a_deadline_is_set_aside_but_survives_in_the_file(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """On ne saurait pas jusqu'à quand la tenir. On n'efface pas pour autant ce qu'on ne
    comprend pas."""
    raw = f"{GOALS_HEADER}\nabc123,,Objectif sans échéance,weekly_sessions,3,séances,,,ai,active,\n"
    dav.seed(GOALS_FILE, raw)

    assert view(app_client, auth)["state"] == "none"
    assert dav.content_of(GOALS_FILE) == raw


def test_a_line_whose_metric_is_unknown_is_set_aside(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Une ligne modifiée à la main peut désigner une métrique qui n'existe pas. L'écran
    n'a alors rien à mesurer — mieux vaut l'ignorer que d'afficher une cible creuse."""
    dav.seed(
        GOALS_FILE,
        f"{GOALS_HEADER}\nabc123,,Dormir plus,sommeil,8,h,{DEADLINE.isoformat()},,manual,active,\n",
    )

    assert view(app_client, auth)["state"] == "none"


def test_an_unreadable_status_falls_back_to_active(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le repli est `active` : une ligne qu'on a pris la peine d'écrire disparaîtrait
    silencieusement dans l'historique si le repli était `closed`."""
    dav.seed(
        GOALS_FILE,
        f"{GOALS_HEADER}\n"
        f"abc123,,Trois séances,weekly_sessions,3,séances,{DEADLINE.isoformat()},,ai,en cours,\n",
    )

    assert view(app_client, auth)["state"] == "active"


# ── 8. La progression, sans rien monter (`GOAL-04`) ───


def test_the_five_goal_metrics_all_exist_in_the_registry() -> None:
    """Garde structurelle. Une clé d'objectif absente du registre produirait un objectif
    adoptable et impossible à mesurer."""
    assert set(GOAL_METRICS) <= set(METRICS)
    assert len(GOAL_METRICS) == 5


def test_progress_is_measured_from_the_starting_point_not_from_zero() -> None:
    """`courant / cible` serait faux dès le premier objectif de poids : viser 78 kg quand
    on en pèse 82 donnerait 105 % d'avancement le jour de l'adoption."""
    assert ratio(baseline=82, current=80, target=78) == 0.5


def test_progress_works_the_same_upwards() -> None:
    """Une seule formule pour les cinq métriques, qu'elles doivent monter ou descendre."""
    assert ratio(baseline=1.8, current=2.4, target=3.0) == pytest.approx(0.5)


def test_progress_is_capped_at_the_target() -> None:
    """Au-delà, l'objectif est atteint. « 130 % » n'ajouterait rien."""
    assert ratio(baseline=1, current=9, target=3) == 1.0


def test_going_backwards_gives_zero_and_never_a_negative() -> None:
    """Un anneau qui se remplirait à l'envers ne se lirait pas."""
    assert ratio(baseline=82, current=85, target=78) == 0.0


def test_a_target_already_held_on_day_one_is_a_full_ring() -> None:
    """L'objectif ne demandait rien à parcourir. Le dire « à 0 % » serait faux dans
    l'autre sens."""
    assert ratio(baseline=3, current=3, target=3) == 1.0


def test_without_a_starting_point_progress_is_unknown_rather_than_zero() -> None:
    """« Aucune valeur inventée » : sans point de départ, « à mi-chemin » ne veut rien
    dire, et un zéro tiendrait lieu de mesure."""
    assert ratio(baseline=None, current=80, target=78) is None


def test_a_weekly_window_stops_at_last_sunday() -> None:
    """Compter le mardi en cours dans une moyenne hebdomadaire ferait ressembler chaque
    lundi matin à un effondrement."""
    start, end, periods = window("week", date(2026, 8, 5))  # un mercredi

    assert start == date(2026, 7, 6)
    assert end == date(2026, 8, 2)  # dimanche précédent
    assert periods == 4


def test_a_daily_window_stops_yesterday() -> None:
    start, end, periods = window("day", date(2026, 8, 5))

    assert (start, end, periods) == (date(2026, 7, 29), date(2026, 8, 4), 7)


def test_a_rate_divides_by_the_window_not_by_the_periods_that_carry_data() -> None:
    """Quatre semaines de repos suivies d'une semaine à six séances font 1,5 séance par
    semaine, pas six. C'est toute la différence entre compter et moyenner."""
    points = [(date(2026, 8, 3) - timedelta(weeks=1), 6.0)]

    value, _ = current_value(points, reduction="rate", granularity="week", as_of=date(2026, 8, 5))

    assert value == 1.5


def test_a_weighing_stays_the_current_weight_however_old_it_is() -> None:
    """Une pesée est une mesure : la dernière vaut, et sa date revient avec elle pour que
    l'écran puisse dire de quand elle date."""
    points = [(date(2026, 6, 1), 82.0), (date(2026, 7, 20), 80.5)]

    value, as_of = current_value(
        points, reduction="latest", granularity="day", as_of=date(2026, 8, 5)
    )

    assert (value, as_of) == (80.5, date(2026, 7, 20))


def test_a_metric_never_measured_yields_nothing_rather_than_zero() -> None:
    """Un poids jamais relevé n'est pas un poids de zéro kilo."""
    assert current_value([], reduction="latest", granularity="day", as_of=TODAY) == (None, None)


def test_a_cadence_never_recorded_is_a_real_zero() -> None:
    """N'avoir couru aucun kilomètre en quatre semaines est une information. C'est la
    limite exacte de « aucune valeur inventée » : une séance non faite se compte."""
    value, _ = current_value([], reduction="rate", granularity="week", as_of=TODAY)

    assert value == 0.0


def test_the_summary_reads_in_french_with_a_decimal_comma() -> None:
    """`GOAL-04` demande un « libellé chiffré ». Il s'affiche tel quel (`API-07`).

    Sans le nom de la métrique : l'écran l'affiche déjà au centre de l'anneau, et la
    première version — « 2,4 sur 3 séances · séances par semaine » — écrivait « séances »
    trois fois en une ligne, qui passait alors sur deux. Défaut trouvé en regardant la
    page, pas en la testant.
    """
    assert summary(2.4, 3, "séances") == "2,4 sur 3 séances"


def test_the_summary_of_an_unmeasured_metric_is_a_dash() -> None:
    assert summary(None, 78, "kg") == "— sur 78 kg"


# ── 9. La progression, de bout en bout ────────────────


def test_progress_on_real_sessions_uses_the_four_complete_weeks(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le point de départ et la valeur courante sortent du **même** calcul, et ce calcul
    est celui du registre — pas une seconde définition de « séances par semaine »."""
    monday = week_start(TODAY)
    seed_workouts(dav, [monday - timedelta(weeks=week) for week in range(1, 5)])
    adopted(app_client, auth, target=3)

    active = view(app_client, auth)["active"]

    # Une séance par semaine sur les quatre semaines révolues.
    assert active["progress"]["current"] == 1.0
    # Adopté aujourd'hui : le point de départ est la même fenêtre, donc le même chiffre.
    assert active["progress"]["baseline"] == 1.0
    assert active["progress"]["ratio"] == 0.0
    assert "4 dernières semaines complètes" in active["progress"]["basis"]


def test_a_weight_goal_progresses_downwards(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le cas qui justifie le point de départ : sans lui, viser 78 quand on pèse 82
    afficherait 105 %."""
    dav.seed(
        WEIGHT_FILE,
        "date,weight_kg,note,source\n"
        f"{(TODAY - timedelta(days=30)).isoformat()},82,,manual\n"
        f"{TODAY.isoformat()},80,,manual\n",
    )
    # Adopté aujourd'hui, le point de départ serait 80 : on antidate la ligne pour que le
    # départ soit la pesée d'il y a un mois, ce qui est le cas réel d'un objectif tenu.
    dav.seed(
        GOALS_FILE,
        f"{GOALS_HEADER}\n"
        f"abc123,{(TODAY - timedelta(days=30)).isoformat()},Descendre à 78,weight,78,kg,"
        f"{DEADLINE.isoformat()},,ai,active,\n",
    )

    progress = view(app_client, auth)["active"]["progress"]

    assert progress["baseline"] == 82
    assert progress["current"] == 80
    assert progress["ratio"] == 0.5
    assert progress["summary"].startswith("80 sur 78 kg")


def test_a_distance_goal_counts_kilometres_not_sessions(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    monday = week_start(TODAY)
    dav.seed(
        RUNS_FILE,
        "date,distance_km,duration_min,pace_min_km,avg_hr,elevation_m,note,source\n"
        + "".join(
            f"{(monday - timedelta(weeks=week)).isoformat()},10,50,,,,,manual\n"
            for week in range(1, 5)
        ),
    )

    adopted(app_client, auth, metric="weekly_distance_km", target=20, title="20 km par semaine")

    assert view(app_client, auth)["active"]["progress"]["current"] == 10.0


# ── 10. Sans clé, tout le domaine reste utilisable ────


def test_the_whole_goal_life_cycle_works_without_any_api_key(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """`IA-07` : l'IA est un confort, jamais un prérequis. Se fixer une cible à la main,
    l'adopter, lire sa progression et la clore n'interrogent aucun modèle."""
    entry = adopted(store_client, auth)

    assert view(store_client, auth)["active"]["progress"]["ratio"] is not None

    closed = store_client.post(
        f"{GOALS}/{entry['id']}/close", headers={**auth, "If-Match": entry["token"]}
    )
    assert closed.status_code == 200
    assert store_client.get(f"{GOALS}/weekly", headers=auth).status_code == 200


def test_the_weekly_history_is_empty_and_says_which_week_comes_next(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    body = store_client.get(f"{GOALS}/weekly", headers=auth).json()

    assert body["entries"] == []
    assert body["next_week"] == (week_start(TODAY) - timedelta(days=7)).isoformat()
    assert body["already_kept"] is False
    assert WEEKLY_FILE not in dav.files, "lire l'historique ne crée pas le fichier"


def test_a_goal_file_written_by_an_older_version_does_not_bring_the_screen_down(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le cas réel qui a rendu l'écran Objectif **et** l'assistant inaccessibles en `502`.

    Un `goals.csv` d'une version antérieure : dix colonnes au lieu de onze, un horodatage
    dans `created`, et une métrique qui n'existe plus. Les trois doivent être absorbés —
    c'est la promesse de la famille *planning*, et une valeur par défaut ne la tenait que
    pour les cellules **vides**.
    """
    dav.seed(
        GOALS_FILE,
        "id,created,title,metric,target,unit,deadline,rationale,source,status\n"
        "efba94f1,2026-07-10T16:26,Courir 3 fois 4 km par semaine,distance_hebdo,12,km/sem,"
        f"{DEADLINE.isoformat()},Une justification d'époque,ai,active\n",
    )

    body = view(app_client, auth)

    # La métrique n'existe plus : la ligne est écartée des vues, et survit dans le fichier.
    assert body["state"] == "none"
    assert "distance_hebdo" in dav.content_of(GOALS_FILE)


def test_a_timestamp_in_a_date_column_is_recovered_not_discarded(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le jour est écrit dans l'horodatage : le lire n'est pas l'inventer.

    Il compte, et pas qu'un peu — `created` est le **point de départ** de la progression
    (`GOAL-04`). Le mettre à `None` ferait repartir l'avancement d'aujourd'hui, c'est-à-dire
    de zéro, sur un objectif tenu depuis un mois.
    """
    dav.seed(
        GOALS_FILE,
        f"{GOALS_HEADER}\n"
        f"abc123,{(TODAY - timedelta(days=30)).isoformat()}T16:26,Trois séances,weekly_sessions,"
        f"3,séances,{DEADLINE.isoformat()},,ai,active,\n",
    )

    active = view(app_client, auth)["active"]

    assert active["goal"]["created"] == (TODAY - timedelta(days=30)).isoformat()


def test_an_unreadable_target_falls_back_to_zero_rather_than_raising(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """« Un nombre illisible » est une possibilité normale dans ce fichier (§2)."""
    dav.seed(
        GOALS_FILE,
        f"{GOALS_HEADER}\n"
        f"abc123,{TODAY.isoformat()},Trois séances,weekly_sessions,douze,séances,"
        f"{DEADLINE.isoformat()},,ai,active,\n",
    )

    assert view(app_client, auth)["active"]["progress"]["target"] == 0
