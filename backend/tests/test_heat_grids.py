"""Grilles lues depuis les fichiers réels (`HEAT-24` → `HEAT-29`, `HEAT-32`).

Le moteur est éprouvé ailleurs, sur des dictionnaires. Ces tests-ci vérifient la
**couture** : que la configuration lue sur Nextcloud arrive intacte jusqu'à lui, et que
le résultat décrit bien les données de saisie.

Trois propriétés y sont vérifiées et nulle part ailleurs : le découpage en jours suit le
fuseau local (`HEAT-32`), la cadence versionnée du journal entre bien dans le calcul
(`HEAT-14`), et chaque cellule reste explorable (`HEAT-29`).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest

from app.core.dates import today_local, tz, week_start
from app.domains.heatmap.engine import DayState, Range, WeekStatus
from app.domains.heatmap.grids import GridService
from app.domains.heatmap.service import TrackService
from app.storage.files import FileStore
from tests.fake_webdav import FakeWebDav

TRACKS_FILE = "Metric/settings/heatmap_tracks.csv"
CADENCES_FILE = "Metric/settings/heatmap_cadences.csv"
OFF_FILE = "Metric/settings/heatmap_off_days.csv"

SESSION_SETS = "Metric/activity/circuit_session_sets.csv"
RUNS = "Metric/activity/runs.csv"
SESSIONS = "Metric/activity/circuit_sessions.csv"
HYDRATION = "Metric/hydration/intake_log.csv"
SUPPLEMENT_LOG = "Metric/supplements/intake_log.csv"

TRACK_HEADER = (
    "id,label,source,filter,validation_threshold,levels,binary,accent,position,active,created\n"
)


def moment(day: date, hour: int = 9, minute: int = 0) -> str:
    return (
        datetime.combine(day, datetime.min.time(), tzinfo=tz())
        .replace(hour=hour, minute=minute)
        .isoformat()
    )


def seed_track(dav: FakeWebDav, *lines: str) -> None:
    dav.seed(TRACKS_FILE, TRACK_HEADER + "".join(lines))


def water_track(created: date, *, threshold: int = 1500) -> str:
    return (
        f"eau,Eau,hydration.intake,,{threshold},1000;1500;2000;2500,false,signal,0,true,{created}\n"
    )


# ── Fuseau local (`HEAT-32`) ──────────────────────────


async def test_a_late_intake_belongs_to_the_day_the_clock_shows(
    store: FileStore, dav: FakeWebDav
) -> None:
    """**Le test qui compte le plus de ce fichier.**

    23 h 30 à Paris, c'est 21 h 30 UTC le même jour en été — mais en hiver, ou pour un
    fuseau négatif, un découpage en UTC ferait basculer la prise d'un jour, et la cellule
    verte apparaîtrait sur la mauvaise colonne.
    """
    today = today_local()
    seed_track(dav, water_track(today - timedelta(days=30)))
    dav.seed(
        HYDRATION,
        f"datetime,volume_ml,kind\n{moment(today, 23, 30)},1600,eau\n",
    )

    grid = (await GridService(store).grid("eau", window=Range(today, today))).grid

    assert grid.days[0].date == today
    assert grid.days[0].state is DayState.DONE


# ── Sources et seuils ─────────────────────────────────


async def test_a_water_grid_reads_the_hydration_log(store: FileStore, dav: FakeWebDav) -> None:
    today = today_local()
    seed_track(dav, water_track(today - timedelta(days=30)))
    dav.seed(
        HYDRATION,
        "datetime,volume_ml,kind\n"
        f"{moment(today - timedelta(days=2))},2600,eau\n"
        f"{moment(today - timedelta(days=1))},1200,eau\n",
    )

    grid = (
        await GridService(store).grid(
            "eau", window=Range(today - timedelta(days=2), today - timedelta(days=1))
        )
    ).grid

    assert grid.days[0].state is DayState.DONE
    assert grid.days[0].level == 4, "2,6 L dépasse la dernière borne"
    assert grid.days[1].state is DayState.MISSED, "1,2 L est sous le seuil de 1,5 L"
    assert grid.stats.total == 3800


async def test_a_muscle_grid_counts_sets_of_the_filtered_groups(
    store: FileStore, dav: FakeWebDav
) -> None:
    """Le filtre est une **valeur** du fichier, pas une constante du code : redécouper les
    pistes ne demande aucune modification."""
    today = today_local()
    seed_track(
        dav,
        f"torse,Torse,activity.muscle_group,pectoraux;épaules,1,1;3;6;10,false,effort,0,true,{today - timedelta(days=30)}\n",
    )
    dav.seed(
        SESSION_SETS,
        "session_id,date,exercise_name,muscle_group,sets,reps\n"
        f"s1,{today},Développé,pectoraux,4,8\n"
        f"s1,{today},Élévations,épaules,3,12\n"
        f"s1,{today},Squat,jambes,5,5\n",
    )

    grid = (await GridService(store).grid("torse", window=Range(today, today))).grid

    assert grid.days[0].value == 7, "les jambes ne comptent pas pour le torse"
    assert grid.days[0].level == 3, "sept séries : au-dessus de six, sous les dix"


# ── Cadence versionnée (`HEAT-14`) ────────────────────


async def test_the_journal_cadence_enters_the_calculation(
    store: FileStore, dav: FakeWebDav
) -> None:
    """La règle qui s'appliquait alors, pas celle d'aujourd'hui.

    L'eau était attendue un jour sur deux jusqu'à J-3, puis tous les jours. Les journées
    creuses d'avant doivent rester `off`, celles d'après passer `missed`.
    """
    today = today_local()
    seed_track(dav, water_track(today - timedelta(days=30)))
    dav.seed(
        CADENCES_FILE,
        "id,track_id,type,params,valid_from\n"
        f"c1,eau,window,min_count=1;window_days=2,{today - timedelta(days=30)}\n"
        f"c2,eau,daily,,{today - timedelta(days=3)}\n",
    )
    dav.seed(
        HYDRATION,
        "datetime,volume_ml,kind\n"
        f"{moment(today - timedelta(days=6))},2000,eau\n"
        f"{moment(today - timedelta(days=4))},2000,eau\n",
    )

    grid = (
        await GridService(store).grid(
            "eau", window=Range(today - timedelta(days=6), today - timedelta(days=1))
        )
    ).grid

    states = [day.state for day in grid.days]
    assert states[1] is DayState.OFF, "la fenêtre couvrait encore ce jour-là"
    assert states[3] is DayState.MISSED, "la règle quotidienne s'applique depuis J-3"
    assert states[5] is DayState.MISSED


# ── Jours neutralisés (`HEAT-06`) ─────────────────────


async def test_a_global_neutralisation_reaches_every_grid(
    store: FileStore, dav: FakeWebDav
) -> None:
    """`track_id` vide neutralise toutes les pistes : une semaine d'arrêt ne se déclare
    pas neuf fois."""
    today = today_local()
    seed_track(dav, water_track(today - timedelta(days=30)))
    dav.seed(
        OFF_FILE,
        "id,track_id,date_from,date_to,reason\n"
        f"o1,,{today - timedelta(days=5)},{today - timedelta(days=3)},grippe\n",
    )

    grid = (
        await GridService(store).grid(
            "eau", window=Range(today - timedelta(days=6), today - timedelta(days=1))
        )
    ).grid

    assert [day.state for day in grid.days[1:4]] == [DayState.OFF] * 3
    assert grid.days[0].state is DayState.MISSED


# ── Lecture groupée (`HEAT-25`) ───────────────────────


async def test_several_grids_share_one_range(store: FileStore, dav: FakeWebDav) -> None:
    today = today_local()
    seed_track(
        dav,
        water_track(today - timedelta(days=30)),
        f"course,Course,activity.runs,,1,1;3;6;10,false,signal,1,true,{today - timedelta(days=30)}\n",
    )

    grids = await GridService(store).grids(window=Range(today - timedelta(days=3), today))

    assert [item.track.id for item in grids] == ["eau", "course"]
    assert all(len(item.grid.days) == 4 for item in grids)


async def test_an_inactive_track_is_left_out(store: FileStore, dav: FakeWebDav) -> None:
    """`HEAT-21` : désactiver retire des vues sans rien perdre."""
    today = today_local()
    seed_track(
        dav,
        water_track(today - timedelta(days=30)),
        f"course,Course,activity.runs,,1,1;3;6;10,false,signal,1,false,{today - timedelta(days=30)}\n",
    )

    grids = await GridService(store).grids(window=Range(today, today))

    assert [item.track.id for item in grids] == ["eau"]


async def test_a_subset_can_be_asked_for(store: FileStore, dav: FakeWebDav) -> None:
    today = today_local()
    seed_track(
        dav,
        water_track(today - timedelta(days=30)),
        f"course,Course,activity.runs,,1,1;3;6;10,false,signal,1,true,{today - timedelta(days=30)}\n",
    )

    grids = await GridService(store).grids(["course"], window=Range(today, today))

    assert [item.track.id for item in grids] == ["course"]


async def test_each_source_file_is_pulled_once_for_the_whole_screen(
    store: FileStore, dav: FakeWebDav
) -> None:
    """`HEAT-33` en esprit : neuf grilles, ce sont neuf fois les mêmes fichiers. Le cache
    de `FileStore` les sert une seule fois, ce qui rend la lecture groupée réellement
    moins chère que neuf appels — pas seulement plus discrète.

    Le cache serveur des grilles lui-même arrive au lot L11 ; cette garde vérifie déjà que
    la couche du dessous ne martèle pas Nextcloud.
    """
    today = today_local()
    seed_track(
        dav,
        water_track(today - timedelta(days=30)),
        f"course,Course,activity.runs,,1,1;3;6;10,false,signal,1,true,{today - timedelta(days=30)}\n",
        f"eau2,Eau bis,hydration.intake,,1000,1000;1500;2000;2500,false,signal,2,true,{today - timedelta(days=30)}\n",
    )
    dav.seed(HYDRATION, f"datetime,volume_ml,kind\n{moment(today)},1600,eau\n")
    dav.reset_journal()

    await GridService(store).grids(window=Range(today - timedelta(days=30), today))

    fetched = [path for method, path in dav.requests if method == "GET"]
    assert sorted(fetched) == sorted(set(fetched)), "un fichier a été tiré deux fois"


# ── Détail d'un jour (`HEAT-29`) ──────────────────────


async def test_a_muscle_cell_lists_its_exercises(store: FileStore, dav: FakeWebDav) -> None:
    today = today_local()
    seed_track(
        dav,
        f"torse,Torse,activity.muscle_group,pectoraux,1,1;3;6;10,false,effort,0,true,{today}\n",
    )
    dav.seed(
        SESSION_SETS,
        "session_id,date,exercise_name,muscle_group,sets,reps\n"
        f"s1,{today},Développé couché,pectoraux,4,8\n"
        f"s1,{today},Squat,jambes,5,5\n",
    )

    detail = await GridService(store).day("torse", today)

    assert len(detail) == 1
    assert detail[0].label == "Développé couché"
    assert (detail[0].sets, detail[0].reps) == (4, 8)
    assert detail[0].unit == "série"
    # **Aucune charge** (**C4**) : `circuit_session_sets.csv` n'en porte pas, et remonter
    # celle de `circuit_loads.csv` l'annoncerait comme la charge de ce jour-là — ce
    # qu'elle n'est pas, puisqu'elle se corrige après coup.
    assert detail[0].weight_kg is None


async def test_a_run_cell_carries_distance_duration_and_pace(
    store: FileStore, dav: FakeWebDav
) -> None:
    """Des nombres, pas des phrases : c'est le client qui compose « 8,40 km en 44:12 »."""
    today = today_local()
    seed_track(dav, f"course,Course,activity.runs,,1,1;3;6;10,false,signal,0,true,{today}\n")
    dav.seed(
        RUNS,
        "date,distance_km,duration_min,pace_min_km,avg_hr,elevation_m,note,source\n"
        f"{today},8.4,44.2,5.262,,,,manual\n",
    )

    detail = await GridService(store).day("course", today)

    assert detail[0].distance_km == 8.4
    assert detail[0].duration_min == 44.2
    assert detail[0].pace_min_km == pytest.approx(5.262)


