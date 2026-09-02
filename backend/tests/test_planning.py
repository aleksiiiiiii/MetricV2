"""Domaine Planning sport (`PLAN-01`, `PLAN-02`, `PLAN-04`, `PLAN-06`).

Les huit familles du patron de domaine, plus une neuvième qui n'existe que pour ce
lot-ci : `plan.csv` est un fichier de **planning**, pas de mesure. Une cellule vide y est
un cas normal, et la batterie doit le prouver colonne par colonne — c'est le défaut qui a
fait tomber le tableau de bord entier en `502` au premier usage réel, sur un fichier de la
même famille.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.dates import today_local
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

PLANNING = "/api/planning"
PLAN_FILE = "Metric/planning/plan.csv"
PLAN_HEADER = "id,date,time,kind,title,duration_min,note,source\n"
RUNS_FILE = "Metric/activity/runs.csv"
SESSIONS_FILE = "Metric/activity/circuit_sessions.csv"


@pytest.fixture
def app_client(client: TestClient, store: FileStore) -> TestClient:
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


def plan(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    """Planifie une séance et rend ce que l'API a renvoyé."""
    body = {
        "date": (today_local() + timedelta(days=1)).isoformat(),
        "time": "18:30",
        "kind": "muscu",
        "title": "Haut du corps",
        "duration_min": 60,
        **fields,
    }
    response = client.post(f"{PLANNING}/sessions", json=body, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


def write(dav: FakeWebDav, path: str, content: str) -> None:
    """Place un fichier tel qu'un tableur aurait pu l'écrire."""
    dav.seed(path, content)


def month_of(client: TestClient, auth: dict[str, str], month: str | None = None) -> Any:
    params = {"month": month} if month else {}
    response = client.get(f"{PLANNING}/month", params=params, headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def cell(view: Any, day: date) -> Any:
    return next(item for item in view["days"] if item["date"] == day.isoformat())


# ── 1. Écriture réelle dans le CSV ────────────────────


def test_a_planned_session_is_written_with_the_annex_columns(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Colonnes et ordre de l'annexe du backlog, accents et BOM compris."""
    plan(app_client, auth, note="Série longue, à l'aise")

    raw = dav.content_of(PLAN_FILE)
    header, line = raw.splitlines()[:2]

    assert header == PLAN_HEADER.strip()
    assert dav.files[PLAN_FILE].content.startswith(b"\xef\xbb\xbf")
    assert "Haut du corps" in line
    assert line.endswith(",manual")


def test_a_session_without_a_time_writes_an_empty_cell(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`PLAN-02` : l'heure est optionnelle, et le fichier doit le montrer tel quel."""
    session = plan(app_client, auth, time=None)

    assert session["time"] is None
    columns = dav.content_of(PLAN_FILE).splitlines()[1].split(",")
    assert columns[2] == ""


def test_an_empty_time_string_is_read_as_no_time(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Un formulaire HTML envoie `""` pour un champ non rempli.

    Le refuser au motif qu'il ne ressemble pas à `HH:MM` rendrait l'heure obligatoire par
    accident, alors que `PLAN-02` la dit facultative.
    """
    assert plan(app_client, auth, time="")["time"] is None


# ── 2. Bornes refusées ────────────────────────────────


def test_a_future_date_is_accepted(app_client: TestClient, auth: dict[str, str]) -> None:
    """Le planning est le **seul** domaine à porter des dates futures.

    Ce test existe pour attraper le jour où quelqu'un remplacerait `PlannedDate` par
    `PastDate` par symétrie avec les cinq autres domaines.
    """
    day = today_local() + timedelta(days=120)

    assert plan(app_client, auth, date=day.isoformat())["date"] == day.isoformat()


@pytest.mark.parametrize("offset", [500, -500])
def test_an_implausible_date_is_refused(
    app_client: TestClient, auth: dict[str, str], offset: int
) -> None:
    """Accepter l'avenir n'est pas accepter n'importe quoi : `2062` pour `2026` poserait
    une séance qu'aucun écran ne montre jamais et qui traînerait dans le flux iCal."""
    response = app_client.post(
        f"{PLANNING}/sessions",
        json={
            "date": (today_local() + timedelta(days=offset)).isoformat(),
            "kind": "muscu",
            "title": "X",
            "duration_min": 60,
        },
        headers=auth,
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [("duration_min", 0), ("duration_min", 2000), ("kind", "cardio"), ("title", "")],
)
def test_an_aberrant_field_is_refused(
    app_client: TestClient, auth: dict[str, str], field: str, value: Any
) -> None:
    response = app_client.post(
        f"{PLANNING}/sessions",
        json={
            "date": today_local().isoformat(),
            "kind": "muscu",
            "title": "Haut du corps",
            "duration_min": 60,
            field: value,
        },
        headers=auth,
    )

    assert response.status_code == 422


@pytest.mark.parametrize("moment", ["25:00", "8:00", "08:60", "matin"])
def test_a_malformed_time_is_refused(
    app_client: TestClient, auth: dict[str, str], moment: str
) -> None:
    """Facultative ne veut pas dire libre : vide ou `HH:MM`, rien entre les deux."""
    response = app_client.post(
        f"{PLANNING}/sessions",
        json={
            "date": today_local().isoformat(),
            "kind": "muscu",
            "title": "X",
            "duration_min": 60,
            "time": moment,
        },
        headers=auth,
    )

    assert response.status_code == 422


# ── 3. Garde anti-conflit ─────────────────────────────


def test_a_change_without_a_token_is_a_conflict(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Un `If-Match` absent est un conflit, jamais une permission (`STO-05`)."""
    session = plan(app_client, auth)
    before = dav.content_of(PLAN_FILE)

    response = app_client.patch(
        f"{PLANNING}/sessions/{session['id']}",
        json={
            "date": session["date"],
            "kind": "course",
            "title": "Sortie",
            "duration_min": 45,
        },
        headers=auth,
    )

    assert response.status_code == 409
    assert dav.content_of(PLAN_FILE) == before


def test_a_stale_token_leaves_the_file_untouched(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    session = plan(app_client, auth)
    before = dav.content_of(PLAN_FILE)

    response = app_client.delete(
        f"{PLANNING}/sessions/{session['id']}",
        headers={**auth, "If-Match": "jeton-perime"},
    )

    assert response.status_code == 409
    assert dav.content_of(PLAN_FILE) == before


def test_a_session_is_removed_with_its_token(app_client: TestClient, auth: dict[str, str]) -> None:
    session = plan(app_client, auth)

    response = app_client.delete(
        f"{PLANNING}/sessions/{session['id']}",
        headers={**auth, "If-Match": session["token"]},
    )

    assert response.status_code == 204
    assert month_of(app_client, auth)["days"]


# ── 4. Préservation de la provenance et de l'identité ──


def test_correcting_an_ai_session_keeps_its_source_and_id(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Déplacer une séance proposée d'un jour n'en fait pas une séance inventée.

    Et son identifiant survit : c'est l'`UID` du flux iCal, et le voir changer ferait
    apparaître un doublon dans un calendrier abonné.
    """
    day = today_local() + timedelta(days=2)
    created = app_client.post(
        f"{PLANNING}/proposal/adopt",
        json={
            "sessions": [
                {
                    "date": day.isoformat(),
                    "kind": "muscu",
                    "title": "Haut du corps",
                    "duration_min": 60,
                }
            ]
        },
        headers=auth,
    ).json()["created"][0]
    assert created["source"] == "ai"

    updated = app_client.patch(
        f"{PLANNING}/sessions/{created['id']}",
        json={
            "date": (day + timedelta(days=1)).isoformat(),
            "kind": "muscu",
            "title": "Haut du corps",
            "duration_min": 75,
        },
        headers={**auth, "If-Match": created["token"]},
    ).json()

    assert updated["source"] == "ai"
    assert updated["session_id"] == created["session_id"]
    assert updated["duration_min"] == 75


# ── 5. Calendrier mensuel (`PLAN-01`) ─────────────────


def test_the_month_grid_starts_on_a_monday_and_covers_full_weeks(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`PLAN-01` : semaine commençant le lundi, débordements compris.

    Le débordement est calculé par le serveur : le recomposer côté client serait une
    seconde implémentation de « la semaine commence le lundi » (`HEAT-30`).
    """
    view = month_of(app_client, auth, "2026-08")

    assert view["month"] == "2026-08-01"
    # Le 1er août 2026 est un samedi : la grille ouvre au lundi 27 juillet.
    assert view["start"] == "2026-07-27"
    assert view["end"] == "2026-09-06"
    assert len(view["days"]) % 7 == 0
    assert date.fromisoformat(view["start"]).weekday() == 0
    assert date.fromisoformat(view["end"]).weekday() == 6


def test_overflow_days_are_marked_out_of_month(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    view = month_of(app_client, auth, "2026-08")

    assert cell(view, date(2026, 7, 27))["in_month"] is False
    assert cell(view, date(2026, 8, 1))["in_month"] is True
    assert cell(view, date(2026, 9, 6))["in_month"] is False


def test_an_empty_month_answers_without_failing(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Historique vide : l'API répond, et aucune case ne porte de valeur inventée."""
    view = month_of(app_client, auth)

    assert view["today"] == today_local().isoformat()
    assert all(day["planned"] == [] and day["done"] == [] for day in view["days"])


def test_the_calendar_shows_planned_and_done_side_by_side(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`PLAN-01` : par jour, ce qui est prévu **et** ce qui a réellement eu lieu.

    Le réalisé est lu chez le domaine Activité, jamais recopié dans `plan.csv` : deux
    vérités sur ce qui s'est passé un mardi seraient une de trop.
    """
    day = today_local()
    write(
        dav,
        RUNS_FILE,
        "date,distance_km,duration_min,pace_min_km,avg_hr,elevation_m,note,source\n"
        f"{day.isoformat()},8.5,45,5.29,148,60,,manual\n",
    )
    plan(app_client, auth, date=day.isoformat(), kind="course", title="Sortie longue")

    today_cell = cell(month_of(app_client, auth, day.strftime("%Y-%m")), day)

    assert [item["title"] for item in today_cell["planned"]] == ["Sortie longue"]
    assert [item["kind"] for item in today_cell["done"]] == ["run"]
    assert today_cell["done"][0]["label"] == "8,50 km"


def test_sessions_of_a_day_are_ordered_by_time(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Une séance sans heure passe en tête plutôt que de se ranger au hasard."""
    day = today_local() + timedelta(days=3)
    plan(app_client, auth, date=day.isoformat(), time="19:00", title="Soir")
    plan(app_client, auth, date=day.isoformat(), time="07:00", title="Matin")
    plan(app_client, auth, date=day.isoformat(), time=None, title="Quand je peux")

    titles = [
        item["title"]
        for item in cell(month_of(app_client, auth, day.strftime("%Y-%m")), day)["planned"]
    ]

    assert titles == ["Quand je peux", "Matin", "Soir"]


# ── 6. Un fichier de planning ne fait jamais tomber un écran ──


def test_an_empty_time_cell_does_not_break_the_calendar(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le défaut exact qui a fait tomber le tableau de bord en `502` au premier usage réel.

    `plan.csv` est de la même famille que `supplements/schedule.csv`, et sa colonne `time`
    est facultative **par conception** : elle sera vide bien plus souvent qu'ailleurs.
    """
    day = today_local()
    write(
        dav, PLAN_FILE, PLAN_HEADER + f"abc123,{day.isoformat()},,muscu,Haut du corps,60,,manual\n"
    )

    session = cell(month_of(app_client, auth, day.strftime("%Y-%m")), day)["planned"][0]

    assert session["time"] is None
    assert session["title"] == "Haut du corps"


@pytest.mark.parametrize(
    "line",
    [
        # Toutes les colonnes facultatives vidées d'un coup.
        "abc123,{day},,,,,,",
        # Nature mal orthographiée dans un tableur.
        "abc123,{day},18:30,Muscu ,Haut du corps,60,,manual",
        "abc123,{day},18:30,cardio,Haut du corps,60,,manual",
        # Colonne `source` absente de la ligne — fichier antérieur à son ajout (`STO-04`).
        "abc123,{day},18:30,muscu,Haut du corps,60,",
    ],
)
def test_a_damaged_line_still_yields_a_readable_session(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav, line: str
) -> None:
    """Chaque colonne porte un défaut : la ligne se dégrade, l'écran tient."""
    day = today_local()
    write(dav, PLAN_FILE, PLAN_HEADER + line.format(day=day.isoformat()) + "\n")

    view = month_of(app_client, auth, day.strftime("%Y-%m"))
    session = cell(view, day)["planned"][0]

    assert session["kind"] in {"muscu", "autre"}
    assert session["source"] == "manual"


def test_a_line_without_an_id_or_a_date_survives_in_the_file(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Écartée des vues — on ne saurait ni quel jour l'afficher ni quelle ligne viser —
    mais conservée : on n'efface pas ce qu'on ne comprend pas."""
    day = today_local()
    write(
        dav,
        PLAN_FILE,
        PLAN_HEADER
        + ",2026-08-10,18:30,muscu,Sans identifiant,60,,manual\n"
        + "def456,,18:30,muscu,Sans date,60,,manual\n"
        + f"abc123,{day.isoformat()},18:30,muscu,Complète,60,,manual\n",
    )

    view = month_of(app_client, auth, day.strftime("%Y-%m"))
    plan(app_client, auth, date=day.isoformat(), title="Ajoutée")

    assert [item["title"] for item in cell(view, day)["planned"]] == ["Complète"]
    # Les deux lignes incomplètes sont toujours là après une écriture.
    raw = dav.content_of(PLAN_FILE)
    assert "Sans identifiant" in raw
    assert "Sans date" in raw


# ── 7. Adoption en une fois (`PLAN-04`) ───────────────


def test_adoption_writes_everything_in_a_single_request(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """« L'adoption enregistre le reste **en une fois** » — et une fois veut dire une.

    Huit `PUT` coûteraient plus d'une seconde à ~180 ms l'aller-retour, et laisseraient le
    fichier à moitié rempli si la coupure survient à la cinquième.
    """
    day = today_local() + timedelta(days=1)
    dav.reset_journal()

    response = app_client.post(
        f"{PLANNING}/proposal/adopt",
        json={
            "sessions": [
                {
                    "date": (day + timedelta(days=offset)).isoformat(),
                    "kind": "muscu",
                    "title": f"Séance {offset}",
                    "duration_min": 60,
                }
                for offset in range(4)
            ]
        },
        headers=auth,
    )

    assert response.status_code == 201
    created = response.json()["created"]
    assert len(created) == 4
    assert {item["source"] for item in created} == {"ai"}
    assert len({item["session_id"] for item in created}) == 4

    puts = [method for method, _ in dav.requests if method == "PUT"]
    assert len(puts) == 1


def test_adoption_refuses_an_empty_list(app_client: TestClient, auth: dict[str, str]) -> None:
    response = app_client.post(f"{PLANNING}/proposal/adopt", json={"sessions": []}, headers=auth)

    assert response.status_code == 422


# ── 8. Écart plan / réalisé (`PLAN-06`) ───────────────


def test_adherence_counts_a_planned_session_as_honoured_when_the_day_carries_activity(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    day = today_local()
    write(
        dav,
        SESSIONS_FILE,
        "session_id,circuit_id,date,name,rounds,duration_min,rpe,source\n"
        f"s1,c1,{day.isoformat()},Haut du corps,4,60,,cadence\n",
    )
    plan(app_client, auth, date=day.isoformat())

    view = app_client.get(f"{PLANNING}/adherence", params={"weeks": 1}, headers=auth).json()

    assert view["planned"] == 1
    assert view["honoured"] == 1
    assert view["rate"] == 1.0
    assert view["weeks"][0]["done"] == 1


def test_adherence_does_not_credit_a_session_on_another_day(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le rapprochement se fait **par jour**. Une sortie le mardi n'honore pas une séance
    prévue le jeudi : c'est le respect d'un rendez-vous qu'on mesure, pas un volume."""
    monday = today_local() - timedelta(days=today_local().weekday())
    write(
        dav,
        SESSIONS_FILE,
        "session_id,circuit_id,date,name,rounds,duration_min,rpe,source\n"
        f"s1,c1,{monday.isoformat()},Haut du corps,4,60,,cadence\n",
    )
    plan(app_client, auth, date=(monday + timedelta(days=2)).isoformat())

    view = app_client.get(f"{PLANNING}/adherence", params={"weeks": 1}, headers=auth).json()

    assert view["planned"] == 1
    assert view["weeks"][0]["done"] == 1
    assert view["honoured"] == 0
    assert view["rate"] == 0.0


def test_two_sessions_the_same_day_need_two_activities(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`min(prévu, réalisé)` par journée : une séance faite n'en honore pas deux."""
    day = today_local()
    write(
        dav,
        SESSIONS_FILE,
        "session_id,circuit_id,date,name,rounds,duration_min,rpe,source\n"
        f"s1,c1,{day.isoformat()},Haut du corps,4,60,,cadence\n",
    )
    plan(app_client, auth, date=day.isoformat(), time="08:00")
    plan(app_client, auth, date=day.isoformat(), time="19:00")

    view = app_client.get(f"{PLANNING}/adherence", params={"weeks": 1}, headers=auth).json()

    assert view["planned"] == 2
    assert view["honoured"] == 1
    assert view["rate"] == 0.5


def test_a_week_without_a_plan_has_no_rate_at_all(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Rien de prévu n'est pas 0 % de respect : c'est l'absence de taux.

    Un zéro ferait passer une semaine sans planning pour une semaine ratée — « aucune
    valeur inventée à l'écran », appliqué à un ratio.
    """
    view = app_client.get(f"{PLANNING}/adherence", params={"weeks": 4}, headers=auth).json()

    assert view["rate"] is None
    assert all(week["rate"] is None for week in view["weeks"])


def test_adherence_returns_one_row_per_week_ending_this_week(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    view = app_client.get(f"{PLANNING}/adherence", params={"weeks": 6}, headers=auth).json()

    weeks = [date.fromisoformat(week["week"]) for week in view["weeks"]]
    assert len(weeks) == 6
    assert all(day.weekday() == 0 for day in weeks)
    assert weeks == sorted(weeks)
    assert weeks[-1] == today_local() - timedelta(days=today_local().weekday())


def test_an_unreadable_date_or_duration_does_not_bring_the_month_down(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Même famille, même promesse que `goals.csv` — et le même défaut latent jusqu'au
    `502` réel de l'écran Objectif : un défaut de colonne ne couvre que la cellule
    **vide**, pas la cellule remplie de travers."""
    day = today_local()
    write(
        dav,
        PLAN_FILE,
        PLAN_HEADER
        + f"aaa,{day.isoformat()}T18:30,18:30,muscu,Horodatage dans la date,60,,manual\n"
        + f"bbb,{day.isoformat()},18:30,muscu,Durée illisible,une heure,,manual\n",
    )

    view = month_of(app_client, auth, day.strftime("%Y-%m"))
    planned = cell(view, day)["planned"]

    assert [item["title"] for item in planned] == ["Horodatage dans la date", "Durée illisible"]
    assert planned[1]["duration_min"] == 0
