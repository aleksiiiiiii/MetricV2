"""Cache des grilles et coût d'un affichage (`HEAT-33`, décision **D8**, lot L11).

Ce fichier existe parce que le lot L10 laissait une question ouverte que personne ne
pouvait trancher de tête : **où passe le temps d'un affichage d'assiduité ?** La réponse,
mesurée sur un an de saisie, a décidé de la conception — le réseau était déjà réglé par
le cache de `FileStore`, et les 50 ms restantes étaient du calcul refait à l'identique.

Les tests portent donc sur les deux propriétés qui comptent, et dans cet ordre :

1. **la justesse d'abord** — une grille mémorisée disparaît dès que l'un des fichiers qui
   l'ont produite change, y compris quand le changement vient d'ailleurs que de nous ;
2. **le coût ensuite** — neuf pistes sur 371 jours ne se relisent ni ne se recalculent à
   chaque affichage.

Un cache qui se trompe est pire que pas de cache : il fait mentir la grille sans rien
signaler, et l'utilisateur conclut que sa saisie n'a pas été enregistrée.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.core.cadence import Cadence
from app.core.dates import today_local
from app.domains.heatmap.cache import GridCache, GridKey
from app.domains.heatmap.engine import Grid, Range, Stats
from app.domains.heatmap.grids import GridService, _dependencies
from app.domains.heatmap.sources import SOURCES, daily_values
from app.storage.cache import FileCache
from app.storage.csv_repo import CsvRepository
from app.storage.files import FileStore
from app.storage.webdav import WebDavClient
from tests.fake_webdav import FakeWebDav

TODAY = today_local()
#: Un an plein, la plage par défaut de `HEAT-31`.
DAYS = 371
CREATED = TODAY - timedelta(days=DAYS)

TRACKS_FILE = "Metric/settings/heatmap_tracks.csv"
CADENCES_FILE = "Metric/settings/heatmap_cadences.csv"
OFF_FILE = "Metric/settings/heatmap_off_days.csv"
EXERCISE_LOG = "Metric/activity/exercise_log.csv"
RUNS = "Metric/activity/runs.csv"
WORKOUTS = "Metric/activity/workouts.csv"
HYDRATION = "Metric/hydration/intake_log.csv"
SUPPLEMENT_LOG = "Metric/supplements/intake_log.csv"
SCHEDULE = "Metric/supplements/schedule.csv"

TRACK_HEADER = (
    "id,label,source,filter,validation_threshold,levels,binary,accent,position,active,created\n"
)
MUSCLES = (
    ("torse", "Torse", "pectoraux"),
    ("dos", "Dos", "dos"),
    ("bras", "Bras", "biceps"),
    ("jambes", "Jambes", "jambes"),
    ("abdos", "Abdos", "abdos"),
)


@pytest.fixture
def loads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fichiers **analysés** — pas seulement lus.

    C'est la mesure qui compte : le cache de `FileStore` évite déjà le réseau, et ce que
    le cache des grilles doit supprimer est la revalidation Pydantic de milliers de
    lignes. Compter les requêtes HTTP ne l'aurait pas montré.
    """
    seen: list[str] = []
    original: Any = CsvRepository.load

    async def counted(self: Any, *, fresh: bool = False) -> Any:
        seen.append(self.path)
        return await original(self, fresh=fresh)

    monkeypatch.setattr(CsvRepository, "load", counted)
    return seen


