"""Objet Cadence (`HEAT-09` → `HEAT-14`, `HEAT-23`, décision **D3**).

Il ne décide pas encore si un jour est validé — c'est le lot L10. Ce qui est vérifié ici,
c'est la grammaire : lire, écrire, refuser ce qui n'a pas de sens.
"""

from __future__ import annotations

import pytest

from app.core.cadence import Cadence, CadenceError, CadenceType


@pytest.mark.parametrize(
    "serialized",
    [
        "daily",
        "window:min_count=1;window_days=2",
        "per_week:count=3",
        "conditional:trigger=workout",
        "none",
    ],
)
def test_a_cadence_survives_a_round_trip(serialized: str) -> None:
    """La forme stockée doit se relire à l'identique : c'est ce qui permet à
    `schedule.csv` et au journal d'historisation de ne jamais diverger (**D3**)."""
    assert Cadence.parse(serialized).serialize() == serialized


def test_an_empty_frequency_means_daily() -> None:
    """Une ligne de planning antérieure à ce lot décrit un complément quotidien : c'est
    l'usage le plus courant et le moins surprenant."""
    assert Cadence.parse("").type is CadenceType.DAILY
    assert Cadence.parse("   ").type is CadenceType.DAILY


def test_an_unknown_type_is_refused() -> None:
    with pytest.raises(CadenceError, match="cadence inconnue"):
        Cadence.parse("mensuelle")


@pytest.mark.parametrize(
    "serialized",
    ["window:min_count=1", "window:window_days=2", "per_week", "conditional"],
)
def test_a_missing_parameter_is_refused(serialized: str) -> None:
    with pytest.raises(CadenceError, match="manquant"):
        Cadence.parse(serialized)


def test_a_non_numeric_parameter_is_refused() -> None:
    with pytest.raises(CadenceError, match="entier"):
        Cadence.parse("per_week:count=beaucoup")


def test_a_window_cannot_demand_more_than_it_holds() -> None:
    """Trois prises dans une fenêtre de deux jours est intenable par construction :
    mieux vaut le dire à la saisie qu'afficher une piste éternellement rouge."""
    with pytest.raises(CadenceError, match="plus de prises qu'elle ne compte de jours"):
        Cadence.parse("window:min_count=3;window_days=2")


def test_a_week_has_only_seven_days() -> None:
    with pytest.raises(CadenceError, match="sept jours"):
        Cadence.parse("per_week:count=9")


def test_a_count_below_one_is_refused() -> None:
    with pytest.raises(CadenceError, match="au moins 1"):
        Cadence.parse("per_week:count=0")


@pytest.mark.parametrize(
    ("serialized", "described"),
    [
        ("daily", "tous les jours"),
        ("window:min_count=1;window_days=2", "un jour sur deux"),
        ("window:min_count=2;window_days=5", "2 fois par 5 jours"),
        ("per_week:count=1", "une fois par semaine"),
        ("per_week:count=3", "3 fois par semaine"),
        ("conditional:trigger=séance", "les jours de séance"),
        ("none", "sans attente"),
    ],
)
def test_a_cadence_says_itself_in_french(serialized: str, described: str) -> None:
    """Le client affiche la formulation du serveur plutôt que de la reconstruire :
    deux formulations divergeraient au premier cas particulier."""
    assert Cadence.parse(serialized).describe() == described


def test_the_parameter_order_does_not_change_the_stored_form() -> None:
    """Deux saisies équivalentes doivent produire la même ligne de fichier, sinon le
    journal d'historisation enregistrerait un changement qui n'en est pas un."""
    first = Cadence.parse("window:window_days=2;min_count=1")
    second = Cadence.parse("window:min_count=1;window_days=2")

    assert first.serialize() == second.serialize()