async def test_a_supplement_cell_carries_the_time_of_each_intake(
    store: FileStore, dav: FakeWebDav
) -> None:
    today = today_local()
    seed_track(dav, f"sup-s1,Créatine,supplement.intake,s1,1,,true,recover,0,true,{today}\n")
    dav.seed(
        SUPPLEMENT_LOG,
        "datetime,schedule_id,name,dose,unit\n"
        f"{moment(today, 8, 5)},s1,Créatine,5,g\n"
        f"{moment(today, 20, 0)},s2,Whey,30,g\n",
    )

    detail = await GridService(store).day("sup-s1", today)

    assert len(detail) == 1, "le filtre ne retient que le supplément de la piste"
    assert detail[0].dose == 5
    assert detail[0].dose_unit == "g"
    assert detail[0].time is not None and detail[0].time.hour == 8


async def test_an_hydration_cell_lists_its_intakes(store: FileStore, dav: FakeWebDav) -> None:
    today = today_local()
    seed_track(dav, water_track(today))
    dav.seed(
        HYDRATION,
        f"datetime,volume_ml,kind\n{moment(today, 8)},500,eau\n{moment(today, 14)},750,café\n",
    )

    detail = await GridService(store).day("eau", today)

    assert [item.value for item in detail] == [500, 750]
    assert [item.label for item in detail] == ["eau", "café"]


