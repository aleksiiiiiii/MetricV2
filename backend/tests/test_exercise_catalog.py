"""Le catalogue d'exercices figé dans le dépôt (**C5**).

Module pur : aucun réseau, aucun fichier utilisateur. Ce qui est vérifié ici, c'est que le
fichier du dépôt est celui qu'on croit — les chiffres publiés par Cadence — et que la
recherche trouve un nom quelle que soit la façon de l'écrire.
"""

from __future__ import annotations

import pytest

from app.domains.activity import exercise_catalog


def test_the_frozen_catalogue_matches_what_cadence_publishes() -> None:
    """1324 exercices, 10 zones, 28 matériels, 19 cibles. Ces quatre nombres sont ceux
    que l'application cible annonce : s'ils divergent, le fichier a été régénéré depuis
    une autre source, et c'est ce qu'on veut voir échouer."""
    catalog = exercise_catalog.catalog()

    assert len(catalog.exercises) == 1324
    assert len(catalog.body_parts) == 10
    assert len(catalog.equipment) == 28
    assert len(catalog.targets) == 19


def test_a_documented_entry_is_read_with_its_three_fields() -> None:
    """L'exemple de la spécification : `barbell full squat` est upper legs · barbell ·
    glutes. Il vérifie que les indices `b`/`e`/`t` pointent bien dans les bonnes listes —
    une inversion de deux d'entre elles serait muette."""
    found = exercise_catalog.search("barbell full squat")[0]

    assert (found.body_part, found.equipment, found.target) == ("upper legs", "barbell", "glutes")


@pytest.mark.parametrize("written", ["push-up", "push up", "Pushup", "PUSH-UP"])
def test_one_exercise_is_found_however_it_is_written(written: str) -> None:
    """`fold` retire le trait d'union sans le remplacer : « push-up » y devient `pushup`
    et « push up » reste `push up`. Sans le repli sans espaces, une recherche sur deux
    ne trouve rien."""
    assert exercise_catalog.search(written)[0].name == "push-up"


def test_the_exact_name_comes_before_what_merely_contains_it() -> None:
    """Trois rangs et pas une note de similarité : le nom exact, puis ce qui commence par
    la recherche, puis ce qui la contient."""
    names = [item.name for item in exercise_catalog.search("pull-up", limit=5)]

    assert names[0] == "pull-up"


def test_a_search_without_a_keyword_is_a_legitimate_question() -> None:
    """« je n'ai que des haltères » n'a pas de mot-clé, et doit rendre le début du
    catalogue filtré plutôt que rien."""
    found = exercise_catalog.search("", equipment="dumbbell")

    assert found
    assert all(item.equipment == "dumbbell" for item in found)


def test_the_limit_is_never_exceeded() -> None:
    """Le catalogue entier fait 70 ko : le servir d'un bloc mettrait le filtrage du
    mauvais côté du réseau."""
    assert len(exercise_catalog.search("a")) == exercise_catalog.LIMIT


def test_bodyweight_is_read_from_the_equipment_and_nothing_else() -> None:
    """Le drapeau sert à **suggérer**, jamais à classer : la page Charges attend une
    déclaration de l'utilisateur (**C3**)."""
    push_up = exercise_catalog.search("push-up")[0]
    squat = exercise_catalog.search("barbell full squat")[0]

    assert push_up.bodyweight
    assert not squat.bodyweight


def test_common_equipment_exists_in_the_catalog() -> None:
    """Les douze matériels montrés d'emblée sont des valeurs du catalogue, à la lettre.

    Aucune traduction, aucune table de correspondance : ce qui est coché est exactement ce
    que la recherche filtre. Régénérer `exercise_catalog.json` avec un vocabulaire
    différent fait tomber ce test — sans lui, la moitié de l'écran de profil se viderait
    en silence, et le filtre cesserait de trouver quoi que ce soit.
    """
    known = set(exercise_catalog.catalog().equipment)

    assert set(exercise_catalog.COMMON_EQUIPMENT) <= known
    assert len(set(exercise_catalog.COMMON_EQUIPMENT)) == len(exercise_catalog.COMMON_EQUIPMENT)


def test_the_equipment_options_cover_the_catalogue_exactly_once() -> None:
    """Les 28, chacune une fois : les courantes dans l'ordre où elles se cochent, les
    autres par ordre alphabétique. Un matériel oublié ici ne se cocherait jamais."""
    options = exercise_catalog.equipment_options()

    assert [value for value, _ in options] != sorted(value for value, _ in options)
    assert {value for value, _ in options} == set(exercise_catalog.catalog().equipment)
    assert len(options) == len(exercise_catalog.catalog().equipment)
    assert [value for value, common in options if common] == list(exercise_catalog.COMMON_EQUIPMENT)
    rest = [value for value, common in options if not common]
    assert rest == sorted(rest)
