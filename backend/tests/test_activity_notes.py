"""Lecture d'une séance écrite en clair, ou photographiée (`C07`).

Ce que ce fichier défend n'est pas « la lecture marche » mais **rien ne s'écrit sans
validation**, et surtout : aucune entrée de catalogue n'est créée, renommée ou fusionnée
en silence. Une fusion erronée est difficile à défaire et pollue l'historique.
"""

from __future__ import annotations

import io
import json
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

from app.core.text import fold
from app.domains.activity.notes import match, read_lines, read_load
from app.domains.activity.schemas import Exercise
from tests.fake_openrouter import FakeOpenRouter

ACTIVITY = "/api/activity"


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (80, 80), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def catalogue(*entries: tuple[str, str, list[str]]) -> list[Exercise]:
    return [
        Exercise(
            id=index,
            token=f"t{index}",
            exercise_id=f"e{index}",
            name=name,
            muscle_group=group,
            aliases=aliases,
        )
        for index, (name, group, aliases) in enumerate(entries)
    ]


# ── Le repli des noms ─────────────────────────────────


def test_two_spellings_of_the_same_move_fold_to_the_same_thing() -> None:
    assert fold("Dev. Couché") == fold("dev couche")
    assert fold("développé  couché") == fold("Développé couché")


def test_folding_is_not_a_fuzzy_match() -> None:
    """Rapprocher deux noms « proches » fusionnerait deux mouvements distincts."""
    assert fold("développé couché") != fold("développé incliné")


# ── Les charges ───────────────────────────────────────


def test_a_load_in_kilos_is_read() -> None:
    assert read_load("60kg") == (60.0, None)
    assert read_load("62,5 kg") == (62.5, None)
    assert read_load("60") == (60.0, None)


def test_bodyweight_is_zero_and_zero_is_a_measurement() -> None:
    """`ACT-07` : zéro est une valeur du domaine, pas une absence de valeur."""
    assert read_load("poids du corps") == (0.0, None)
    assert read_load("PDC") == (0.0, None)


def test_a_foreign_unit_stays_empty_and_says_why() -> None:
    """Convertir ici produirait un nombre d'apparence honnête que personne n'a soulevé."""
    value, why = read_load("135 lbs")

    assert value is None
    assert why is not None
    assert "lbs" in why


def test_an_absent_load_is_empty_without_a_reason() -> None:
    assert read_load("") == (None, None)


# ── La relecture d'une réponse ────────────────────────


def test_unknown_reps_stay_empty_rather_than_invented() -> None:
    """« 3xmax » porte des répétitions réelles mais inconnues."""
    lines = read_lines({"exercises": [{"name": "Tractions", "sets": 3, "reps": "max"}]})

    assert lines[0].sets == 3
    assert lines[0].reps is None


def test_an_unknown_muscle_group_falls_back_to_autre() -> None:
    """Le domaine n'a que neuf groupes ; un dixième casserait les statistiques."""
    lines = read_lines({"exercises": [{"name": "Squat", "muscle_group": "quadriceps"}]})

    assert lines[0].muscle_group == "autre"


def test_a_line_without_a_name_is_dropped() -> None:
    assert read_lines({"exercises": [{"sets": 3, "reps": 8}]}) == []


# ── Le rapprochement au catalogue ─────────────────────


def test_an_exact_name_attaches_without_touching_the_catalogue() -> None:
    lines = match(
        read_lines({"exercises": [{"name": "développé couché"}]}),
        catalogue(("Développé couché", "pectoraux", [])),
    )

    assert lines[0].status == "known"
    assert lines[0].exercise_id == "e0"
    # Le nom du catalogue s'impose, y compris sur la casse.
    assert lines[0].name == "Développé couché"


def test_a_known_alias_attaches_silently() -> None:
    """C'est ce qui rend la lecture de plus en plus silencieuse au fil des séances."""
    lines = match(
        read_lines({"exercises": [{"name": "dev couché"}]}),
        catalogue(("Développé couché", "pectoraux", ["dev couché"])),
    )

    assert lines[0].status == "known"
    assert lines[0].name == "Développé couché"


