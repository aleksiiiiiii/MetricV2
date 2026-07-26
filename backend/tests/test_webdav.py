"""Client WebDAV : verbes, réessais, traduction des erreurs (`STO-01`, `STO-08`, `STO-09`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx2
import pytest

from app.storage.errors import (
    StorageAuthFailedError,
    StorageConflictError,
    StorageNotFoundError,
    StorageUnavailableError,
)
from app.storage.webdav import WebDavClient
from tests.fake_webdav import FakeWebDav

# ── Verbes ────────────────────────────────────────────


async def test_put_then_get_round_trip(webdav: WebDavClient, dav: FakeWebDav) -> None:
    etag = await webdav.put("body/weight.csv", b"date,weight_kg\n2026-07-26,68.4\n")

    fetched = await webdav.get("body/weight.csv")

    assert fetched.content == b"date,weight_kg\n2026-07-26,68.4\n"
    assert fetched.etag == etag
    assert dav.content_of("Metric/body/weight.csv").startswith("date,weight_kg")


async def test_paths_are_prefixed_by_the_configured_root(webdav: WebDavClient) -> None:
    assert webdav.url_for("body/weight.csv") == "/Metric/body/weight.csv"


async def test_conditional_get_reports_not_modified(webdav: WebDavClient, dav: FakeWebDav) -> None:
    etag = dav.seed("Metric/body/weight.csv", "date\n2026-07-26\n")

    fetched = await webdav.get("body/weight.csv", etag=etag)

    assert fetched.not_modified is True
    assert fetched.content is None


async def test_mkcol_is_idempotent(webdav: WebDavClient, dav: FakeWebDav) -> None:
    await webdav.mkcol("nutrition")
    await webdav.mkcol("nutrition")  # 405 côté Nextcloud, non fatal

    assert "Metric/nutrition" in dav.collections
    assert dav.count("MKCOL") == 2


async def test_ensure_collection_creates_every_parent(
    webdav: WebDavClient, dav: FakeWebDav
) -> None:
    await webdav.ensure_collection("nutrition/photos/2026/07/26")

    assert "Metric/nutrition/photos/2026" in dav.collections
    assert "Metric/nutrition/photos/2026/07/26" in dav.collections


async def test_list_collection_returns_child_names(webdav: WebDavClient, dav: FakeWebDav) -> None:
    dav.seed("Metric/body/weight.csv", "date\n")
    dav.seed("Metric/body/measurements.csv", "date\n")

    names = await webdav.list_collection("body")

    assert sorted(names) == ["measurements.csv", "weight.csv"]


async def test_exists_distinguishes_present_from_absent(
    webdav: WebDavClient, dav: FakeWebDav
) -> None:
    dav.seed("Metric/body/weight.csv", "date\n")

    assert await webdav.exists("body/weight.csv") is True
    assert await webdav.exists("body/nowhere.csv") is False


# ── Réessais (`STO-08`) ───────────────────────────────


async def test_retries_on_429_and_honours_retry_after(
    webdav: WebDavClient, dav: FakeWebDav, sleeps: list[float]
) -> None:
    dav.seed("Metric/body/weight.csv", "date\n2026-07-26\n")
    dav.faults = [(429, {"Retry-After": "2"})]

    fetched = await webdav.get("body/weight.csv")

    assert fetched.content == b"date\n2026-07-26\n"
    assert sleeps == [2.0], "le délai annoncé par le serveur doit être respecté tel quel"


async def test_retry_after_accepts_an_http_date(
    webdav: WebDavClient, dav: FakeWebDav, sleeps: list[float]
) -> None:
    dav.seed("Metric/body/weight.csv", "date\n")
    when = datetime.now(tz=UTC) + timedelta(seconds=5)
    dav.faults = [(503, {"Retry-After": format_datetime(when, usegmt=True)})]

    await webdav.get("body/weight.csv")

    assert len(sleeps) == 1
    assert 3.0 <= sleeps[0] <= 6.0


async def test_retries_on_file_lock(webdav: WebDavClient, dav: FakeWebDav) -> None:
    """423 : verrou Nextcloud, fréquent quand la synchro tourne en parallèle."""
    dav.seed("Metric/body/weight.csv", "date\n")
    dav.faults = [(423, {}), (423, {})]

    fetched = await webdav.get("body/weight.csv")

    assert fetched.content == b"date\n"
    assert dav.count("GET") == 3


async def test_backoff_grows_and_stays_capped(
    webdav: WebDavClient, dav: FakeWebDav, sleeps: list[float]
) -> None:
    dav.seed("Metric/body/weight.csv", "date\n")
    dav.faults = [(503, {}), (503, {})]

    await webdav.get("body/weight.csv")

    assert len(sleeps) == 2
    assert all(0 < delay <= 8.0 for delay in sleeps)


async def test_gives_up_after_max_attempts(webdav: WebDavClient, dav: FakeWebDav) -> None:
    dav.seed("Metric/body/weight.csv", "date\n")
    dav.faults = [(503, {})] * 4

    with pytest.raises(StorageUnavailableError):
        await webdav.get("body/weight.csv")

    assert dav.count("GET") == 4, "quatre tentatives, pas une de plus"


async def test_retries_transport_errors(webdav: WebDavClient, dav: FakeWebDav) -> None:
    """Une coupure réseau passagère ne doit pas remonter à l'utilisateur."""
    dav.seed("Metric/body/weight.csv", "date\n")
    dav.faults = [httpx2.ConnectError("connexion perdue")]

    fetched = await webdav.get("body/weight.csv")

    assert fetched.content == b"date\n"


