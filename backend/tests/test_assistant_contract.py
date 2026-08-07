"""Le contrat élargi de l'assistant : actions, tranches demandées, titre (`IA-14`).

**Tout ce fichier tourne sans réseau et sans application.** `conversation.py` est un module
pur : une consigne à assembler, une réponse à relire. C'est ce qui permet de couvrir ici
les cas qu'un modèle rend une fois sur cent — un objet là où on attend une liste, un nom
inventé, quinze actions d'un coup — sans dépendre de ce qu'un modèle gratuit aura décidé
de faire ce jour-là.

Ce que ce fichier **ne** couvre pas : qu'une action nommée existe, que ses arguments soient
les bons, qu'elle soit permise. C'est l'affaire de l'exécuteur, qui connaît le catalogue.
La séparation est volontaire et c'est elle qui garde ce module pur.
"""

from __future__ import annotations

from typing import Any

from app.domains.assistant.conversation import (
    build_prompt,
    read_actions,
    read_need,
    read_title,
)
from app.domains.assistant.schemas import MAX_ACTIONS, MAX_NEED

CONTEXT = ["Nous sommes le vendredi 07/08/2026", "Séances par semaine : 1,8"]
MEMORY = ["blessure — Genou droit sensible"]

CATALOGUE = [
    "weight.add — noter une pesée. args : date (AAAA-MM-JJ), weight_kg (nombre)",
    "meal.add — noter un repas. args : meal_type, protein_g",
]
SLICES = ["exercises", "meals.today"]


def prompt(**kwargs: Any) -> str:
    base: dict[str, Any] = {"question": "Où j'en suis ?", "context": CONTEXT, "memory": MEMORY}
    return build_prompt(**{**base, **kwargs})


# ── 1. La consigne n'invite à agir que si c'est possible ──


def test_without_a_catalogue_the_prompt_never_mentions_actions() -> None:
    """C'est le comportement voulu, pas une commodité de test.

    Inviter à agir sans rien d'exécutable ne produirait que des promesses — « je l'ai
    ajouté » sans que rien ne soit écrit est pire que « je ne sais pas faire ».
    """
    text = prompt()

    assert '"actions"' not in text
    assert '"need"' not in text
    assert "Ce que tu peux faire" not in text


def test_the_catalogue_is_inserted_verbatim() -> None:
    """Le module ne connaît aucun nom d'action : il insère ce que le catalogue a rendu.

    C'est ce qui garde `conversation.py` pur, et le catalogue seul autorité sur ce qui
    existe. Un nom qui change ne se retrouve donc jamais à deux endroits.
    """
    text = prompt(actions=CATALOGUE, slices=SLICES)

    for line in CATALOGUE:
        assert line in text
    assert "exercises, meals.today" in text


def test_the_prompt_presents_the_empty_list_as_the_normal_case() -> None:
    """Un modèle à qui on offre une possibilité la prend.

    Sans cette insistance, chaque « où j'en suis ? » repartirait avec une séance ajoutée.
    C'est le garde-fou le moins cher et le plus efficace du lot.
    """
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert "Liste vide le plus" in text
    assert "une question est une question, pas une instruction" in text


def test_the_medical_guard_forbids_acting_not_only_advising() -> None:
    """`IA-12` s'étend : un assistant qui peut écrire ne doit pas agir sur une douleur.

    La consigne interdisait déjà de diagnostiquer. Elle doit maintenant interdire de
    *réagir* — créer une semaine de repos parce qu'on lui a parlé d'un genou serait une
    prescription déguisée en mise à jour de planning.
    """
    text = prompt(actions=CATALOGUE, slices=SLICES)

    assert "Aucune action à la suite d'une douleur" in text


def test_the_title_is_only_asked_when_a_thread_opens() -> None:
    """Le redemander à chaque tour inviterait le modèle à rebaptiser une discussion."""
    assert '"title"' in prompt(naming=True)
    assert '"title"' not in prompt()


# ── 2. Les actions relues ─────────────────────────────


def test_a_well_formed_action_comes_back() -> None:
    actions = read_actions({"actions": [{"name": "weight.add", "args": {"weight_kg": 82.4}}]})

    assert len(actions) == 1
    assert actions[0].name == "weight.add"
    assert actions[0].args == {"weight_kg": 82.4}


def test_an_answer_without_actions_yields_none() -> None:
    """Le cas normal, et de loin."""
    assert read_actions({"reply": "Tu tournes à 1,8 séance."}) == []