@pytest.fixture
def full_dav(dav: FakeWebDav) -> FakeWebDav:
    """Neuf pistes et un an de saisie réaliste — le vrai cas d'usage de l'écran."""
    tracks = TRACK_HEADER
    cadences = "id,track_id,type,params,valid_from\n"

    for position, (track_id, label, group) in enumerate(MUSCLES):
        tracks += (
            f"{track_id},{label},activity.muscle_group,{group},1,1;3;6;10,false,effort,"
            f"{position},true,{CREATED}\n"
        )
        cadences += f"c{position},{track_id},per_week,count=2,{CREATED}\n"

    tracks += f"course,Course,activity.runs,,1,1;3;6;10,false,signal,5,true,{CREATED}\n"
    tracks += f"eau,Eau,hydration.intake,,1500,1000;1500;2000;2500,false,signal,6,true,{CREATED}\n"
    tracks += f"sup-s1,Créatine,supplement.intake,s1,1,,true,recover,7,true,{CREATED}\n"
    tracks += f"sup-s2,Whey,supplement.intake,s2,1,,true,recover,8,true,{CREATED}\n"
    cadences += f"c5,course,per_week,count=3,{CREATED}\n"
    cadences += f"c6,eau,daily,,{CREATED}\n"
    cadences += f"c7,sup-s1,daily,,{CREATED}\n"
    cadences += f"c8,sup-s2,window,min_count=1;window_days=2,{CREATED}\n"

    dav.seed(TRACKS_FILE, tracks)
    dav.seed(CADENCES_FILE, cadences)
    dav.seed(OFF_FILE, "id,track_id,date_from,date_to,reason\n")
    dav.seed(
        SCHEDULE,
        "id,name,dose,unit,time,frequency,active,created\n"
        f"s1,Créatine,5,g,08:00,daily,true,{CREATED}\n"
        f"s2,Whey,30,g,12:30,window:min_count=1;window_days=2,true,{CREATED}\n",
    )

    log = "workout_id,date,exercise_id,exercise_name,muscle_group,weight_kg,sets,reps,note\n"
    runs = "id,date,distance_km,duration_min,pace_min_km,note\n"
    hydration = "datetime,volume_ml,kind\n"
    intakes = "datetime,schedule_id,name,dose,unit\n"

    for offset in range(DAYS):
        day = TODAY - timedelta(days=offset)
        if offset % 2 == 0:
            group = MUSCLES[offset % 5][2]
            for exercise in range(4):
                log += f"w{offset},{day},e{exercise},Exercice {exercise},{group},60,4,10,\n"
        if offset % 3 == 0:
            runs += f"r{offset},{day},8.2,44.5,5.4,\n"
        for hour in (8, 12, 18):
            hydration += f"{day}T{hour:02d}:00:00+02:00,700,eau\n"
        intakes += f"{day}T08:00:00+02:00,s1,Créatine,5,g\n"

    dav.seed(EXERCISE_LOG, log)
    dav.seed(RUNS, runs)
    dav.seed(WORKOUTS, "id,date,type,duration_min,note\n")
    dav.seed(HYDRATION, hydration)
    dav.seed(SUPPLEMENT_LOG, intakes)
    return dav


@pytest.fixture
def grids_cache() -> GridCache:
    """Le cache des grilles. Nommé sans ambiguïté : `cache` désigne déjà le cache de
    fichiers du conftest, et l'ombrer donnerait un `FileStore` bâti sur le mauvais objet."""
    return GridCache()


@pytest.fixture
def service(store: FileStore, grids_cache: GridCache) -> GridService:
    return GridService(store, grids_cache)


@pytest.fixture
def revalidating(webdav: WebDavClient, grids_cache: GridCache) -> GridService:
    """Service dont le cache de fichiers a **toujours** expiré.

    C'est l'état de l'application une trentaine de secondes après le dernier affichage,
    donc son état ordinaire — et le seul dans lequel une modification venue d'ailleurs
    peut être vue. Les tests d'invalidation passent tous par lui : les faire sur un cache
    fichier chaud vérifierait le TTL de `STO-06`, pas l'empreinte.
    """
    return GridService(FileStore(webdav, FileCache(ttl=0)), grids_cache)


async def display(service: GridService) -> int:
    """Un affichage complet de l'écran d'assiduité."""
    return len((await service.multi_view()).grids)


# ── Justesse (décision **D8**) ────────────────────────


async def test_a_second_display_recomputes_nothing(
    full_dav: FakeWebDav, service: GridService, grids_cache: GridCache, loads: list[str]
) -> None:
    """La propriété centrale du lot.

    Neuf pistes rouvrent les mêmes cinq fichiers : sans mémorisation, un affichage
    revalide six mille lignes Pydantic pour rendre exactement la grille précédente.
    """
    assert await display(service) == 9
    first = len(loads)
    assert grids_cache.misses == 9 and grids_cache.hits == 0

    loads.clear()
    assert await display(service) == 9

    assert grids_cache.hits == 9
    # Seule la liste des pistes est relue : c'est elle qui dit lesquelles afficher.
    assert loads == [TRACKS_FILE.removeprefix("Metric/")]
    assert first > 20, "le premier affichage analyse bien tous les fichiers sources"


