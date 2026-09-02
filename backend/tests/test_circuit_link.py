"""Le lien de séance de Cadence Tabata (**D7**).

La spécification vit dans `llms.txt`, à la racine. Ce qui est vérifié ici, ce sont ses
cinq exemples décodés par l'implémentation réelle, sa liste de vérification, et l'aller
retour — le test qui attrape le plus de choses pour le moins d'écriture.

Aucun réseau, aucun fichier : le module est pur.
"""

from __future__ import annotations

import pytest

from app.domains.activity.circuit_link import (
    TIMED,
    LinkCircuit,
    LinkExercise,
    build_url,
    estimate,
    parse_url,
)

BASE = "https://cadence.exemple.fr"


def timed(name: str, seconds: int, rest: int = 0) -> LinkExercise:
    return LinkExercise(name=name, duration_s=seconds, reps=TIMED, rest_s=rest)


def reps(name: str, count: int, rest: int = 0) -> LinkExercise:
    return LinkExercise(name=name, reps=count, rest_s=rest)


# ── Les cinq exemples vérifiés de la spécification (§6) ─


EXAMPLES: tuple[tuple[str, LinkCircuit], ...] = (
    (
        "?w=Tabata+Classique~8~60~Squats:20s:10~Pompes:20s:10~Burpees:20s:10",
        LinkCircuit(
            name="Tabata Classique",
            rounds=8,
            round_rest_s=60,
            exercises=(timed("Squats", 20, 10), timed("Pompes", 20, 10), timed("Burpees", 20, 10)),
        ),
    ),
    (
        "?w=Full+Body~3~45~Crunchs:30s:10~Push-Ups+Classic:15x:20~Skater+Jumps:45s:15",
        LinkCircuit(
            name="Full Body",
            rounds=3,
            round_rest_s=45,
            exercises=(
                timed("Crunchs", 30, 10),
                reps("Push-Ups Classic", 15, 20),
                timed("Skater Jumps", 45, 15),
            ),
        ),
    ),
    (
        "?w=Force+Haut+du+Corps~4~90~Pull-ups:8x:30~Dips:12x:30~Pike+Push-ups:15x:45",
        LinkCircuit(
            name="Force Haut du Corps",
            rounds=4,
            round_rest_s=90,
            exercises=(
                reps("Pull-ups", 8, 30),
                reps("Dips", 12, 30),
                reps("Pike Push-ups", 15, 45),
            ),
        ),
    ),
    (
        "?w=S%C3%A9ance+%C2%AB+Jambes+%C2%BB+100%25~2~30~"
        "D%C3%A9velopp%C3%A9+couch%C3%A9+%7E+tempo+2%3A1:12x:60~Fentes+arri%C3%A8re:40s:20",
        LinkCircuit(
            name="Séance « Jambes » 100%",
            rounds=2,
            round_rest_s=30,
            exercises=(
                reps("Développé couché ~ tempo 2:1", 12, 60),
                timed("Fentes arrière", 40, 20),
            ),
        ),
    ),
    (
        "?w=Gainage~1~0~Plank:60s:0",
        LinkCircuit(name="Gainage", rounds=1, round_rest_s=0, exercises=(timed("Plank", 60),)),
    ),
)


@pytest.mark.parametrize(("query", "circuit"), EXAMPLES)
def test_the_five_verified_examples_are_produced_exactly(query: str, circuit: LinkCircuit) -> None:
    """Ces cinq liens ont été décodés par l'application réelle. Si l'un d'eux change,
    c'est notre générateur qui a tort, pas la spécification."""
    assert build_url(BASE, circuit) == BASE + query


@pytest.mark.parametrize(("query", "circuit"), EXAMPLES)
def test_the_five_verified_examples_are_read_back(query: str, circuit: LinkCircuit) -> None:
    assert parse_url(BASE + query) == circuit


@pytest.mark.parametrize(("query", "circuit"), EXAMPLES)
def test_a_link_survives_a_round_trip(query: str, circuit: LinkCircuit) -> None:
    """Encoder puis relire doit rendre l'original. C'est ce qui permet de coller un lien
    fabriqué ailleurs sans que Metric en perde un morceau au passage."""
    url = build_url(BASE, circuit)
    assert url is not None
    assert parse_url(url) == circuit


# ── L'erreur la plus fréquente (§2) ────────────────────


def test_repetitions_carry_the_x_suffix_and_seconds_do_not() -> None:
    """Le suffixe `x` n'est pas optionnel : sans lui, quinze répétitions deviennent quinze
    secondes, la séance se lance quand même, et elle est fausse en silence."""
    url = build_url(BASE, LinkCircuit("A", 1, 0, (reps("Pompes", 15, 20), timed("Gainage", 15))))

    assert url == f"{BASE}?w=A~1~0~Pompes:15x:20~Gainage:15s:0"


