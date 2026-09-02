"""Modèle de piste et cycle de vie (spec `HEAT` v2, lot L09).

Le lot ne calcule aucun état : il pose ce qui les paramètre. Les tests portent donc sur
les propriétés que le moteur du lot suivant devra pouvoir tenir pour acquises —
non-rétroactivité d'une piste, cadence retrouvable à une date passée, données sources
intactes après une suppression.

Trois d'entre eux comptent plus que les autres :

* une cadence changée aujourd'hui ne réécrit pas le verdict d'hier (`HEAT-14`) ;
* supprimer une piste n'efface aucune mesure (`HEAT-21`) ;
* les cadences d'amorçage viennent de la **fréquence réelle** et non d'une constante
  (décision **D9**) — une grille rouge dès le premier jour est une grille qu'on cesse de
  regarder.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.dates import today_local, tz
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

TRACKS = "/api/heatmap/tracks"
OFF_DAYS = "/api/heatmap/off-days"

TRACKS_FILE = "Metric/settings/heatmap_tracks.csv"
CADENCES_FILE = "Metric/settings/heatmap_cadences.csv"
OFF_FILE = "Metric/settings/heatmap_off_days.csv"

SESSION_SETS = "Metric/activity/circuit_session_sets.csv"
RUNS = "Metric/activity/runs.csv"
SCHEDULE = "Metric/supplements/schedule.csv"
SUPPLEMENT_LOG = "Metric/supplements/intake_log.csv"
HYDRATION = "Metric/hydration/intake_log.csv"


@pytest.fixture
def app_client(client: TestClient, store: FileStore) -> TestClient:
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


def moment(day: Any, hour: int = 9) -> str:
    return datetime.combine(day, datetime.min.time(), tzinfo=tz()).replace(hour=hour).isoformat()


def read(client: TestClient, auth: dict[str, str]) -> Any:
    response = client.get(TRACKS, headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def by_id(client: TestClient, auth: dict[str, str]) -> dict[str, Any]:
    return {track["track_id"]: track for track in read(client, auth)["tracks"]}


def payload(**overrides: Any) -> dict[str, Any]:
    return {
        "label": "Gainage",
        "source": "activity.muscle_group",
        "filter": "abdos",
        "validation_threshold": 1,
        "levels": [1, 3, 6, 10],
        "cadence": "per_week:count=3",
        **overrides,
    }


@pytest.fixture
def supplements(dav: FakeWebDav) -> None:
    """Deux compléments au planning, avec des cadences différentes."""
    dav.seed(
        SCHEDULE,
        "id,name,dose,unit,time,frequency,active,created\n"
        "s1,Créatine,5,g,08:00,daily,true,2026-01-01\n"
        "s2,Whey,30,g,12:30,window:min_count=1;window_days=2,true,2026-01-01\n",
    )


# ── Amorçage (`heat_backlog` §5, décisions D7 / D9 / D10 / D11) ──


def test_the_default_tracks_appear_on_first_read(
    app_client: TestClient, auth: dict[str, str], supplements: None
) -> None:
    """Ouvrir l'écran pour la première fois doit montrer des grilles peuplées de son
    propre historique, pas un formulaire de création vide."""
    del supplements
    tracks = by_id(app_client, auth)

    assert set(tracks) == {
        "torse",
        "dos",
        "bras",
        "jambes",
        "abdos",
        "course",
        "eau",
        "sup-s1",
        "sup-s2",
    }


def test_seeding_is_idempotent(app_client: TestClient, auth: dict[str, str]) -> None:
    """Un fichier non vide est laissé tel quel — y compris s'il ne contient qu'une piste
    que l'utilisateur a gardée après en avoir supprimé sept."""
    first = read(app_client, auth)["tracks"]
    second = read(app_client, auth)["tracks"]

    assert [track["track_id"] for track in first] == [track["track_id"] for track in second]


