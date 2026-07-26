"""Analyse des saisies humaines (`ACT-01`, `ACT-02`, `ACT-15`, `IMP-03`)."""

from __future__ import annotations

import pytest

from app.core.parsing import (
    ParseError,
    estimate_one_rep_max,
    format_duration,
    pace_min_per_km,
    parse_decimal,
    parse_distance_km,
    parse_duration_minutes,
)


@pytest.mark.parametrize(
    ("saisie", "minutes"),
    [
        ("44:12", 44.2),  # minutes et secondes
        ("1:18:44", 78.7333333),  # heures, minutes, secondes
        ("0:45", 0.75),
        ("44", 44.0),  # minutes seules
        ("44,5", 44.5),  # virgule française
        ("44.5", 44.5),
        ("90min", 90.0),
        ("1h30", 90.0),
        ("1 h 30", 90.0),
        ("2h", 120.0),
        (" 44:12 ", 44.2),  # espaces autour
    ],
)
def test_a_duration_is_understood_in_every_usual_form(saisie: str, minutes: float) -> None:
    """`ACT-01` : refuser tous les formats sauf un coûterait plus de temps à la saisie
    que le relevé n'en vaut."""
    assert parse_duration_minutes(saisie) == pytest.approx(minutes, abs=1e-4)


def test_forty_four_twelve_means_minutes_not_hours() -> None:
    """Le choix suit l'usage du domaine : une séance dépasse rarement la journée."""
    assert parse_duration_minutes("44:12") == pytest.approx(44.2)


@pytest.mark.parametrize("saisie", ["", "  ", "abc", "1:2:3:4", "h"])
def test_an_unintelligible_duration_is_refused(saisie: str) -> None:
    with pytest.raises(ParseError):
        parse_duration_minutes(saisie)


def test_a_number_already_numeric_passes_through() -> None:
    assert parse_duration_minutes(44.5) == 44.5


@pytest.mark.parametrize(
    ("saisie", "valeur"),
    [("8,40", 8.4), ("8.40", 8.4), (" 8,4 ", 8.4), ("1 200,5", 1200.5)],
)
def test_the_french_decimal_comma_is_accepted(saisie: str, valeur: float) -> None:
    assert parse_decimal(saisie) == pytest.approx(valeur)


@pytest.mark.parametrize(
    ("saisie", "km"),
    [("8,4", 8.4), ("8.4km", 8.4), ("5mi", 8.04672), ("3 miles", 4.828032)],
)
def test_miles_are_converted_at_entry(saisie: str, km: float) -> None:
    """`IMP-03` : une capture Apple d'un appareil impérial arrive en miles ; stocker
    deux unités dans la même colonne serait un piège durable."""
    assert parse_distance_km(saisie) == pytest.approx(km, abs=1e-4)


@pytest.mark.parametrize(
    ("minutes", "texte"), [(44.2, "44:12"), (78.7333, "1:18:44"), (0.75, "0:45")]
)
def test_a_duration_round_trips(minutes: float, texte: str) -> None:
    assert format_duration(minutes) == texte
    assert parse_duration_minutes(texte) == pytest.approx(minutes, abs=1e-3)


def test_the_pace_is_derived_from_distance_and_time() -> None:
    """`ACT-02` : 8,40 km en 44:12 donne 5:16 au kilomètre."""
    pace = pace_min_per_km(8.4, 44.2)

    assert pace is not None
    assert format_duration(pace) == "5:16"


@pytest.mark.parametrize(("distance", "minutes"), [(0, 44), (8.4, 0), (-1, 44)])
def test_a_pace_without_meaning_is_none(distance: float, minutes: float) -> None:
    """Une séance de musculation n'a pas d'allure."""
    assert pace_min_per_km(distance, minutes) is None


def test_epley_estimates_the_one_rep_max() -> None:
    """`ACT-15` : 100 kg × 10 réps → 133,3 kg."""
    assert estimate_one_rep_max(100, 10) == pytest.approx(133.3333, abs=1e-3)
    assert estimate_one_rep_max(80, 1) == pytest.approx(82.6667, abs=1e-3)


def test_bodyweight_has_no_estimated_maximum() -> None:
    """Charge 0 = poids du corps (`ACT-07`) : sans charge, la formule ne dit rien."""
    assert estimate_one_rep_max(0, 12) is None
    assert estimate_one_rep_max(60, 0) is None