def test_a_tilde_or_a_colon_in_a_name_never_splits_the_workout() -> None:
    """Les deux séparateurs, dans un nom, au même endroit. `quote` laisse le tilde intact
    — c'est le remplacement explicite qui fait le travail."""
    url = build_url(BASE, LinkCircuit("A~B", 1, 0, (timed("tempo 2:1 ~ lent", 30),)))

    assert url == f"{BASE}?w=A%7EB~1~0~tempo+2%3A1+%7E+lent:30s:0"
    assert parse_url(url) == LinkCircuit("A~B", 1, 0, (timed("tempo 2:1 ~ lent", 30),))


# ── Bornes et tolérances (§4) ──────────────────────────


@pytest.mark.parametrize(
    ("segment", "expected"),
    [
        ("Ex:30:5", timed("Ex", 30, 5)),  # le « s » est optionnel
        ("Ex:15X:5", reps("Ex", 15, 5)),  # le « x » est insensible à la casse
        ("Ex:30s", timed("Ex", 30)),  # repos omis
        ("Ex", timed("Ex", 20)),  # tout omis
        ("Ex:0x:5", reps("Ex", 20, 5)),  # le piège : 0 est invalide, le suffixe reste
    ],
)
def test_the_tolerated_forms_are_read_as_the_specification_says(
    segment: str, expected: LinkExercise
) -> None:
    circuit = parse_url(f"{BASE}?w=A~1~0~{segment}")

    assert circuit is not None
    assert circuit.exercises == (expected,)


def test_out_of_range_values_are_clamped_and_not_rejected() -> None:
    """Cadence ramène dans l'intervalle plutôt que de refuser. Reproduire ce bornage est
    ce qui garantit que la durée annoncée est celle qui se déroulera."""
    circuit = parse_url(f"{BASE}?w=A~500~99999~Ex:5000s:-9")

    assert circuit is not None
    assert (circuit.rounds, circuit.round_rest_s) == (99, 900)
    assert circuit.exercises == (timed("Ex", 999, 0),)


# ── Liens sans issue (§9) ──────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        BASE,  # aucun paramètre
        f"{BASE}?w=",  # vide
        f"{BASE}?w=MaSéance",  # segments manquants
        f"{BASE}?w=A~8~60",  # aucun exercice
        f"{BASE}?w=A~8~60~:30s:10",  # nom d'exercice vide
    ],
)
def test_an_unusable_link_yields_nothing_rather_than_an_error(url: str) -> None:
    """Aucun lien ne produit d'erreur visible dans Cadence — il ouvre l'accueil. Le
    décodeur reproduit cette tolérance : l'appelant n'a qu'un seul cas à traiter."""
    assert parse_url(url) is None


def test_an_anonymous_exercise_is_dropped_and_the_others_are_kept() -> None:
    circuit = parse_url(f"{BASE}?w=A~8~60~:30s:10~B:20s:5")

    assert circuit is not None
    assert circuit.exercises == (timed("B", 20, 5),)


def test_other_query_parameters_are_ignored() -> None:
    """Un lien partagé traîne souvent un `utm_source`. Il ne doit pas empêcher de le
    relire, et l'ordre des paramètres n'a pas d'importance."""
    circuit = parse_url(f"{BASE}?utm_source=metric&w=Gainage~1~0~Plank:60s:0&x=1")

    assert circuit is not None
    assert circuit.name == "Gainage"


def test_no_base_address_means_no_link_at_all() -> None:
    """Pas d'adresse relative de repli : sans base, il n'y a pas de lien, et c'est un état
    que l'écran sait dire."""
    assert build_url("", LinkCircuit("A", 1, 0, (timed("Ex", 30),))) is None
    assert build_url("   ", LinkCircuit("A", 1, 0, (timed("Ex", 30),))) is None


def test_a_circuit_without_a_named_exercise_has_no_link() -> None:
    assert build_url(BASE, LinkCircuit("A", 1, 0, (timed("  ", 30),))) is None


# ── Durées et estimations (§7) ─────────────────────────


def test_a_timed_workout_has_an_exact_duration() -> None:
    """`(Σ(durée + repos)) × rounds + repos_round × (rounds - 1)`, et rien d'autre."""
    circuit = LinkCircuit("A", 8, 60, (timed("Squats", 20, 10), timed("Pompes", 20, 10)))

    # (30 + 30) × 8 + 60 × 7 = 480 + 420 = 900 s
    result = estimate(circuit)
    assert (result.minutes, result.exact) == (15.0, True)


