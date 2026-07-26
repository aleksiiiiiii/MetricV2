"""Script de vérification du stockage (`STO-11`).

C'est la première chose qu'on lance face à une Nextcloud inconnue : il doit dire ce qui
ne va pas, et surtout ne pas planter lui-même.
"""

from __future__ import annotations

from typing import Any

import httpx2
import pytest

from app.config import Settings
from app.scripts import check_storage
from app.storage.webdav import WebDavClient
from tests.fake_webdav import FakeWebDav


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch, dav: FakeWebDav) -> None:
    """Branche le script sur le double, sans passer par l'environnement ni par `.env`."""
    monkeypatch.setattr(
        check_storage,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            nextcloud_url="http://nextcloud.test",
            nextcloud_username="aleksi",
            nextcloud_password="secret",
            nextcloud_root="Metric",
        ),
    )

    def with_double(**kwargs: Any) -> WebDavClient:
        return WebDavClient(**kwargs, transport=httpx2.ASGITransport(app=dav))

    monkeypatch.setattr(check_storage, "WebDavClient", with_double)


async def test_it_explains_what_to_fill_in_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_storage, "get_settings", lambda: Settings(_env_file=None))

    code = await check_storage.run()

    assert code == 2
    assert "NEXTCLOUD_URL" in capsys.readouterr().out


async def test_a_healthy_storage_passes_every_step(
    configured: None, dav: FakeWebDav, capsys: pytest.CaptureFixture[str]
) -> None:
    del configured

    code = await check_storage.run()
    out = capsys.readouterr().out

    assert code == 0
    assert "Stockage opérationnel" in out
    assert "304 honoré" in out, "la revalidation conditionnelle doit être vérifiée (D8)"


async def test_it_cleans_up_after_itself(configured: None, dav: FakeWebDav) -> None:
    """Un diagnostic ne doit pas laisser de déchet dans les données de l'utilisateur."""
    del configured

    await check_storage.run()

    assert not [name for name in dav.files if "healthcheck" in name]


async def test_bad_credentials_are_reported_not_raised(
    configured: None, dav: FakeWebDav, capsys: pytest.CaptureFixture[str]
) -> None:
    del configured
    dav.faults = [(401, {})]

    code = await check_storage.run()
    out = capsys.readouterr().out

    assert code == 1
    assert "identifiants" in out
    assert "Traceback" not in out


async def test_a_server_without_etag_is_flagged_as_degraded(
    configured: None, dav: FakeWebDav, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sans ETag, la garde anti-conflit tombe : il faut le dire, pas le taire."""
    del configured
    dav.omit_etag = True

    code = await check_storage.run()
    out = capsys.readouterr().out

    assert code == 0, "dégradé n'est pas cassé : le script continue"
    assert "garde anti-conflit sera dégradée" in out
