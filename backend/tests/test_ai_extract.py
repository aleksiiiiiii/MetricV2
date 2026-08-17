"""Extraction du JSON d'une réponse de modèle (`IA-05`, `L12-16`).

Chaque cas de ce fichier a été vu en vrai sur un modèle gratuit. Ce n'est pas une liste de
malveillances imaginées : c'est ce que rendent les modèles quand on leur demande du JSON.
"""

from __future__ import annotations

import json
import random

from app.domains.ai.extract import ReplyStream, first_json_object, strip_reasoning


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


# ── La lecture au fil de l'eau (§7.1 du plan de coaching) ──
#
# Le réseau coupe où il veut. Chaque cas se joue donc **caractère par caractère** : servir
# de gros morceaux éviterait toutes les coupures intéressantes et rendrait ces tests muets
# sur exactement ce qu'ils doivent couvrir.


def jouer(texte: str, *, assured: bool = False, taille: int = 1, limite: int | None = None) -> str:
    """Fait passer `texte` par le lecteur, découpé, et rend ce qui a été diffusé."""
    lecteur = ReplyStream(assured=assured, limit=limite)
    return "".join(lecteur.feed(texte[i : i + taille]) for i in range(0, len(texte), taille))


def test_an_empty_need_proves_the_pass_is_final_and_the_reply_flows() -> None:
    """Le cas normal : le modèle ne demande rien, donc sa réponse ne sera pas remplacée."""
    raw = json.dumps({"need": [], "actions": [], "reply": "Charge 67,5 kg.", "remember": []})

    assert jouer(raw) == "Charge 67,5 kg."


def test_a_pass_that_asks_for_a_slice_says_nothing() -> None:
    """L'objection qui interdisait de diffuser, et la raison d'être de tout ce dessin.

    Une seconde passe remplace **entièrement** la première. Ce qui serait diffusé ici
    devrait être effacé quinze secondes plus tard.
    """
    raw = json.dumps({"need": ["progression_charges"], "reply": "Je regarde.", "remember": []})

    assert jouer(raw) == ""


def test_the_second_pass_needs_no_proof_because_there_is_no_third() -> None:
    """`assured` : le plafond de `IA-16` rend la preuve inutile sur la passe finale."""
    raw = json.dumps({"need": ["progression_charges"], "reply": "Je regarde.", "remember": []})

    assert jouer(raw, assured=True) == "Je regarde."


def test_a_reply_written_before_need_is_not_streamed() -> None:
    """Le repli, silencieux par construction.

    Rien ne garantit qu'un modèle respecte l'ordre demandé — le lot 5 le garantira par
    `json_schema`. En attendant, une réponse qu'on ne peut pas prouver finale ne s'affiche
    pas : le pire cas est le comportement d'avant ce lot, jamais un effacement.
    """
    raw = json.dumps({"reply": "Hors contrat.", "need": [], "remember": []})

    assert jouer(raw) == ""


def test_escapes_survive_a_cut_anywhere() -> None:
    """Un morceau réseau tombe entre `\\` et `u`, ou au milieu des quatre chiffres.

    Décoder un préfixe coupé là lèverait, ou rendrait un caractère faux. Le cas mêle
    guillemet échappé, retour à la ligne, antislash littéral et deux caractères non ASCII
    que `json.dumps` écrit en `\\uXXXX`.
    """
    texte = 'Il a dit "oui".\nPuis \\ — 82,4 kg é'
    raw = json.dumps({"need": [], "reply": texte, "remember": []})

    assert jouer(raw) == texte


def test_any_random_split_yields_the_same_text() -> None:
    """La propriété qui compte : le découpage ne doit rien changer au texte rendu."""
    texte = 'Ligne 1\nLigne "2" \\ fin é—'
    raw = json.dumps({"need": [], "reply": texte, "remember": []})
    alea = random.Random(7)

    for _ in range(200):
        lecteur = ReplyStream()
        rendu = ""
        position = 0
        while position < len(raw):
            taille = alea.randint(1, 7)
            rendu += lecteur.feed(raw[position : position + taille])
            position += taille
        assert rendu == texte


def test_the_preview_never_outgrows_what_will_be_stored() -> None:
    """`limit` vient de `MAX_REPLY` : un aperçu plus long serait raccourci sous les yeux
    au moment où la réponse définitive arrive."""
    raw = json.dumps({"need": [], "reply": "Charge 67,5 kg lundi.", "remember": []})

    assert jouer(raw, limite=10) == "Charge 67,"


def test_a_scalar_field_before_the_reply_does_not_derail_the_reader() -> None:
    """Un nombre ou un booléen se termine sur le séparateur et non sur une fermeture."""
    raw = '{"need": [], "score": 12, "flag": true, "reply": "Après les scalaires.", "x": null}'

    assert jouer(raw) == "Après les scalaires."


def test_braces_inside_a_string_do_not_count_as_nesting() -> None:
    """Sinon une réponse qui cite du JSON refermerait l'objet trop tôt."""
    raw = json.dumps({"need": [], "title": 'un {"faux": "objet"}', "reply": "Vraie réponse."})

    assert jouer(raw) == "Vraie réponse."