def test_a_single_repetition_exercise_makes_the_whole_duration_an_estimate() -> None:
    """Personne ne sait combien de temps prend une série. Un seul exercice en répétitions
    suffit à retirer le droit d'annoncer une durée exacte."""
    circuit = LinkCircuit("A", 1, 0, (timed("Plank", 60), reps("Pull-ups", 8)))

    result = estimate(circuit)
    assert result.exact is False
    # 60 + max(8 × 2, 10) = 76 s
    assert result.minutes == pytest.approx(76 / 60, abs=0.05)


def test_a_very_short_series_still_costs_its_floor() -> None:
    """Deux secondes par répétition donnerait quatre secondes pour deux tractions. Le
    plancher de dix secondes est celui de Cadence : s'en écarter ferait afficher à Metric
    une durée que l'autre application contredit à l'écran suivant."""
    result = estimate(LinkCircuit("A", 1, 0, (reps("Pull-ups", 2),)))

    assert result.minutes == pytest.approx(10 / 60, abs=0.05)


def test_the_estimate_uses_the_clamped_values() -> None:
    """Annoncer 500 rounds quand Cadence en exécutera 99 serait faux d'un facteur cinq."""
    circuit = LinkCircuit("A", 500, 0, (timed("Ex", 60),))

    assert estimate(circuit).minutes == pytest.approx(99.0, abs=0.05)


# ── Le 4ᵉ champ : la note (§1, spécification v2) ───────


def test_the_note_is_omitted_when_there_is_nothing_to_say() -> None:
    """Un circuit sans charge produit **exactement** les octets d'hier.

    C'est la garantie de rétrocompatibilité, et elle se vérifie ici plutôt que par une
    relecture : un `:` final ajouté sans raison allongerait chaque lien déjà collé dans une
    note de planning, pour rien.
    """
    url = build_url(BASE, LinkCircuit("Gainage", 1, 0, (timed("Plank", 60),)))

    assert url == f"{BASE}?w=Gainage~1~0~Plank:60s:0"


def test_the_documented_example_with_notes_is_produced_exactly() -> None:
    """L'exemple EX6 de la spécification, octet pour octet — notes sur deux exercices,
    aucune sur le troisième."""
    url = build_url(
        BASE,
        LinkCircuit(
            name="Haut du corps",
            rounds=3,
            round_rest_s=60,
            exercises=(
                LinkExercise(name="Pompes", duration_s=30, reps=TIMED, rest_s=15, note="12 kg"),
                timed("Gainage", 45, 15),
                LinkExercise(name="Rowing", reps=12, rest_s=30, note="40 kg"),
            ),
        ),
    )

    assert (
        url == f"{BASE}?w=Haut+du+corps~3~60~Pompes:30s:15:12+kg~Gainage:45s:15~Rowing:12x:30:40+kg"
    )


def test_a_note_survives_a_round_trip_with_both_separators() -> None:
    """Les deux séparateurs dans une note, comme le test qui les vérifie dans un nom. Sans
    l'échappement, `tempo 3:1` couperait le champ et `~` couperait la séance."""
    circuit = LinkCircuit(
        "A",
        1,
        0,
        (LinkExercise(name="Rowing", duration_s=30, reps=TIMED, note="tempo 3:1 ~ lent"),),
    )
    url = build_url(BASE, circuit)

    assert url == f"{BASE}?w=A~1~0~Rowing:30s:0:tempo+3%3A1+%7E+lent"
    assert parse_url(url) == circuit


def test_an_empty_fourth_field_reads_as_no_note() -> None:
    """`Ex:30s:10:` est une écriture valide de la spécification, et elle vaut `Ex:30s:10`.
    Les deux doivent donner le même circuit, sinon relire un lien fabriqué à la main en
    produirait un autre."""
    with_field = parse_url(f"{BASE}?w=A~1~0~Rowing:30s:10:")
    without_field = parse_url(f"{BASE}?w=A~1~0~Rowing:30s:10")

    assert with_field == without_field
    assert with_field is not None
    assert with_field.exercises[0].note == ""


def test_an_unescaped_colon_in_a_note_is_cut_where_cadence_cuts_it() -> None:
    """Un lien mal fabriqué ailleurs porte un `:` nu dans sa note. On garde le premier
    champ et rien de plus — recoller les morceaux afficherait dans Metric une note que
    Cadence, lui, coupe au même endroit."""
    parsed = parse_url(f"{BASE}?w=A~1~0~Rowing:30s:10:tempo 3:1")

    assert parsed is not None
    assert parsed.exercises[0].note == "tempo 3"
