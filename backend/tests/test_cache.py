"""Cache des lectures et cohérence (`STO-06`, décision **D8**)."""

from __future__ import annotations

from app.storage.cache import DEFAULT_TTL, FileCache
from app.storage.files import FileStore
from app.storage.webdav import WebDavClient
from tests.fake_webdav import FakeWebDav


class Clock:
    """Horloge manuelle : le TTL se teste sans attendre."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def test_a_second_read_within_the_ttl_costs_nothing(
    store: FileStore, dav: FakeWebDav
) -> None:
    """Le point du cache : dix fichiers pour un tableau de bord, pas dix requêtes."""
    dav.seed("Metric/body/weight.csv", "date\n2026-07-26\n")

    first = await store.read("body/weight.csv")
    second = await store.read("body/weight.csv")

    assert first.content == second.content
    assert dav.count("GET") == 1


async def test_past_the_ttl_the_server_is_revalidated_not_refetched(
    webdav: WebDavClient, dav: FakeWebDav
) -> None:
    """Un 304 confirme l'entrée sans retransférer le fichier."""
    clock = Clock()
    store = FileStore(webdav, FileCache(ttl=30.0, clock=clock))
    dav.seed("Metric/body/weight.csv", "date\n2026-07-26\n")

    await store.read("body/weight.csv")
    clock.advance(31)
    again = await store.read("body/weight.csv")

    assert again.content == b"date\n2026-07-26\n"
    assert dav.count("GET") == 2, "une revalidation, pas plus"


async def test_an_external_change_is_picked_up_after_the_ttl(
    webdav: WebDavClient, dav: FakeWebDav
) -> None:
    """Décision **D8** : Nextcloud est modifiable depuis un autre appareil ou un tableur.

    L'invalidation ne peut donc pas suivre uniquement nos propres écritures.
    """
    clock = Clock()
    store = FileStore(webdav, FileCache(ttl=30.0, clock=clock))
    dav.seed("Metric/body/weight.csv", "date\n2026-07-26\n")
    await store.read("body/weight.csv")

    # Modification « depuis un autre appareil » : nouveau contenu, nouvel ETag.
    dav.seed("Metric/body/weight.csv", "date\n2026-07-27\n")

    clock.advance(31)
    refreshed = await store.read("body/weight.csv")

    assert refreshed.content == b"date\n2026-07-27\n"


async def test_a_fresh_read_bypasses_the_ttl(webdav: WebDavClient, dav: FakeWebDav) -> None:
    """Ce dont dépend la garde anti-conflit : deux appareils au cache chaud passeraient
    tous les deux la garde, et le second écraserait le premier."""
    clock = Clock()
    store = FileStore(webdav, FileCache(ttl=300.0, clock=clock))
    dav.seed("Metric/body/weight.csv", "date\n2026-07-26\n")
    await store.read("body/weight.csv")

    dav.seed("Metric/body/weight.csv", "date\n2026-07-27\n")
    fresh = await store.read("body/weight.csv", fresh=True)

    assert fresh.content == b"date\n2026-07-27\n"


async def test_writing_keeps_the_cache_in_phase(store: FileStore, dav: FakeWebDav) -> None:
    dav.seed("Metric/body/weight.csv", "date\n2026-07-26\n")
    await store.read("body/weight.csv")

    await store.write("body/weight.csv", b"date\n2026-07-28\n")
    after = await store.read("body/weight.csv")

    assert after.content == b"date\n2026-07-28\n"
    assert dav.count("GET") == 1, "l'écriture a mémorisé le contenu, pas besoin de relire"


async def test_deleting_drops_the_entry(store: FileStore, dav: FakeWebDav) -> None:
    dav.seed("Metric/body/weight.csv", "date\n")
    await store.read("body/weight.csv")

    await store.delete("body/weight.csv")
    after = await store.read("body/weight.csv")

    assert after.exists is False
    assert after.content == b""


async def test_a_missing_file_reads_as_empty_not_as_an_error(store: FileStore) -> None:
    """Pour un CSV, « pas encore de fichier » et « fichier sans lignes » se traitent
    pareil côté domaine."""
    state = await store.read("body/nowhere.csv")

    assert state.exists is False
    assert state.etag is None
    assert state.content == b""


async def test_a_server_without_etag_invalidates_rather_than_lies(
    webdav: WebDavClient, dav: FakeWebDav
) -> None:
    """Mieux vaut une requête de plus qu'un cache qui mentirait sur l'ETag et ferait
    échouer la garde suivante."""
    cache = FileCache()
    store = FileStore(webdav, cache)
    dav.omit_etag = True  # PUT accepté, mais sans en-tête ETag

    await store.write("body/weight.csv", b"date\n")

    assert len(cache) == 0, "un cache sans ETag fiable doit être vidé, pas conservé"


async def test_an_absence_is_remembered_too(store: FileStore, dav: FakeWebDav) -> None:
    """Sur une installation neuve, aucun fichier n'existe.

    Le tableau de bord (`AGG-01`) réclame neuf sources, dont plusieurs deux fois — le
    poids sert à la fois les indicateurs et la série d'assiduité. Si l'absence n'était pas
    mémorisée, chaque domaine irait redemander un 404 que le précédent venait d'obtenir,
    et la promesse d'« une requête pour tout l'écran » se paierait en allers-retours
    invisibles côté serveur.
    """
    first = await store.read("body/nowhere.csv")
    second = await store.read("body/nowhere.csv")

    assert first.exists is False
    assert second.exists is False
    assert second.content == b""
    assert dav.count("GET") == 1, "le 404 a été redemandé"


async def test_a_file_that_appears_is_seen_once_the_entry_ages(
    webdav: WebDavClient, dav: FakeWebDav
) -> None:
    """La contrepartie, et elle est bornée.

    Un fichier déposé depuis un autre appareil reste invisible au plus le temps du TTL —
    la même fenêtre d'incohérence que pour un contenu déjà lu (décision **D8**). Passé ce
    délai, la lecture repart au serveur.
    """
    clock = Clock()
    store = FileStore(webdav, FileCache(clock=clock))

    assert (await store.read("body/weight.csv")).exists is False

    dav.seed("Metric/body/weight.csv", "date\n2026-07-28\n")
    assert (await store.read("body/weight.csv")).exists is False, "encore dans le TTL"

    clock.advance(DEFAULT_TTL + 1)
    assert (await store.read("body/weight.csv")).exists is True