def test_a_spelling_the_model_matches_is_proposed_as_an_alias() -> None:
    """Le nom du catalogue s'impose, et la graphie de la note devient l'alias **proposé**.

    Le rapprochement vient du modèle, pas d'une distance d'édition calculée ici : une
    mesure de similarité qui se trompe fusionnerait deux mouvements distincts, et rien ne
    le déferait. La proposition, elle, se valide ligne à ligne avant d'écrire.
    """
    lines = match(
        read_lines({"exercises": [{"name": "DC barre", "match": "Développé couché"}]}),
        catalogue(("Développé couché", "pectoraux", [])),
    )

    assert lines[0].status == "alias"
    assert lines[0].name == "Développé couché"
    assert lines[0].alias_of == "DC barre"
    assert lines[0].exercise_id == "e0"


def test_a_match_the_catalogue_does_not_carry_is_ignored() -> None:
    """Un modèle nomme volontiers une entrée qui n'existe pas."""
    lines = match(
        read_lines({"exercises": [{"name": "Hip thrust", "match": "Soulevé de hanches"}]}),
        catalogue(("Développé couché", "pectoraux", [])),
    )

    assert lines[0].status == "new"
    assert lines[0].exercise_id is None


def test_an_unknown_exercise_is_proposed_for_creation() -> None:
    lines = match(
        read_lines({"exercises": [{"name": "Hip thrust", "muscle_group": "fessiers"}]}),
        catalogue(("Développé couché", "pectoraux", [])),
    )

    assert lines[0].status == "new"
    assert lines[0].exercise_id is None
    # Le groupe déduit accompagne la proposition : c'est ce que la création demandera.
    assert lines[0].muscle_group == "fessiers"


def test_the_catalogue_group_wins_over_the_one_the_model_guessed() -> None:
    """La note dit ce que la main a écrit ; le catalogue dit ce que l'historique connaît."""
    lines = match(
        read_lines({"exercises": [{"name": "Squat", "muscle_group": "fessiers"}]}),
        catalogue(("Squat", "jambes", [])),
    )

    assert lines[0].muscle_group == "jambes"


# ── Bout en bout ──────────────────────────────────────


def note(client: TestClient, auth: dict[str, str], **body: Any) -> Any:
    return client.post(f"{ACTIVITY}/notes/read", data={"text": "…", **body}, headers=auth)