async def test_an_entry_count_cell_names_the_domains(store: FileStore, dav: FakeWebDav) -> None:
    today = today_local()
    seed_track(dav, f"suivi,Suivi,entry_count,,1,1;2;3;4,false,signal,0,true,{today}\n")
    dav.seed("Metric/body/weight.csv", f"date,weight_kg,note,source\n{today},72,,manual\n")
    dav.seed(HYDRATION, f"datetime,volume_ml,kind\n{moment(today)},1500,eau\n")

    detail = await GridService(store).day("suivi", today)

    assert {item.label for item in detail} == {"Poids", "Hydratation"}


async def test_a_source_without_detail_answers_empty(store: FileStore, dav: FakeWebDav) -> None:
    """Une source mal orthographiée ne doit pas faire tomber le tiroir de détail."""
    today = today_local()
    seed_track(dav, f"x,X,activity.telepathie,,1,,false,signal,0,true,{today}\n")

    assert await GridService(store).day("x", today) == []


# ── Cadence conditionnelle branchée sur l'activité (`HEAT-12`) ──


async def test_a_peri_workout_supplement_is_not_missed_on_a_rest_day(
    store: FileStore, dav: FakeWebDav
) -> None:
    """Le cas d'usage nommé par la spec. Sans cette cadence, un complément
    péri-entraînement serait rouge tous les jours de repos."""
    today = today_local()
    seed_track(
        dav,
        f"sup-s1,Whey,supplement.intake,s1,1,,true,recover,0,true,{today - timedelta(days=10)}\n",
    )
    dav.seed(
        CADENCES_FILE,
        "id,track_id,type,params,valid_from\n"
        f"c1,sup-s1,conditional,trigger=workout,{today - timedelta(days=10)}\n",
    )
    dav.seed(
        SESSIONS,
        "session_id,circuit_id,date,name,rounds,duration_min,rpe,source\n"
        f"s1,c1,{today - timedelta(days=3)},Haut du corps,4,60,,cadence\n",
    )

    grid = (
        await GridService(store).grid(
            "sup-s1", window=Range(today - timedelta(days=4), today - timedelta(days=1))
        )
    ).grid

    assert [day.state for day in grid.days] == [
        DayState.OFF,
        DayState.MISSED,  # jour de séance, whey non prise
        DayState.OFF,
        DayState.OFF,
    ]


