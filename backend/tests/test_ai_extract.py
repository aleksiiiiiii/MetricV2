"""Extraction du JSON d'une réponse de modèle (`IA-05`, `L12-16`).

Chaque cas de ce fichier a été vu en vrai sur un modèle gratuit. Ce n'est pas une liste de
malveillances imaginées : c'est ce que rendent les modèles quand on leur demande du JSON.
"""

from __future__ import annotations

from app.domains.ai.extract import first_json_object, strip_reasoning


def test_a_bare_object_is_read() -> None:
    assert first_json_object('{"protein_g": 32}') == {"protein_g": 32}


def test_politeness_around_the_object_is_ignored() -> None:
    """Le cas le plus fréquent : le modèle encadre sa réponse de deux phrases."""
    raw = (
        "Bien sûr ! Voici mon estimation pour ce repas :\n"
        '{"protein_g": 32, "calories": 640}\n'
        "N'hésite pas si tu veux plus de détails."
    )

    assert first_json_object(raw) == {"protein_g": 32, "calories": 640}


def test_a_fenced_code_block_is_read() -> None:
    raw = '```json\n{"protein_g": 28}\n```'

    assert first_json_object(raw) == {"protein_g": 28}


def test_reasoning_is_removed_before_reading() -> None:
    """Le monologue contient lui-même des accolades : le lire en premier serait fatal."""
    raw = (
        '<think>Je vois du riz. Le format demandé est {"protein_g": …} donc '
        'je dois écrire un objet.</think>\n{"protein_g": 21}'
    )

    assert first_json_object(raw) == {"protein_g": 21}


def test_an_unclosed_reasoning_tag_takes_everything_after_it() -> None:
    """Réponse coupée en plein raisonnement : il n'y a rien à sauver après l'ouverture."""
    raw = '{"protein_g": 21}<think>Attends, en fait le poulet fait plutôt'

    # L'objet **avant** l'ouverture reste lisible ; ce qui suit est écarté.
    assert first_json_object(raw) == {"protein_g": 21}
    assert "Attends" not in strip_reasoning(raw)


def test_a_truncated_object_yields_nothing() -> None:
    """`L12-16` : JSON tronqué. **Rien n'est complété** — un objet partiel serait inventé."""
    raw = '{"protein_g": 32, "added_sugar_g": 12, "calories": 6'

    assert first_json_object(raw) is None


def test_a_truncated_object_after_a_valid_one_does_not_hide_it() -> None:
    raw = '{"protein_g": 32} puis {"calories": 6'

    assert first_json_object(raw) == {"protein_g": 32}


def test_nested_objects_are_returned_whole() -> None:
    """L'équilibrage compte les accolades : une expression régulière s'arrêterait trop tôt."""
    raw = '{"repas": {"protein_g": 32}, "note": "estimation"}'

    assert first_json_object(raw) == {"repas": {"protein_g": 32}, "note": "estimation"}


def test_braces_inside_strings_do_not_end_the_object() -> None:
    raw = '{"comment": "riz {complet}", "protein_g": 12}'

    assert first_json_object(raw) == {"comment": "riz {complet}", "protein_g": 12}


def test_an_escaped_quote_does_not_end_the_string() -> None:
    raw = r'{"comment": "poulet \"fermier\"", "protein_g": 40}'

    assert first_json_object(raw) == {"comment": 'poulet "fermier"', "protein_g": 40}


def test_an_invalid_object_does_not_hide_a_valid_one_further_on() -> None:
    """Un modèle bavard donne parfois un exemple mal formé avant sa vraie réponse."""
    raw = "Exemple : {'protein_g': 30,} — et voici la réponse : {\"protein_g\": 33}"

    assert first_json_object(raw) == {"protein_g": 33}


def test_a_closing_brace_alone_is_prose_not_json() -> None:
    raw = 'Fin de l\'analyse } puis {"protein_g": 15}'

    assert first_json_object(raw) == {"protein_g": 15}


def test_a_json_array_is_not_an_object() -> None:
    """La couche IA attend un objet : un tableau n'a pas les clés qu'on lui demandera."""
    assert first_json_object("[1, 2, 3]") is None


def test_prose_without_json_yields_nothing() -> None:
    assert first_json_object("Je ne peux pas analyser cette image, désolé.") is None