def test_reading_a_note_writes_absolutely_nothing(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """Le contrat du lot : un tableau, et pas une ligne écrite."""
    openrouter.say(
        json.dumps(
            {
                "exercises": [
                    {"name": "développé couché", "sets": 4, "reps": 8, "weight": "60kg"},
                    {"name": "tractions", "sets": 3, "reps": "max", "weight": "poids du corps"},
                ]
            }
        )
    )

    response = note(ai_app_client, auth, text="dev couché 4x8 60kg / tractions 3xmax")

    assert response.status_code == 200
    lines = response.json()["lines"]
    assert len(lines) == 2
    assert lines[1]["weight_kg"] == 0
    # Le catalogue est vide : les deux sont proposés à la création, aucun n'existe.
    assert {line["status"] for line in lines} == {"new"}
    assert ai_app_client.get(f"{ACTIVITY}/exercises", headers=auth).json() == []


def test_a_note_that_says_nothing_is_refused_rather_than_emptied(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """Mieux vaut le dire que d'ouvrir un tableau vide en le présentant comme une lecture."""
    openrouter.say(json.dumps({"exercises": [], "readable": False}))

    response = note(ai_app_client, auth, text="il faisait beau")

    assert response.status_code == 422
    assert response.json()["code"] == "ai_unreadable"


def test_a_note_needs_a_text_or_a_photo(ai_app_client: TestClient, auth: dict[str, str]) -> None:
    response = ai_app_client.post(f"{ACTIVITY}/notes/read", data={"text": "  "}, headers=auth)

    assert response.status_code == 422


def test_a_photo_goes_through_the_same_model(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """L'OCR n'est pas une brique à part : c'est la même consigne, avec une image."""
    openrouter.say(json.dumps({"exercises": [{"name": "squat", "sets": 5, "reps": 5}]}))

    response = ai_app_client.post(
        f"{ACTIVITY}/notes/read",
        files={"photo": ("carnet.png", png(), "image/png")},
        headers=auth,
    )

    assert response.status_code == 200
    assert openrouter.calls[0].with_image is True


# ── Les alias, une fois validés ───────────────────────


def test_an_alias_is_added_without_touching_the_name(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    created = store_client.post(
        f"{ACTIVITY}/exercises",
        json={"name": "Développé couché", "muscle_group": "pectoraux"},
        headers=auth,
    ).json()

    response = store_client.post(
        f"{ACTIVITY}/exercises/{created['exercise_id']}/aliases",
        json={"alias": "dev couché"},
        headers=auth,
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Développé couché"
    assert response.json()["aliases"] == ["dev couché"]


def test_adding_a_known_alias_twice_changes_nothing(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """L'opération doit être sûre à rejouer : une validation qui part deux fois arrive."""
    created = store_client.post(
        f"{ACTIVITY}/exercises",
        json={"name": "Développé couché", "muscle_group": "pectoraux"},
        headers=auth,
    ).json()
    url = f"{ACTIVITY}/exercises/{created['exercise_id']}/aliases"

    store_client.post(url, json={"alias": "dev couché"}, headers=auth)
    store_client.post(url, json={"alias": "Dev Couché"}, headers=auth)

    assert store_client.post(url, json={"alias": "dev couché"}, headers=auth).json()["aliases"] == [
        "dev couché"
    ]


def test_correcting_an_exercise_keeps_its_aliases(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """Le formulaire du catalogue ne parle pas d'alias, il ne doit pas les effacer."""
    created = store_client.post(
        f"{ACTIVITY}/exercises",
        json={"name": "Developpé couché", "muscle_group": "pectoraux"},
        headers=auth,
    ).json()
    store_client.post(
        f"{ACTIVITY}/exercises/{created['exercise_id']}/aliases",
        json={"alias": "dev couché"},
        headers=auth,
    )

    fresh = store_client.get(f"{ACTIVITY}/exercises", headers=auth).json()[0]
    corrected = store_client.patch(
        f"{ACTIVITY}/exercises/{fresh['id']}",
        json={"name": "Développé couché", "muscle_group": "pectoraux"},
        headers={**auth, "If-Match": fresh["token"]},
    )

    assert corrected.status_code == 200
    assert corrected.json()["aliases"] == ["dev couché"]


def test_removing_an_exercise_takes_its_aliases_with_it(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """C'est la raison du choix d'une colonne plutôt que d'un fichier à part.

    Un `exercise_aliases.csv` laisserait des orphelins, et un nom retiré du catalogue
    continuerait d'être reconnu à la saisie.
    """
    created = store_client.post(
        f"{ACTIVITY}/exercises",
        json={"name": "Développé couché", "muscle_group": "pectoraux"},
        headers=auth,
    ).json()
    store_client.post(
        f"{ACTIVITY}/exercises/{created['exercise_id']}/aliases",
        json={"alias": "dev couché"},
        headers=auth,
    )

    fresh = store_client.get(f"{ACTIVITY}/exercises", headers=auth).json()[0]
    store_client.delete(
        f"{ACTIVITY}/exercises/{fresh['id']}", headers={**auth, "If-Match": fresh["token"]}
    )

    assert store_client.get(f"{ACTIVITY}/exercises", headers=auth).json() == []


def test_a_semicolon_never_enters_an_alias(store_client: TestClient, auth: dict[str, str]) -> None:
    """C'est le séparateur : un alias qui en porterait un couperait la cellule en deux."""
    created = store_client.post(
        f"{ACTIVITY}/exercises",
        json={"name": "Squat", "muscle_group": "jambes", "aliases": ["squat;barre"]},
        headers=auth,
    )

    assert created.json()["aliases"] == ["squat barre"]
