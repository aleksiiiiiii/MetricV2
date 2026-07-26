"""Cycle de vie de la couche stockage."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.storage.errors import StorageNotConfiguredError
from app.storage.provider import StorageProvider


def unconfigured() -> Settings:
    return Settings(_env_file=None)


def with_nextcloud() -> Settings:
    return Settings(
        _env_file=None,
        nextcloud_url="http://nextcloud.test",
        nextcloud_username="aleksi",
        nextcloud_password="secret",
        nextcloud_root="Metric",
    )


async def test_without_configuration_nothing_is_opened() -> None:
    """L'application doit démarrer sans Nextcloud : seuls les écrans de données échouent."""
    provider = StorageProvider(unconfigured())

    await provider.start()

    assert provider.configured is False
    with pytest.raises(StorageNotConfiguredError):
        _ = provider.store
    await provider.stop()


async def test_starting_opens_a_usable_store() -> None:
    provider = StorageProvider(with_nextcloud())

    await provider.start()
    try:
        assert provider.configured is True
        assert provider.store.client.url_for("body/weight.csv") == "/Metric/body/weight.csv"
    finally:
        await provider.stop()


async def test_stopping_releases_the_connection_pool() -> None:
    """Les connexions keep-alive doivent être relâchées à l'arrêt (`STO-08`)."""
    provider = StorageProvider(with_nextcloud())
    await provider.start()

    await provider.stop()

    with pytest.raises(StorageNotConfiguredError):
        _ = provider.store


async def test_stopping_without_starting_is_harmless() -> None:
    provider = StorageProvider(with_nextcloud())

    await provider.stop()  # ne doit pas lever

    assert provider.configured is True