# ── Statuts hebdomadaires bout en bout (`HEAT-28`) ────


async def test_a_weekly_track_reports_its_weeks(store: FileStore, dav: FakeWebDav) -> None:
    today = today_local()
    start = week_start(today) - timedelta(weeks=2)
    seed_track(
        dav,
        f"dos,Dos,activity.muscle_group,dos,1,1;3;6;10,false,effort,0,true,{start}\n",
    )
    dav.seed(
        CADENCES_FILE,
        f"id,track_id,type,params,valid_from\nc1,dos,per_week,count=2,{start}\n",
    )
    dav.seed(
        SESSION_SETS,
        "session_id,date,exercise_name,muscle_group,sets,reps\n"
        f"s1,{start},Tractions,dos,4,8\n"
        f"s2,{start + timedelta(days=2)},Tractions,dos,4,8\n",
    )

    grid = (
        await GridService(store).grid(
            "dos", window=Range(start, week_start(today) - timedelta(days=1))
        )
    ).grid

    assert grid.weeks is not None
    statuses = {week.week_start: week.status for week in grid.weeks}
    assert statuses[start] is WeekStatus.REACHED
    assert statuses[start + timedelta(weeks=1)] is WeekStatus.MISSED
    assert DayState.MISSED not in {day.state for day in grid.days}


