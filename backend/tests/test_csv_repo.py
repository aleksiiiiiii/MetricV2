"""Dépôt CSV : lecture typée, ajout, migration, gardes (`STO-02` → `STO-05`)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.storage.csv_repo import CsvRepository
from app.storage.errors import StorageConflictError, StorageSchemaError, StorageUnavailableError
from app.storage.files import FileStore
from app.storage.model import CsvModel
from tests.fake_webdav import FakeWebDav

PATH = "body/weight.csv"


class Weight(CsvModel):
    """Modèle de test, calqué sur `body/weight.csv`."""

    date: date
    weight_kg: float
    note: str | None = None
    source: str = "manual"


@pytest.fixture
def repo(store: FileStore) -> CsvRepository[Weight]:
    return CsvRepository(store, PATH, Weight)


# ── Lecture (`STO-02`) ────────────────────────────────


async def test_a_missing_file_reads_as_no_rows(repo: CsvRepository[Weight]) -> None:
    assert await repo.read_all() == []


async def test_an_empty_file_reads_as_no_rows(repo: CsvRepository[Weight], dav: FakeWebDav) -> None:
    dav.seed(f"Metric/{PATH}", "")

    assert await repo.read_all() == []


async def test_rows_are_parsed_into_typed_models(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    dav.seed(
        f"Metric/{PATH}",
        "date,weight_kg,note,source\n2026-07-26,68.4,jambes lourdes,manual\n",
    )

    rows = await repo.read_all()

    assert len(rows) == 1
    assert rows[0].model == Weight(
        date=date(2026, 7, 26), weight_kg=68.4, note="jambes lourdes", source="manual"
    )
    assert rows[0].index == 0


async def test_an_empty_cell_becomes_none(repo: CsvRepository[Weight], dav: FakeWebDav) -> None:
    dav.seed(f"Metric/{PATH}", "date,weight_kg,note,source\n2026-07-26,68.4,,manual\n")

    assert (await repo.read_all())[0].model.note is None


async def test_a_trailing_blank_line_is_ignored(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    dav.seed(f"Metric/{PATH}", "date,weight_kg,note,source\n2026-07-26,68.4,,manual\n\n")

    assert len(await repo.read_all()) == 1


async def test_an_unparseable_row_says_which_line_and_column(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    """Échouer bruyamment : l'utilisateur est aussi le mainteneur de ses fichiers."""
    dav.seed(
        f"Metric/{PATH}",
        "date,weight_kg,note,source\n2026-07-26,68.4,,manual\n2026-07-27,pas-un-nombre,,manual\n",
    )

    with pytest.raises(StorageSchemaError) as caught:
        await repo.read_all()

    assert "ligne 3" in str(caught.value)
    assert "weight_kg" in str(caught.value)


# ── Ajout (`STO-03`) ──────────────────────────────────