async def test_a_replayed_delete_tolerates_the_missing_file(
    webdav: WebDavClient, dav: FakeWebDav
) -> None:
    """Le premier DELETE a abouti, la réponse s'est perdue : le rejeu voit un 404."""
    dav.seed("Metric/body/weight.csv", "date\n")
    dav.faults = [(503, {})]

    await webdav.delete("body/weight.csv")

    assert "Metric/body/weight.csv" not in dav.files


# ── Traduction des erreurs (`STO-09`) ─────────────────


async def test_bad_credentials_are_not_retried(webdav: WebDavClient, dav: FakeWebDav) -> None:
    dav.faults = [(401, {})]

    with pytest.raises(StorageAuthFailedError) as caught:
        await webdav.get("body/weight.csv")

    assert dav.count("GET") == 1, "un mot de passe faux ne devient pas juste en réessayant"
    assert "identifiants" in caught.value.message


async def test_missing_file_raises_not_found(webdav: WebDavClient) -> None:
    with pytest.raises(StorageNotFoundError):
        await webdav.get("body/nowhere.csv")


async def test_if_match_mismatch_is_a_conflict(webdav: WebDavClient, dav: FakeWebDav) -> None:
    """Cœur de `STO-05` : le fichier a changé depuis la lecture."""
    dav.seed("Metric/body/weight.csv", "date\n")

    with pytest.raises(StorageConflictError):
        await webdav.put("body/weight.csv", b"autre", if_match='"etag-perime"')


async def test_if_none_match_refuses_to_overwrite(webdav: WebDavClient, dav: FakeWebDav) -> None:
    dav.seed("Metric/body/weight.csv", "date\n")

    with pytest.raises(StorageConflictError):
        await webdav.put("body/weight.csv", b"autre", if_none_match="*")


async def test_error_messages_never_leak_the_username(
    webdav: WebDavClient, dav: FakeWebDav
) -> None:
    dav.faults = [(403, {})]

    with pytest.raises(StorageAuthFailedError) as caught:
        await webdav.get("body/weight.csv")

    assert "aleksi" not in caught.value.message
    assert "secret" not in str(caught.value)