# ── Robustesse ────────────────────────────────────────


async def test_an_unknown_track_is_refused(store: FileStore, dav: FakeWebDav) -> None:
    from app.storage.errors import StorageNotFoundError

    seed_track(dav, water_track(today_local()))

    with pytest.raises(StorageNotFoundError):
        await GridService(store).grid("telepathie")


async def test_a_track_with_an_unknown_source_yields_an_empty_grid(
    store: FileStore, dav: FakeWebDav
) -> None:
    """Une piste abîmée coûte sa propre grille, pas l'écran entier."""
    today = today_local()
    seed_track(
        dav, f"x,X,activity.telepathie,,1,,false,signal,0,true,{today - timedelta(days=5)}\n"
    )

    grid = (await GridService(store).grid("x", window=Range(today - timedelta(days=2), today))).grid

    assert len(grid.days) == 3
    assert all(day.value == 0 for day in grid.days)


async def test_the_default_range_covers_a_full_year_of_columns(
    store: FileStore, dav: FakeWebDav
) -> None:
    seed_track(dav, water_track(today_local()))

    grid = (await GridService(store).grid("eau")).grid

    assert len(grid.days) == 371
    assert grid.range.start.weekday() == 0
    assert grid.range.end.weekday() == 6


async def test_the_seeded_tracks_all_produce_a_grid(store: FileStore, dav: FakeWebDav) -> None:
    """Garde d'ensemble : les pistes amorcées au lot L09 doivent toutes être calculables
    par le moteur du lot L10. Une piste par défaut qui ne rendrait pas de grille serait
    une régression invisible autrement."""
    dav.seed(
        "Metric/supplements/schedule.csv",
        "id,name,dose,unit,time,frequency,active,created\n"
        "s1,Créatine,5,g,08:00,daily,true,2026-01-01\n",
    )
    seeded = await TrackService(store).ensure_seeded()

    grids = await GridService(store).grids()

    assert len(grids) == len(seeded) == 8  # 5 groupes + course + eau + 1 supplément
    assert all(len(item.grid.days) == 371 for item in grids)


def test_today_is_read_in_the_local_timezone() -> None:
    """`HEAT-32` : le jour courant du moteur est celui de l'horloge, pas celui d'UTC."""
    assert today_local() == datetime.now(tz=tz()).date()


@pytest.fixture(autouse=True)
def _known_collections(store: FileStore) -> Any:
    """Le double WebDAV du dépôt connaît déjà les dossiers écrits par l'amorçage."""
    store._known_collections.add("settings")
    return None
