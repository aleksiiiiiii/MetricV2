"""Fichiers binaires et arborescence datée (`STO-07`, `NUT-02`)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.storage import paths
from app.storage.files import FileStore
from tests.fake_webdav import FakeWebDav

PARIS = ZoneInfo("Europe/Paris")


def test_a_dated_path_is_browsable_outside_the_app() -> None:
    when = datetime(2026, 7, 26, 13, 5, tzinfo=PARIS)

    assert paths.dated_directory(paths.MEAL_PHOTOS, when) == "nutrition/photos/2026/07/26"
    assert (
        paths.dated_file(paths.MEAL_PHOTOS, when, "20260726-130500.jpg")
        == "nutrition/photos/2026/07/26/20260726-130500.jpg"
    )


async def test_uploading_creates_every_parent_directory(store: FileStore, dav: FakeWebDav) -> None:
    when = datetime(2026, 7, 26, 13, 5, tzinfo=PARIS)
    path = paths.dated_file(paths.MEAL_PHOTOS, when, "20260726-130500.jpg")

    await store.write_binary(path, b"\xff\xd8\xff\xe0jpeg", content_type="image/jpeg")

    assert "Metric/nutrition/photos/2026/07/26" in dav.collections
    assert dav.files[f"Metric/{path}"].content == b"\xff\xd8\xff\xe0jpeg"


async def test_a_binary_round_trip_is_byte_exact(store: FileStore) -> None:
    payload = bytes(range(256))

    await store.write_binary(
        "nutrition/photos/2026/07/26/x.jpg", payload, content_type="image/jpeg"
    )
    read_back = await store.read_binary("nutrition/photos/2026/07/26/x.jpg")

    assert read_back == payload


async def test_binaries_do_not_pollute_the_csv_cache(store: FileStore) -> None:
    """Volumineux et immuables : ils sont servis par un endpoint qui pose ses propres
    en-têtes de cache (`NUT-08`), pas par le cache mémoire des CSV."""
    await store.write_binary(
        "nutrition/photos/2026/07/26/x.jpg", b"jpeg", content_type="image/jpeg"
    )

    assert len(store.cache) == 0


async def test_parent_directories_are_created_once_not_per_upload(
    store: FileStore, dav: FakeWebDav
) -> None:
    for index in range(3):
        await store.write_binary(
            f"nutrition/photos/2026/07/26/{index}.jpg", b"jpeg", content_type="image/jpeg"
        )

    # Dossier racine + 5 segments à la première écriture, rien ensuite.
    assert dav.count("MKCOL") == 6