def test_a_single_object_is_accepted_where_a_list_was_asked() -> None:
    """Un modèle rend parfois un objet là où la consigne demande une liste.

    L'accepter coûte deux lignes ; le refuser coûterait l'action *et* l'appel qui l'a
    produite. Même tolérance que pour `remember`.
    """
    actions = read_actions({"actions": {"name": "water.add", "args": {"volume_ml": 500}}})

    assert [item.name for item in actions] == ["water.add"]


def test_an_action_without_a_name_is_dropped() -> None:
    """Sans nom, il n'y a rien à exécuter — et rien à refuser non plus."""
    assert read_actions({"actions": [{"args": {"weight_kg": 82.4}}]}) == []


def test_an_action_without_args_keeps_an_empty_dict() -> None:
    """L'exécuteur validera ; il ne doit pas avoir à distinguer « absent » de « vide »."""
    actions = read_actions({"actions": [{"name": "goal.create"}]})

    assert actions[0].args == {}


def test_args_that_are_not_an_object_become_an_empty_dict() -> None:
    """Une chaîne à la place des arguments est une réponse mal formée, pas une charge."""
    actions = read_actions({"actions": [{"name": "weight.add", "args": "82,4 kg"}]})

    assert actions[0].args == {}


def test_actions_are_bounded() -> None:
    """« Range mon mois » se traduit en cinquante actions.

    La borne est un garde-fou de sécurité plus que de coût : le tour où le modèle se
    trompe est exactement celui où on ne veut pas qu'il écrive vingt lignes.
    """
    many = [{"name": "weight.add", "args": {"n": index}} for index in range(20)]

    assert len(read_actions({"actions": many})) == MAX_ACTIONS


def test_a_malformed_entry_does_not_lose_the_others() -> None:
    """Une réponse à moitié bonne vaut mieux qu'un échange perdu."""
    actions = read_actions(
        {"actions": ["pas un objet", {"name": "water.add"}, 42, {"name": "meal.add"}]}
    )

    assert [item.name for item in actions] == ["water.add", "meal.add"]


# ── 3. Les tranches demandées (`IA-09`) ───────────────


def test_a_requested_slice_must_be_one_we_offered() -> None:
    """La garantie de `IA-09` : le modèle choisit **dans ce qu'on lui a dit pouvoir
    demander**, il ne nomme pas un fichier.

    Sans ce filtre, « need »: ["/etc/passwd"] ou ["tout"] deviendrait une lecture.
    """
    need = read_need({"need": ["exercises", "inventé", "meals.today"]}, available=SLICES)

    assert need == ["exercises", "meals.today"]


def test_a_single_string_is_accepted_where_a_list_was_asked() -> None:
    assert read_need({"need": "exercises"}, available=SLICES) == ["exercises"]


def test_a_slice_asked_twice_is_only_read_once() -> None:
    assert read_need({"need": ["exercises", "exercises"]}, available=SLICES) == ["exercises"]


def test_requested_slices_are_bounded() -> None:
    """Au-delà, le modèle réclame le dossier entier — ce que `IA-09` interdit."""
    available = [f"tranche{index}" for index in range(10)]

    assert len(read_need({"need": available}, available=available)) == MAX_NEED


def test_no_need_at_all_is_the_normal_case() -> None:
    assert read_need({"reply": "…"}, available=SLICES) == []


# ── 4. Le titre du fil ────────────────────────────────


def test_the_model_names_the_thread() -> None:
    assert read_title({"title": "Stagnation du développé couché"}, fallback="…") == (
        "Stagnation du développé couché"
    )


def test_an_empty_title_falls_back_to_the_question() -> None:
    """Un titre vide vaut moins que la question : c'est sur lui qu'on retrouve un fil."""
    assert read_title({"title": "   "}, fallback="Où j'en suis ?") == "Où j'en suis ?"


def test_a_missing_title_falls_back_too() -> None:
    assert read_title({}, fallback="Où j'en suis ?") == "Où j'en suis ?"


def test_a_title_is_bounded_and_collapsed() -> None:
    """Un titre sur trois lignes ne se lit pas dans une liste."""
    title = read_title({"title": "un  titre\nsur   plusieurs\nlignes " * 20}, fallback="…")

    assert "\n" not in title
    assert "  " not in title
    assert len(title) <= 80