async def test_a_grid_survives_the_file_cache_expiring(
    full_dav: FakeWebDav, revalidating: GridService, grids_cache: GridCache, loads: list[str]
) -> None:
    """Le cas que le TTL de `STO-06` rend fréquent, et le seul qui justifie une empreinte.

    Passé trente secondes, chaque fichier est revalidé auprès du serveur. Il répond `304`
    — même ETag, rien n'a bougé — et la grille mémorisée reste donc vraie. Un cache qui
    aurait expiré en même temps que les fichiers n'aurait servi qu'à l'intérieur d'une
    seule requête.
    """
    service = revalidating

    await display(service)
    full_dav.reset_journal()
    loads.clear()

    await display(service)

    assert grids_cache.hits == 9
    assert loads == [TRACKS_FILE.removeprefix("Metric/")]
    assert full_dav.count("GET") > 0, "les fichiers ont bien été revalidés"


async def test_a_change_made_elsewhere_invalidates_the_grid(
    full_dav: FakeWebDav, revalidating: GridService, grids_cache: GridCache
) -> None:
    service = revalidating
    """Nextcloud est modifiable depuis un téléphone ou un tableur (**D8**).

    L'empreinte porte l'ETag des sources et non l'heure du calcul : une ligne ajoutée
    hors de l'application fait tomber la grille, exactement comme une saisie faite ici.
    """
    await display(service)
    before = (await service.grid("eau")).grid

    # Le double réécrit le fichier avec un ETag neuf, comme le ferait un autre appareil.
    full_dav.seed(HYDRATION, full_dav.content_of(HYDRATION) + f"{TODAY}T21:00:00+02:00,900,eau\n")
    grids_cache.hits = grids_cache.misses = 0

    after = (await service.grid("eau")).grid

    assert grids_cache.misses == 1, "la grille de l'eau a été recalculée"
    assert after.stats.total > before.stats.total


async def test_only_the_tracks_that_read_the_file_are_invalidated(
    full_dav: FakeWebDav, revalidating: GridService, grids_cache: GridCache
) -> None:
    service = revalidating
    """Une empreinte par piste, et non une par écran.

    Boire un verre ne doit pas faire recalculer les cinq grilles musculaires : elles ne
    lisent pas ce fichier, et rien de ce qu'elles disent n'a changé.
    """
    await display(service)
    full_dav.seed(HYDRATION, full_dav.content_of(HYDRATION) + f"{TODAY}T21:00:00+02:00,900,eau\n")
    grids_cache.hits = grids_cache.misses = 0

    await display(service)

    assert grids_cache.misses == 1, "seule la piste eau"
    assert grids_cache.hits == 8


async def test_changing_a_validation_threshold_invalidates_the_grid(
    full_dav: FakeWebDav, revalidating: GridService, grids_cache: GridCache
) -> None:
    service = revalidating
    """`HEAT-20` promet qu'un seuil rejuge tout l'historique.

    Le fichier des pistes fait donc partie de l'empreinte, alors même qu'il est lu avant
    l'évaluation. L'oublier aurait produit le pire symptôme possible : un réglage qui
    s'enregistre, s'affiche comme enregistré, et ne change rien à la grille.
    """
    await display(service)
    validated = (await service.grid("eau")).grid.stats.validated_days

    full_dav.seed(TRACKS_FILE, full_dav.content_of(TRACKS_FILE).replace(",1500,", ",2500,"))
    grids_cache.hits = grids_cache.misses = 0

    assert (await service.grid("eau")).grid.stats.validated_days < validated
    assert grids_cache.misses == 1


async def test_nothing_is_memorised_when_the_server_gives_no_etag(
    full_dav: FakeWebDav, service: GridService, grids_cache: GridCache
) -> None:
    """Une grille qu'on ne saurait pas invalider vaut moins que pas de cache du tout.

    Sans ETag, la seule stratégie honnête est de recalculer. `check-storage` signale
    d'ailleurs ce cas comme une dégradation, pas comme un détail.
    """
    full_dav.omit_etag = True
    full_dav.files.clear()
    full_dav.seed(
        TRACKS_FILE,
        TRACK_HEADER + f"eau,Eau,hydration.intake,,1500,,false,signal,0,true,{CREATED}\n",
    )

    await service.grid("eau")
    await service.grid("eau")

    assert len(grids_cache) == 0
    assert grids_cache.hits == 0


# ── Coût d'un affichage (`L11-05`) ────────────────────