async def test_appending_to_a_missing_file_writes_the_header(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    await repo.append(Weight(date=date(2026, 7, 26), weight_kg=68.4))

    assert dav.content_of(f"Metric/{PATH}") == (
        "date,weight_kg,note,source\n2026-07-26,68.4,,manual\n"
    )


async def test_appending_leaves_existing_lines_byte_for_byte(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    """L'invariant de `STO-03` : un ajout n'est qu'un ajout."""
    dav.seed(f"Metric/{PATH}", "date,weight_kg,note,source\n2026-07-26,68.4,première,manual\n")

    await repo.append(Weight(date=date(2026, 7, 27), weight_kg=68.1))

    lines = dav.content_of(f"Metric/{PATH}").splitlines()
    assert lines[0] == "date,weight_kg,note,source"
    assert lines[1] == "2026-07-26,68.4,première,manual"
    assert lines[2] == "2026-07-27,68.1,,manual"


async def test_the_file_is_written_with_a_bom(repo: CsvRepository[Weight], dav: FakeWebDav) -> None:
    """Sans BOM, un double-clic dans Excel sous Windows massacre les accents."""
    await repo.append(Weight(date=date(2026, 7, 26), weight_kg=68.4, note="séance à jeun"))

    assert dav.files[f"Metric/{PATH}"].content.startswith(b"\xef\xbb\xbf")


async def test_accents_survive_a_round_trip(repo: CsvRepository[Weight]) -> None:
    await repo.append(Weight(date=date(2026, 7, 26), weight_kg=68.4, note="l'œil, à jeun, ça va"))

    assert (await repo.read_all())[0].model.note == "l'œil, à jeun, ça va"


async def test_an_offset_aware_datetime_survives_a_round_trip(store: FileStore) -> None:
    """`HEAT-32` : une prise à 23 h 30 doit rester interprétable sans deviner le fuseau."""

    class Intake(CsvModel):
        datetime_: datetime
        volume_ml: int

    repo = CsvRepository(store, "hydration/intake_log.csv", Intake)
    when = datetime(2026, 7, 26, 23, 30, tzinfo=UTC).astimezone(
        __import__("zoneinfo").ZoneInfo("Europe/Paris")
    )
    await repo.append(Intake(datetime_=when, volume_ml=500))

    assert (await repo.read_all())[0].model.datetime_ == when


# ── Migration d'en-tête (`STO-04`) ────────────────────


async def test_a_column_added_to_the_model_reads_as_its_default(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    """Le fichier ne connaît pas `source` : les lignes anciennes restent valides."""
    dav.seed(f"Metric/{PATH}", "date,weight_kg,note\n2026-07-26,68.4,ancienne ligne\n")

    rows = await repo.read_all()

    assert rows[0].model.source == "manual"
    assert rows[0].model.note == "ancienne ligne"


async def test_the_new_header_is_written_on_the_next_write(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    dav.seed(f"Metric/{PATH}", "date,weight_kg,note\n2026-07-26,68.4,ancienne\n")

    await repo.append(Weight(date=date(2026, 7, 27), weight_kg=68.1))

    assert dav.content_of(f"Metric/{PATH}").splitlines()[0] == "date,weight_kg,note,source"


async def test_columns_are_remapped_by_name_not_by_position(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    dav.seed(f"Metric/{PATH}", "note,date,source,weight_kg\ndésordre,2026-07-26,apple,68.4\n")

    row = (await repo.read_all())[0].model

    assert (row.date, row.weight_kg, row.note, row.source) == (
        date(2026, 7, 26),
        68.4,
        "désordre",
        "apple",
    )


async def test_a_column_unknown_to_the_app_is_never_destroyed(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    """Une colonne ajoutée à la main dans un tableur doit survivre à une écriture :
    c'est toute la promesse de `STO-02`."""
    dav.seed(
        f"Metric/{PATH}",
        "date,weight_kg,note,source,humeur\n2026-07-26,68.4,,manual,bonne\n",
    )

    await repo.append(Weight(date=date(2026, 7, 27), weight_kg=68.1))

    content = dav.content_of(f"Metric/{PATH}")
    assert content.splitlines()[0] == "date,weight_kg,note,source,humeur"
    assert "bonne" in content


# ── Garde anti-conflit (`STO-05`) ─────────────────────


async def test_replacing_a_row_that_did_not_change(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    dav.seed(f"Metric/{PATH}", "date,weight_kg,note,source\n2026-07-26,68.4,,manual\n")
    before = (await repo.read_all())[0]

    await repo.replace(0, before.raw, Weight(date=date(2026, 7, 26), weight_kg=68.9))

    assert (await repo.read_all(fresh=True))[0].model.weight_kg == 68.9


async def test_replacing_a_row_that_changed_elsewhere_is_refused(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    """Le cas qui motive `STO-05` : l'app est ouverte sur deux appareils."""
    dav.seed(f"Metric/{PATH}", "date,weight_kg,note,source\n2026-07-26,68.4,,manual\n")
    stale = (await repo.read_all())[0]

    # L'autre appareil a corrigé la pesée entre-temps.
    dav.seed(f"Metric/{PATH}", "date,weight_kg,note,source\n2026-07-26,70.2,,manual\n")

    with pytest.raises(StorageConflictError) as caught:
        await repo.replace(0, stale.raw, Weight(date=date(2026, 7, 26), weight_kg=68.9))

    assert "70.2" in str(caught.value), "le message doit dire ce qui a été trouvé"
    assert dav.content_of(f"Metric/{PATH}").count("70.2") == 1, "le fichier est intact"


async def test_a_partial_expectation_is_enough(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    """Le client peut n'annoncer que les colonnes qui l'intéressent."""
    dav.seed(f"Metric/{PATH}", "date,weight_kg,note,source\n2026-07-26,68.4,,manual\n")

    await repo.replace(0, {"weight_kg": "68.4"}, Weight(date=date(2026, 7, 26), weight_kg=68.9))

    assert (await repo.read_all(fresh=True))[0].model.weight_kg == 68.9


async def test_a_model_can_serve_as_the_expectation(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    dav.seed(f"Metric/{PATH}", "date,weight_kg,note,source\n2026-07-26,68.4,,manual\n")
    expected = Weight(date=date(2026, 7, 26), weight_kg=68.4)

    await repo.replace(0, expected, Weight(date=date(2026, 7, 26), weight_kg=68.9))

    assert (await repo.read_all(fresh=True))[0].model.weight_kg == 68.9


async def test_deleting_removes_only_the_targeted_row(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    dav.seed(
        f"Metric/{PATH}",
        "date,weight_kg,note,source\n"
        "2026-07-26,68.4,,manual\n"
        "2026-07-27,68.1,,manual\n"
        "2026-07-28,67.9,,manual\n",
    )
    rows = await repo.read_all()

    await repo.delete(1, rows[1].raw)

    remaining = [row.model.date for row in await repo.read_all(fresh=True)]
    assert remaining == [date(2026, 7, 26), date(2026, 7, 28)]


async def test_deleting_a_row_that_moved_is_refused(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    dav.seed(
        f"Metric/{PATH}",
        "date,weight_kg,note,source\n2026-07-26,68.4,,manual\n2026-07-27,68.1,,manual\n",
    )
    rows = await repo.read_all()

    # L'autre appareil a supprimé la première ligne : l'index 1 ne désigne plus la même.
    dav.seed(f"Metric/{PATH}", "date,weight_kg,note,source\n2026-07-27,68.1,,manual\n")

    with pytest.raises(StorageConflictError):
        await repo.delete(1, rows[1].raw)


async def test_an_index_out_of_range_is_a_conflict(repo: CsvRepository[Weight]) -> None:
    with pytest.raises(StorageConflictError):
        await repo.delete(7, {"weight_kg": "68.4"})


async def test_a_concurrent_append_is_replayed_not_refused(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    """Deux appareils qui enregistrent en même temps ne doivent pas s'envoyer un `409` :
    l'ordre de deux ajouts n'a pas d'importance."""
    dav.seed(f"Metric/{PATH}", "date,weight_kg,note,source\n2026-07-26,68.4,,manual\n")
    dav.faults = [None, (412, {})]  # la première tentative d'écriture est refusée

    await repo.append(Weight(date=date(2026, 7, 27), weight_kg=68.1))

    rows = await repo.read_all(fresh=True)
    assert [row.model.date for row in rows] == [date(2026, 7, 26), date(2026, 7, 27)]


async def test_an_interrupted_write_leaves_the_previous_version_intact(
    repo: CsvRepository[Weight], dav: FakeWebDav
) -> None:
    """Propriété recherchée par `STO-03` : jamais de fichier tronqué.

    L'écriture est annoncée comme une indisponibilité et non comme un conflit : il n'y a
    rien à recharger, il faut réessayer.
    """
    original = "date,weight_kg,note,source\n2026-07-26,68.4,,manual\n"
    dav.seed(f"Metric/{PATH}", original)
    dav.faults = [None, *[(503, {})] * 4]  # lecture ok, puis écriture qui n'aboutit jamais

    with pytest.raises(StorageUnavailableError):
        await repo.append(Weight(date=date(2026, 7, 27), weight_kg=68.1))

    assert dav.content_of(f"Metric/{PATH}") == original


async def test_overwrite_replaces_every_row(repo: CsvRepository[Weight], dav: FakeWebDav) -> None:
    dav.seed(f"Metric/{PATH}", "date,weight_kg,note,source\n2026-07-26,68.4,,manual\n")

    await repo.overwrite(
        [
            Weight(date=date(2026, 7, 27), weight_kg=68.1),
            Weight(date=date(2026, 7, 28), weight_kg=67.9),
        ]
    )

    rows = await repo.read_all(fresh=True)
    assert [row.model.date for row in rows] == [date(2026, 7, 27), date(2026, 7, 28)]


async def test_a_date_in_the_future_is_still_stored_as_written(store: FileStore) -> None:
    """Le dépôt ne juge pas la vraisemblance : c'est le rôle de la validation d'API
    (`API-06`), pas celui du stockage."""
    repo = CsvRepository(store, PATH, Weight)
    tomorrow = date.today() + timedelta(days=1)  # noqa: DTZ011 - borne de test, pas une donnée

    await repo.append(Weight(date=tomorrow, weight_kg=68.4))

    assert (await repo.read_all())[0].model.date == tomorrow