def test_the_muscle_mapping_lives_in_the_configuration(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Le regroupement des neuf groupes de `ACT-06` en cinq pistes est une **valeur**,
    dans la colonne `filter` — pas une constante du moteur."""
    tracks = by_id(app_client, auth)

    assert tracks["torse"]["filter"] == "pectoraux;épaules"
    assert tracks["bras"]["filter"] == "biceps;triceps"
    assert tracks["jambes"]["filter"] == "jambes;fessiers"


def test_the_other_group_is_deliberately_unmapped(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Décision **D7** : « autre » ne doit polluer aucune piste. L'utilisateur peut l'y
    rattacher lui-même, le mapping étant une configuration."""
    filters = " ".join(track["filter"] for track in read(app_client, auth)["tracks"])

    assert "autre" not in filters


def test_the_weekly_cadence_comes_from_the_real_frequency(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Décision **D9**. Amorcer à « 2 fois par semaine » pour cinq groupes supposerait dix
    créneaux hebdomadaires, ce qui est beaucoup quand on court aussi. Une piste doit
    décrire un engagement tenable."""
    today = today_local()
    # Douze séances de dos en quatre semaines : trois fois par semaine.
    lines = [
        f"s{offset},{today - timedelta(days=offset * 2)},Tractions,dos,4,8" for offset in range(12)
    ]
    dav.seed(
        SESSION_SETS,
        "session_id,date,exercise_name,muscle_group,sets,reps\n" + "\n".join(lines) + "\n",
    )

    tracks = by_id(app_client, auth)

    assert tracks["dos"]["cadence"]["type"] == "per_week"
    assert tracks["dos"]["cadence"]["params"]["count"] == 3
    assert tracks["dos"]["cadence"]["label"] == "3 fois par semaine"


def test_without_history_the_cadence_starts_at_once_a_week(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Il est plus facile de monter une exigence que de se réconcilier avec une grille
    rouge."""
    assert by_id(app_client, auth)["torse"]["cadence"]["params"]["count"] == 1


def test_the_water_track_validates_at_fifteen_hundred(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Décision **D10**. À un litre, le vert validait des journées à la moitié de
    l'objectif et ne voulait plus rien dire. Le gradient, lui, est inchangé."""
    eau = by_id(app_client, auth)["eau"]

    assert eau["validation_threshold"] == 1500
    assert eau["levels"] == [1000, 1500, 2000, 2500]
    assert eau["cadence"]["type"] == "daily"


def test_a_supplement_gets_its_own_track_and_its_own_cadence(
    app_client: TestClient, auth: dict[str, str], supplements: None
) -> None:
    """`HEAT-18`, `HEAT-23`. La spec cite « créatine » et « whey » en exemple ; les coder
    en dur donnerait deux grilles vides à qui prend autre chose."""
    del supplements
    tracks = by_id(app_client, auth)

    assert tracks["sup-s1"]["label"] == "Créatine"
    assert tracks["sup-s1"]["cadence"]["label"] == "tous les jours"
    assert tracks["sup-s2"]["label"] == "Whey"
    assert tracks["sup-s2"]["cadence"]["label"] == "un jour sur deux"


def test_supplements_are_binary_by_default(
    app_client: TestClient, auth: dict[str, str], supplements: None
) -> None:
    """Décision **D11** : une prise est une prise. Le mode gradué reste supporté, il
    suffit de renseigner deux seuils."""
    del supplements
    whey = by_id(app_client, auth)["sup-s2"]

    assert whey["binary"] is True
    assert whey["levels"] == []


def test_the_seeded_files_stay_readable_in_a_spreadsheet(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`STO-02`. Le point-virgule sépare les listes internes : la cellule n'a pas besoin
    d'être protégée par des guillemets et se lit à l'œil."""
    read(app_client, auth)

    tracks = dav.content_of(TRACKS_FILE)
    cadences = dav.content_of(CADENCES_FILE)

    assert tracks.startswith(
        "id,label,source,filter,validation_threshold,levels,binary,accent,position,active,created\n"
    )
    assert "pectoraux;épaules" in tracks
    assert "1;3;6;10" in tracks
    assert cadences.startswith("id,track_id,type,params,valid_from\n")


# ── Sources (`HEAT-02`, `HEAT-03`) ────────────────────


def test_the_source_catalogue_is_published(app_client: TestClient, auth: dict[str, str]) -> None:
    """L'écran de création n'en code aucune : ajouter une source au serveur la rend
    choisissable sans toucher au client."""
    sources = {entry["key"]: entry for entry in read(app_client, auth)["sources"]}

    assert set(sources) == {
        "activity.muscle_group",
        "activity.runs",
        "activity.duration",
        "supplement.intake",
        "hydration.intake",
        "entry_count",
    }
    assert sources["activity.muscle_group"]["filter_label"] == "Groupes musculaires"
    assert sources["hydration.intake"]["filter_label"] is None
    assert sources["hydration.intake"]["unit"] == "ml"


@pytest.mark.parametrize(
    ("source", "filter_", "expected"),
    [
        ("activity.muscle_group", "dos", 4.0),  # séries
        ("activity.runs", "", 8.4),  # kilomètres
        ("activity.duration", "", 44.2),  # minutes
        ("supplement.intake", "s1", 1.0),  # prises
        ("hydration.intake", "", 1500.0),  # millilitres
    ],
)
async def test_each_source_reduces_a_day_to_one_number(
    store: FileStore, dav: FakeWebDav, source: str, filter_: str, expected: float
) -> None:
    """`HEAT-03` : c'est le seul contrat entre une source et le moteur. Tout le reste —
    validation, cadence, intensité — ne travaille que sur ce nombre."""
    from app.domains.heatmap.sources import daily_values

    today = today_local()
    dav.seed(
        SESSION_SETS,
        f"session_id,date,exercise_name,muscle_group,sets,reps\ns1,{today},Tractions,dos,4,8\n",
    )
    dav.seed(
        RUNS,
        "date,distance_km,duration_min,pace_min_km,avg_hr,elevation_m,note,source\n"
        f"{today},8.4,44.2,5.26,,,,manual\n",
    )
    dav.seed(
        SUPPLEMENT_LOG, f"datetime,schedule_id,name,dose,unit\n{moment(today)},s1,Créatine,5,g\n"
    )
    dav.seed(HYDRATION, f"datetime,volume_ml,kind\n{moment(today)},1500,eau\n")

    values = await daily_values(store, source, filter_)

    assert values[today] == pytest.approx(expected)


async def test_an_unknown_source_yields_an_empty_series(store: FileStore) -> None:
    """Le fichier des pistes est éditable à la main : une source mal orthographiée doit
    rendre une grille vide, pas faire tomber l'écran avec les huit autres pistes."""
    from app.domains.heatmap.sources import daily_values

    assert await daily_values(store, "activity.telepathie", "") == {}


async def test_the_entry_count_source_reuses_the_streak_definition(
    store: FileStore, dav: FakeWebDav
) -> None:
    """Deux définitions de « un domaine a été renseigné » donneraient deux grilles pour la
    même semaine."""
    from app.domains.heatmap.sources import daily_values

    today = today_local()
    dav.seed("Metric/body/weight.csv", f"date,weight_kg,note,source\n{today},72,,manual\n")
    dav.seed(HYDRATION, f"datetime,volume_ml,kind\n{moment(today)},1500,eau\n")

    assert (await daily_values(store, "entry_count", ""))[today] == 2.0


# ── Création (`HEAT-18`, `HEAT-07`) ───────────────────


def test_a_track_can_be_created_without_touching_any_code(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    read(app_client, auth)
    response = app_client.post(TRACKS, json=payload(), headers=auth)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["label"] == "Gainage"
    assert body["cadence"]["label"] == "3 fois par semaine"
    assert body["source_label"] == "Séries d'un groupe musculaire"
    assert body["unit"] == "série"


def test_a_new_track_is_not_retroactive(app_client: TestClient, auth: dict[str, str]) -> None:
    """`HEAT-07` : ajouter la créatine aujourd'hui ne rend pas rouges les six mois
    précédents. La date de création est portée par la piste et immuable."""
    read(app_client, auth)
    created = app_client.post(TRACKS, json=payload(), headers=auth).json()

    assert created["created"] == today_local().isoformat()


def test_a_new_track_goes_last(app_client: TestClient, auth: dict[str, str]) -> None:
    """L'ordre est un réglage, pas une surprise."""
    before = read(app_client, auth)["tracks"]
    created = app_client.post(TRACKS, json=payload(), headers=auth).json()

    assert created["position"] > max(track["position"] for track in before)


@pytest.mark.parametrize(
    "field_and_value",
    [
        {"cadence": "hebdomadaire"},
        {"cadence": "window:min_count=3;window_days=2"},
        {"cadence": "per_week:count=9"},
        {"accent": "fuchsia"},
        {"levels": [1, 6, 3, 10]},
        {"levels": [1, 1, 3, 6]},
        {"label": ""},
    ],
)
def test_an_incoherent_track_is_refused_at_entry(
    app_client: TestClient, auth: dict[str, str], field_and_value: dict[str, Any]
) -> None:
    """Une cadence illisible enregistrée aujourd'hui se découvrirait dans six mois, au
    moment de juger un historique — trop tard pour savoir ce qui était voulu."""
    read(app_client, auth)
    response = app_client.post(TRACKS, json=payload(**field_and_value), headers=auth)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# ── Cadences versionnées (`HEAT-14`, `HEAT-19`) ───────


def test_changing_a_cadence_does_not_rewrite_the_past(
    app_client: TestClient, auth: dict[str, str], store: FileStore, dav: FakeWebDav
) -> None:
    """**Le test central du lot.**

    Passer la whey d'un jour sur deux à un jour sur trois aujourd'hui ne doit pas réécrire
    le verdict des mois passés : le moteur du lot L10 lira la règle qui s'appliquait
    alors.
    """
    import anyio

    from app.domains.heatmap.service import TrackService

    dav.seed(
        TRACKS_FILE,
        "id,label,source,filter,validation_threshold,levels,binary,accent,position,active,created\n"
        "eau,Eau,hydration.intake,,1500,1000;1500;2000;2500,false,signal,0,true,2026-01-15\n",
    )
    dav.seed(
        CADENCES_FILE,
        "id,track_id,type,params,valid_from\nc1,eau,daily,,2026-01-15\n",
    )
    eau = by_id(app_client, auth)["eau"]

    response = app_client.patch(
        f"{TRACKS}/eau",
        json=payload(
            label="Eau",
            source="hydration.intake",
            filter="",
            validation_threshold=1500,
            levels=[1000, 1500, 2000, 2500],
            cadence="window:min_count=5;window_days=7",
        ),
        headers={**auth, "If-Match": eau["token"]},
    )
    assert response.status_code == 200, response.text

    async def cadences() -> tuple[str, str]:
        service = TrackService(store)
        past = await service.cadence_at("eau", date(2026, 3, 1))
        now = await service.cadence_at("eau", today_local())
        return past.describe(), now.describe()

    before, after = anyio.run(cadences)

    assert before == "tous les jours", "le mois de mars garde la règle de mars"
    assert after == "5 fois par 7 jours"


def test_the_cadence_journal_only_ever_grows(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Journal en ajout seul (décision **D3**) : on n'y remplace jamais une ligne, même
    pour corriger celle du jour."""
    eau = by_id(app_client, auth)["eau"]
    lines_before = len(dav.content_of(CADENCES_FILE).strip().splitlines())

    app_client.patch(
        f"{TRACKS}/eau",
        json=payload(label="Eau", source="hydration.intake", filter="", cadence="per_week:count=5"),
        headers={**auth, "If-Match": eau["token"]},
    )

    after = dav.content_of(CADENCES_FILE).strip().splitlines()
    assert len(after) == lines_before + 1


def test_an_unchanged_cadence_adds_no_entry(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Réenregistrer un libellé ne doit pas faire croire à un changement d'engagement."""
    eau = by_id(app_client, auth)["eau"]
    lines_before = len(dav.content_of(CADENCES_FILE).strip().splitlines())

    app_client.patch(
        f"{TRACKS}/eau",
        json=payload(
            label="Hydratation",
            source="hydration.intake",
            filter="",
            validation_threshold=1500,
            levels=[1000, 1500, 2000, 2500],
            cadence="daily",
        ),
        headers={**auth, "If-Match": eau["token"]},
    )

    after = dav.content_of(CADENCES_FILE).strip().splitlines()
    assert len(after) == lines_before


def test_a_supplement_cadence_follows_the_schedule(
    app_client: TestClient,
    auth: dict[str, str],
    dav: FakeWebDav,
    store: FileStore,
    supplements: None,
) -> None:
    """Décision **D3** : `schedule.frequency` est la valeur courante. Un seul endroit
    décrit « je prends de la whey un jour sur deux »."""
    del supplements
    assert by_id(app_client, auth)["sup-s2"]["cadence"]["label"] == "un jour sur deux"

    dav.seed(
        SCHEDULE,
        "id,name,dose,unit,time,frequency,active,created\n"
        "s1,Créatine,5,g,08:00,daily,true,2026-01-01\n"
        "s2,Whey,30,g,12:30,per_week:count=4,true,2026-01-01\n",
    )
    # Le planning vient d'être modifié en dehors de l'application : le cache le sert
    # encore pendant son TTL (`STO-06`). On se place après.
    store.cache.clear()

    assert by_id(app_client, auth)["sup-s2"]["cadence"]["label"] == "4 fois par semaine"


def test_a_schedule_edited_by_hand_still_reaches_the_journal(
    app_client: TestClient,
    auth: dict[str, str],
    dav: FakeWebDav,
    store: FileStore,
    supplements: None,
) -> None:
    """Le planning est modifiable depuis l'écran Routine **et dans un tableur**.

    Brancher un déclencheur sur la seule écriture de l'application laisserait le journal
    muet dans le second cas, et le moteur jugerait le passé avec une cadence périmée. La
    réconciliation vit donc à la lecture.
    """
    del supplements
    read(app_client, auth)
    before = len(dav.content_of(CADENCES_FILE).strip().splitlines())

    dav.seed(
        SCHEDULE,
        "id,name,dose,unit,time,frequency,active,created\n"
        "s1,Créatine,5,g,08:00,daily,true,2026-01-01\n"
        "s2,Whey,30,g,12:30,per_week:count=4,true,2026-01-01\n",
    )
    store.cache.clear()  # comme après le TTL : la modification externe devient visible
    read(app_client, auth)

    after = dav.content_of(CADENCES_FILE).strip().splitlines()
    assert len(after) == before + 1
    assert "per_week" in after[-1]


def test_reading_twice_does_not_journal_twice(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav, supplements: None
) -> None:
    """La réconciliation n'écrit que lorsqu'un écart existe réellement."""
    del supplements
    read(app_client, auth)
    first = dav.content_of(CADENCES_FILE)
    read(app_client, auth)

    assert dav.content_of(CADENCES_FILE) == first


# ── Seuils rétroactifs (`HEAT-20`) ────────────────────


def test_changing_a_threshold_announces_the_recalculation(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`HEAT-20`. Un seuil dit ce que « validé » signifie, et cette signification n'a pas
    de version : tout l'historique est rejugé. Il ne suffit pas de l'appliquer — il faut
    le dire."""
    eau = by_id(app_client, auth)["eau"]

    body = app_client.patch(
        f"{TRACKS}/eau",
        json=payload(
            label="Eau",
            source="hydration.intake",
            filter="",
            validation_threshold=1000,
            levels=[1000, 1500, 2000, 2500],
            cadence="daily",
        ),
        headers={**auth, "If-Match": eau["token"]},
    ).json()

    assert body["recalculated_history"] is True
    assert any("rejugé" in warning for warning in body["warnings"])


def test_changing_only_the_cadence_is_not_retroactive(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """L'asymétrie assumée du lot : une cadence est un engagement daté."""
    eau = by_id(app_client, auth)["eau"]

    body = app_client.patch(
        f"{TRACKS}/eau",
        json=payload(
            label="Eau",
            source="hydration.intake",
            filter="",
            validation_threshold=1500,
            levels=[1000, 1500, 2000, 2500],
            cadence="per_week:count=5",
        ),
        headers={**auth, "If-Match": eau["token"]},
    ).json()

    assert body["recalculated_history"] is False
    assert any("à partir d'aujourd'hui" in warning for warning in body["warnings"])


def test_a_change_without_the_token_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    read(app_client, auth)
    response = app_client.patch(f"{TRACKS}/eau", json=payload(), headers=auth)

    assert response.status_code == 409
    assert by_id(app_client, auth)["eau"]["label"] == "Eau"


def test_the_creation_date_survives_a_modification(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Immuable, sinon la non-rétroactivité se réinitialiserait à chaque correction."""
    dav.seed(
        TRACKS_FILE,
        "id,label,source,filter,validation_threshold,levels,binary,accent,position,active,created\n"
        "eau,Eau,hydration.intake,,1500,1000;1500;2000;2500,false,signal,0,true,2026-01-15\n",
    )
    eau = by_id(app_client, auth)["eau"]

    body = app_client.patch(
        f"{TRACKS}/eau",
        json=payload(label="Hydratation", source="hydration.intake", filter=""),
        headers={**auth, "If-Match": eau["token"]},
    ).json()

    assert body["track"]["created"] == "2026-01-15"


# ── Désactivation et suppression (`HEAT-21`) ──────────


def test_deleting_a_track_never_erases_a_measurement(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`HEAT-21`. Une piste n'est qu'une lecture posée par-dessus les données ; la défaire
    ne défait pas ce qui a été fait."""
    today = today_local()
    dav.seed(HYDRATION, f"datetime,volume_ml,kind\n{moment(today)},1500,eau\n")
    eau = by_id(app_client, auth)["eau"]

    response = app_client.delete(f"{TRACKS}/eau", headers={**auth, "If-Match": eau["token"]})

    assert response.status_code == 204
    assert "eau" not in by_id(app_client, auth)
    assert "1500" in dav.content_of(HYDRATION)


def test_deleting_a_track_takes_its_cadence_history_with_it(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """L'historique de cadences n'a plus d'objet sans sa piste ; le laisser ferait grossir
    un fichier de configuration sans que rien ne le relise jamais."""
    eau = by_id(app_client, auth)["eau"]
    app_client.delete(f"{TRACKS}/eau", headers={**auth, "If-Match": eau["token"]})

    assert ",eau," not in dav.content_of(CADENCES_FILE)


def test_deactivating_keeps_the_track_and_its_history(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """La voie normale pour cesser d'afficher une grille sans rien perdre."""
    eau = by_id(app_client, auth)["eau"]

    app_client.patch(
        f"{TRACKS}/eau",
        json=payload(label="Eau", source="hydration.intake", filter="", active=False),
        headers={**auth, "If-Match": eau["token"]},
    )

    stored = by_id(app_client, auth)["eau"]
    assert stored["active"] is False
    assert stored["created"] is not None


def test_deleting_without_the_token_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    read(app_client, auth)

    assert app_client.delete(f"{TRACKS}/eau", headers=auth).status_code == 409
    assert "eau" in by_id(app_client, auth)


def test_an_unknown_track_is_a_404(app_client: TestClient, auth: dict[str, str]) -> None:
    read(app_client, auth)
    response = app_client.delete(f"{TRACKS}/telepathie", headers={**auth, "If-Match": "x"})

    assert response.status_code == 404


# ── Ordre et mise en avant (`HEAT-22`) ────────────────


def test_the_order_is_a_user_setting(app_client: TestClient, auth: dict[str, str]) -> None:
    read(app_client, auth)

    body = app_client.post(
        f"{TRACKS}/order", json={"track_ids": ["eau", "course"]}, headers=auth
    ).json()

    assert [track["track_id"] for track in body[:2]] == ["eau", "course"]


def test_tracks_left_out_of_a_reorder_keep_their_rank(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Un client qui n'enverrait que les deux premières ne doit pas faire disparaître les
    six autres."""
    before = {track["track_id"] for track in read(app_client, auth)["tracks"]}

    app_client.post(f"{TRACKS}/order", json={"track_ids": ["eau"]}, headers=auth)

    assert {track["track_id"] for track in read(app_client, auth)["tracks"]} == before


def test_highlighting_a_track_reaches_the_dashboard(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """La piste mise en avant est le réglage `heatmap_metric` — celui-là même que le
    tableau de bord expose sous `highlight` depuis le lot L08."""
    read(app_client, auth)

    body = app_client.post(f"{TRACKS}/eau/highlight", headers=auth).json()

    assert body["highlight"] == "eau"
    assert app_client.get("/api/aggregates/dashboard", headers=auth).json()["highlight"] == "eau"


# ── Jours neutralisés (`HEAT-06`) ─────────────────────


def test_a_range_can_be_neutralised(app_client: TestClient, auth: dict[str, str]) -> None:
    """Une grippe ne casse pas une série de quatre-vingt-dix jours."""
    read(app_client, auth)
    today = today_local()

    response = app_client.post(
        OFF_DAYS,
        json={
            "track_id": "",
            "date_from": (today - timedelta(days=6)).isoformat(),
            "date_to": today.isoformat(),
            "reason": "grippe",
        },
        headers=auth,
    )

    assert response.status_code == 201, response.text
    assert response.json()["days"] == 7
    assert response.json()["track_id"] == ""


async def test_a_global_neutralisation_covers_every_track(
    store: FileStore, dav: FakeWebDav
) -> None:
    """`track_id` vide neutralise **toutes** les pistes : c'est le cas d'une semaine
    d'arrêt, qu'on ne veut pas avoir à déclarer neuf fois."""
    from app.domains.heatmap.service import TrackService

    dav.seed(
        OFF_FILE,
        "id,track_id,date_from,date_to,reason\no1,,2026-07-01,2026-07-07,voyage\n",
    )

    plages = await TrackService(store).neutralised("eau")

    assert len(plages) == 1
    assert plages[0].covers(date(2026, 7, 4))
    assert not plages[0].covers(date(2026, 7, 8))


def test_a_reversed_range_is_refused(app_client: TestClient, auth: dict[str, str]) -> None:
    """Une plage à l'envers ne couvrirait aucun jour, et l'utilisateur croirait sa semaine
    neutralisée."""
    read(app_client, auth)
    today = today_local()

    response = app_client.post(
        OFF_DAYS,
        json={
            "date_from": today.isoformat(),
            "date_to": (today - timedelta(days=6)).isoformat(),
        },
        headers=auth,
    )

    assert response.status_code == 422


def test_a_future_neutralisation_is_refused(app_client: TestClient, auth: dict[str, str]) -> None:
    """On ne sait pas encore qu'on sera malade."""
    read(app_client, auth)
    tomorrow = (today_local() + timedelta(days=1)).isoformat()

    response = app_client.post(
        OFF_DAYS, json={"date_from": tomorrow, "date_to": tomorrow}, headers=auth
    )

    assert response.status_code == 422


def test_a_neutralisation_can_be_undone(app_client: TestClient, auth: dict[str, str]) -> None:
    read(app_client, auth)
    today = today_local()
    created = app_client.post(
        OFF_DAYS,
        json={"date_from": today.isoformat(), "date_to": today.isoformat()},
        headers=auth,
    ).json()

    response = app_client.delete(
        f"{OFF_DAYS}/{created['off_id']}", headers={**auth, "If-Match": created["token"]}
    )

    assert response.status_code == 204
    assert read(app_client, auth)["off_days"] == []


def test_undoing_a_neutralisation_without_the_token_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    read(app_client, auth)
    today = today_local()
    created = app_client.post(
        OFF_DAYS,
        json={"date_from": today.isoformat(), "date_to": today.isoformat()},
        headers=auth,
    ).json()

    assert app_client.delete(f"{OFF_DAYS}/{created['off_id']}", headers=auth).status_code == 409
    assert len(read(app_client, auth)["off_days"]) == 1


def test_neutralising_an_unknown_track_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    read(app_client, auth)
    today = today_local()

    response = app_client.post(
        OFF_DAYS,
        json={
            "track_id": "telepathie",
            "date_from": today.isoformat(),
            "date_to": today.isoformat(),
        },
        headers=auth,
    )

    assert response.status_code == 404


# ── Robustesse du fichier (leçon du lot L08) ──────────


def test_a_track_file_mangled_by_hand_still_answers(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Cellules vides, source inconnue, seuils illisibles, accent inventé : la piste doit
    se dégrader seule, sans emporter les autres."""
    dav.seed(
        TRACKS_FILE,
        "id,label,source,filter,validation_threshold,levels,binary,accent,position,active,created\n"
        "abimee,,activity.telepathie,,,abc;;3,false,fuchsia,0,true,\n"
        "eau,Eau,hydration.intake,,1500,1000;1500;2000;2500,false,signal,1,true,2026-01-15\n",
    )

    tracks = by_id(app_client, auth)

    assert tracks["abimee"]["label"] == "abimee", "à défaut de libellé, l'identifiant"
    assert tracks["abimee"]["source_label"] == "source inconnue"
    assert tracks["abimee"]["levels"] == [3.0], "les bornes illisibles sont ignorées"
    assert tracks["abimee"]["accent"] == "signal"
    assert tracks["eau"]["label"] == "Eau", "la piste saine est intacte"


def test_an_unreadable_cadence_in_the_journal_falls_back_to_daily(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le repli le moins surprenant : « tous les jours » est l'usage le plus courant."""
    dav.seed(
        TRACKS_FILE,
        "id,label,source,filter,validation_threshold,levels,binary,accent,position,active,created\n"
        "eau,Eau,hydration.intake,,1500,1000;1500,false,signal,0,true,2026-01-15\n",
    )
    dav.seed(
        CADENCES_FILE,
        "id,track_id,type,params,valid_from\nc1,eau,hebdomadaire,,2026-01-15\n",
    )

    assert by_id(app_client, auth)["eau"]["cadence"]["label"] == "tous les jours"