async def test_nine_tracks_over_a_year_do_not_reread_nextcloud(
    full_dav: FakeWebDav, service: GridService
) -> None:
    """`HEAT-33`, énoncé tel quel : « un calcul sur 371 jours × 9 pistes ne doit pas
    relire Nextcloud à chaque affichage »."""
    view = await service.multi_view()
    assert len(view.grids) == 9
    assert all(len(grid.days) == 371 for grid in view.grids)

    full_dav.reset_journal()
    await service.multi_view()

    assert full_dav.requests == []


async def test_one_display_opens_each_file_once_not_once_per_track(
    full_dav: FakeWebDav, service: GridService
) -> None:
    """Neuf pistes, sept fichiers. Sans cache de fichiers ni préchargement, ce serait
    plus de vingt requêtes — et sur l'instance réelle, à ~180 ms l'aller-retour, une
    attente de plusieurs secondes."""
    full_dav.reset_journal()
    await service.multi_view()

    fetched = [path for method, path in full_dav.requests if method == "GET"]
    assert len(fetched) == len(set(fetched)), "aucun fichier n'est demandé deux fois"
    assert len(fetched) <= 10


# ── Garde structurelle ────────────────────────────────


@pytest.mark.parametrize("key", sorted(SOURCES))
async def test_declared_paths_match_what_is_read(
    full_dav: FakeWebDav, store: FileStore, key: str
) -> None:
    """Les chemins déclarés par une source servent au préchargement.

    Ils ne décident **pas** de la validité du cache — l'empreinte, elle, est relevée à
    l'exécution. Mais une déclaration fausse ferait payer un aller-retour séquentiel à
    chaque affichage sans que rien ne le dise, et c'est précisément le genre de dérive
    silencieuse que le lot L09 a déjà rencontrée sur la garde d'authentification.
    """
    source = SOURCES[key]
    filter_ = "s1" if key == "supplement.intake" else "pectoraux"

    with store.observe() as read_paths:
        await daily_values(store, key, filter_)

    assert set(read_paths) == set(source.paths)


def test_the_prefetch_list_covers_every_configuration_file() -> None:
    """Les trois fichiers de configuration sont ouverts par toute grille, quelle que soit
    sa source : ils doivent être préchargés même pour une piste dont la source n'en
    déclare aucun."""
    dependencies = _dependencies([])

    assert TRACKS_FILE.removeprefix("Metric/") in dependencies
    assert CADENCES_FILE.removeprefix("Metric/") in dependencies
    assert OFF_FILE.removeprefix("Metric/") in dependencies


# ── Éviction ──────────────────────────────────────────


def empty_grid() -> Grid:
    return Grid(
        range=Range(TODAY, TODAY),
        days=[],
        weeks=None,
        stats=Stats(0, 0, None, 0, 0, None, None, 0),
        cadence=Cadence.parse("daily"),
    )


def test_the_oldest_entry_leaves_first() -> None:
    """Le tiroir de détail évalue un jour par cellule ouverte : sans plafond, une session
    curieuse ferait grossir le cache indéfiniment."""
    small = GridCache(max_entries=2)

    for index in range(3):
        small.store(GridKey(f"t{index}", TODAY, TODAY, TODAY), empty_grid(), {"a": f"e{index}"})

    assert len(small) == 2
    assert small.get(GridKey("t0", TODAY, TODAY, TODAY)) is None
    assert small.get(GridKey("t2", TODAY, TODAY, TODAY)) is not None


def test_reading_an_entry_makes_it_the_freshest() -> None:
    """L'éviction est un vrai LRU et non un premier-entré-premier-sorti.

    La piste mise en avant est consultée à chaque affichage : la faire partir parce
    qu'elle a été mémorisée en premier serait exactement le mauvais choix.
    """
    small = GridCache(max_entries=2)
    for index in range(2):
        small.store(GridKey(f"t{index}", TODAY, TODAY, TODAY), empty_grid(), {"a": f"e{index}"})

    small.get(GridKey("t0", TODAY, TODAY, TODAY))
    small.store(GridKey("t2", TODAY, TODAY, TODAY), empty_grid(), {"a": "e2"})

    assert small.get(GridKey("t0", TODAY, TODAY, TODAY)) is not None
    assert small.get(GridKey("t1", TODAY, TODAY, TODAY)) is None


def test_a_cleared_cache_forgets_its_counters_too() -> None:
    small = GridCache()
    small.store(GridKey("t", TODAY, TODAY, TODAY), empty_grid(), {"a": "e"})
    small.record(hit=True)

    small.clear()

    assert len(small) == 0 and small.hits == 0 and small.misses == 0
