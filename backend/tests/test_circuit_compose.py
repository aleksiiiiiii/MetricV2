"""La composition assistée d'un circuit — `/activite/creer` (§5 de `refonte-activite.md`).

Le partage du travail est celui du dépôt : **le modèle propose, le serveur relit,
l'utilisateur ajuste, l'appui écrit.** Ce fichier vérifie les deux premiers tiers, et
surtout la seule chose qui ne se rattrape pas — **rien n'est écrit**.

Les autres familles portent ce que la relecture protège : un nom hors catalogue est
signalé et non écarté, un nombre hors bornes est ramené et non rejeté, un exercice sans
nom est écarté et se dit.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.domains.activity import composer
from app.storage.files import FileStore
from tests.fake_openrouter import FakeOpenRouter
from tests.fake_webdav import FakeWebDav

ACTIVITY = "/api/activity"
SETTINGS_FILE = "Metric/settings/settings.csv"

#: Une réponse plausible d'un modèle : deux exercices, un en répétitions, un au temps.
ANSWER: dict[str, Any] = {
    "name": "Bras — 30 min",
    "rounds": 4,
    "round_rest_s": 60,
    "exercises": [
        {"name": "push-up", "muscle_group": "pectoraux", "reps": 12, "rest_s": 20},
        {"name": "plank", "muscle_group": "abdos", "duration_s": 40, "rest_s": 20},
    ],
}


def compose(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    return client.post(f"{ACTIVITY}/circuits/propose", json={"wish": "", **fields}, headers=auth)


def prompt_of(openrouter: FakeOpenRouter) -> str:
    """La consigne réellement partie au modèle."""
    return str(openrouter.calls[-1].prompt)


# ── 1. Rien n'est écrit (**R5**) ──────────────────────


def test_composing_writes_absolutely_nothing(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """**Le test qui porte la phase.** La proposition s'affiche, s'ajuste, et c'est
    l'appui sur « Enregistrer » qui écrit — par `POST /circuits`, qui ne connaît pas l'IA.

    Un circuit à dix exercices se corrige mal une fois écrit : c'est toute la raison pour
    laquelle cette route ne touche pas au stockage.
    """
    openrouter.say(json.dumps(ANSWER))
    before = dict(dav.files)

    response = compose(ai_app_client, auth, wish="bras 30 min")

    assert response.status_code == 200, response.text
    assert dict(dav.files) == before


def test_a_proposal_comes_back_whole_and_adjustable(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """Nom, rounds, repos entre rounds, et une ligne par exercice — la forme exacte que
    `POST /circuits` accepte, pour que l'écran n'ait rien à retraduire."""
    openrouter.say(json.dumps(ANSWER))

    body = compose(ai_app_client, auth, wish="bras 30 min").json()

    assert body["name"] == "Bras — 30 min"
    assert (body["rounds"], body["round_rest_s"]) == (4, 60)
    assert [item["name"] for item in body["exercises"]] == ["push-up", "plank"]
    assert (body["exercises"][0]["reps"], body["exercises"][0]["duration_s"]) == (12, None)
    assert (body["exercises"][1]["reps"], body["exercises"][1]["duration_s"]) == (None, 40)


def test_a_proposal_can_be_saved_by_the_ordinary_route(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """La proposition et la saisie manuelle passent par **la même** écriture.

    Une route d'écriture propre à l'IA aurait deux jeux de bornes à tenir, et le jour où
    elles divergent c'est la proposition qui écrit ce que le formulaire refuse.
    """
    openrouter.say(json.dumps(ANSWER))
    proposal = compose(ai_app_client, auth, wish="bras").json()

    response = ai_app_client.post(
        f"{ACTIVITY}/circuits",
        json={
            "name": proposal["name"],
            "rounds": proposal["rounds"],
            "round_rest_s": proposal["round_rest_s"],
            "exercises": [
                {
                    "name": item["name"],
                    "muscle_group": item["muscle_group"],
                    **({"reps": item["reps"]} if item["reps"] else {}),
                    **({"duration_s": item["duration_s"]} if item["duration_s"] else {}),
                    "rest_s": item["rest_s"],
                }
                for item in proposal["exercises"]
            ],
        },
        headers=auth,
    )

    assert response.status_code == 201, response.text


# ── 2. Ce que l'utilisateur n'a pas à taper (§5 bis) ──


def test_the_owned_equipment_travels_with_the_request(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """**R8** : proposer un développé couché à qui n'a ni banc ni barre est pire que de ne
    rien proposer. Le matériel part sans qu'on ait à le retaper à chaque demande."""
    dav.seed(SETTINGS_FILE, "key,value\nprofile_equipment,dumbbell\n")
    openrouter.say(json.dumps(ANSWER))

    compose(ai_app_client, auth, wish="bras")

    consigne = prompt_of(openrouter)
    assert "dumbbell" in consigne
    # Le catalogue montré est filtré : aucun nom exclusivement à la barre ne doit y être.
    assert "barbell squat" not in consigne


def test_the_bodyweight_names_are_always_offered(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """325 des 1324 exercices sont au poids du corps. Les retirer parce qu'on a coché
    « dumbbell » viderait le tabata de sa moitié la plus utile."""
    dav.seed(SETTINGS_FILE, "key,value\nprofile_equipment,dumbbell\n")
    openrouter.say(json.dumps(ANSWER))

    compose(ai_app_client, auth, wish="bras")

    assert "push-up" in prompt_of(openrouter)


def test_the_constraints_travel_in_their_own_heading(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Une épaule sensible n'est pas une préférence qu'on arbitre contre le reste : elle a
    sa rubrique, et son titre dit « à respecter »."""
    dav.seed(SETTINGS_FILE, "key,value\nprofile_constraints,épaule droite sensible\n")
    openrouter.say(json.dumps(ANSWER))

    compose(ai_app_client, auth, wish="haut du corps")

    consigne = prompt_of(openrouter)
    assert "Contraintes à respecter" in consigne
    assert "épaule droite sensible" in consigne


def test_an_empty_wish_is_still_answerable(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """« Fais-moi 30 minutes » devient répondable parce que le profil suffit. Exiger une
    phrase serait un formulaire de plus pour rien."""
    openrouter.say(json.dumps(ANSWER))

    response = compose(ai_app_client, auth)

    assert response.status_code == 200, response.text
    assert "Groupes musculaires" in prompt_of(openrouter)


def test_the_proposal_says_what_it_leans_on(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Une suggestion dont on voit l'argument se discute ; une suggestion nue se croit ou
    se rejette."""
    dav.seed(SETTINGS_FILE, "key,value\nprofile_equipment,dumbbell\n")
    openrouter.say(json.dumps(ANSWER))

    basis = compose(ai_app_client, auth, wish="bras").json()["basis"]

    assert any("dumbbell" in line for line in basis)


# ── 3. Ce que la relecture protège ────────────────────


def test_a_name_outside_the_catalogue_is_flagged_not_dropped(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """La spécification de Cadence le dit : un nom hors catalogue reste valide, la séance
    tourne, simplement sans démonstration.

    L'écarter coûterait un exercice pour un défaut d'affichage ; le taire promettrait une
    image qui n'arrivera pas.
    """
    openrouter.say(
        json.dumps(
            {
                **ANSWER,
                "exercises": [
                    {"name": "Pompes sautées maison", "muscle_group": "pectoraux", "reps": 10},
                    {"name": "push-up", "muscle_group": "pectoraux", "reps": 12},
                ],
            }
        )
    )

    exercises = compose(ai_app_client, auth, wish="pecs").json()["exercises"]

    assert [item["name"] for item in exercises] == ["Pompes sautées maison", "push-up"]
    assert [item["illustrated"] for item in exercises] == [False, True]


def test_a_number_out_of_bounds_is_brought_back_not_refused(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """C'est ce que fait l'application cible — `circuit_link.normalise` borne déjà rounds
    et repos. Refuser ici produirait un refus que Cadence contredirait à l'ouverture du
    lien, et l'utilisateur verrait deux applications se disputer."""
    openrouter.say(json.dumps({**ANSWER, "rounds": 400, "round_rest_s": 99999}))

    body = compose(ai_app_client, auth, wish="bras").json()

    assert body["rounds"] == 99
    assert body["round_rest_s"] == 900


def test_an_exercise_without_a_name_is_dropped_and_said(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """La seule colonne dont rien ne peut tenir lieu : un exercice sans nom n'affiche rien,
    ne se corrige pas, et ne dit pas ce qu'il était.

    L'écarter en silence laisserait croire que le modèle n'a proposé que le reste.
    """
    openrouter.say(
        json.dumps(
            {
                **ANSWER,
                "exercises": [
                    {"name": "  ", "muscle_group": "abdos", "reps": 10},
                    {"name": "plank", "muscle_group": "abdos", "duration_s": 40},
                ],
            }
        )
    )

    body = compose(ai_app_client, auth, wish="abdos").json()

    assert [item["name"] for item in body["exercises"]] == ["plank"]
    assert body["dropped"] == ["exercice 1 : sans nom"]


def test_an_unknown_muscle_group_falls_back_instead_of_losing_the_exercise(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """Le groupe est un champ que l'écran affiche **proposé et ajustable** (§5), et
    « autre » s'y voit comme un champ à corriger. Écarter l'exercice perdrait un mouvement
    pour une étiquette."""
    openrouter.say(
        json.dumps({**ANSWER, "exercises": [{"name": "plank", "muscle_group": "core", "reps": 10}]})
    )

    exercises = compose(ai_app_client, auth, wish="abdos").json()["exercises"]

    assert exercises[0]["muscle_group"] == "autre"


def test_a_proposal_with_nothing_usable_is_refused_with_a_code(
    ai_app_client: TestClient, openrouter: FakeOpenRouter, auth: dict[str, str]
) -> None:
    """La chaîne a fonctionné, la réponse ne contient rien qu'on puisse afficher. Un `503`
    dirait « réessaie plus tard » ; ici, réessayer ou composer à la main sont deux
    conduites également valables — et c'est ce que dit `422`."""
    openrouter.say(json.dumps({"name": "Vide", "exercises": []}))

    response = compose(ai_app_client, auth, wish="bras")

    assert response.status_code == 422
    assert response.json()["code"] == "ai_unreadable"


# ── 4. Le module pur, sur des valeurs fixes ───────────


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"reps": 12, "duration_s": 40}, (12, None)),
        ({"duration_s": 40}, (None, 40)),
        ({}, (None, composer.DEFAULT_DURATION_S)),
        ({"reps": 0}, (None, composer.DEFAULT_DURATION_S)),
    ],
)
def test_reps_wins_over_duration_and_absence_falls_back(
    entry: dict[str, Any], expected: tuple[int | None, int | None]
) -> None:
    """`reps` fait autorité, `duration_s` est subordonnée — la règle du domaine, écrite sur
    `CircuitExerciseRow`. Une seconde règle ici trancherait autrement le jour où le cas
    arrive.

    Ni l'un ni l'autre retombe sur la durée par défaut du domaine : ce n'est pas une valeur
    inventée au sens de l'invariant, elle arrive **marquée comme proposée** dans un champ
    qui s'ajuste.
    """
    proposal, _dropped = composer.read_proposal(
        {"exercises": [{"name": "plank", "muscle_group": "abdos", **entry}]},
        groups={"abdos"},
        fallback_group="autre",
    )

    assert proposal is not None
    assert (proposal.exercises[0].reps, proposal.exercises[0].duration_s) == expected


def test_more_exercises_than_a_session_are_cut_and_said() -> None:
    """Douze mouvements à quatre rounds font déjà quarante-huit passages : au-delà, le
    modèle a compris autre chose que « une séance »."""
    proposal, dropped = composer.read_proposal(
        {
            "exercises": [
                {"name": f"plank {index}", "muscle_group": "abdos", "reps": 10}
                for index in range(composer.MAX_EXERCISES + 2)
            ]
        },
        groups={"abdos"},
        fallback_group="autre",
    )

    assert proposal is not None
    assert len(proposal.exercises) == composer.MAX_EXERCISES
    assert len(dropped) == 2


async def test_the_pure_module_reads_no_user_file(store: FileStore) -> None:
    """Module pur, comme `circuit_link.py` : il répond à l'identique sur un stockage vide.

    C'est ce qui permet de tester la relecture sur des valeurs fixes, sans monter une
    application.
    """
    del store
    consigne = composer.build_prompt(
        demande="bras", materiel=[], groupes=["abdos"], negliges=[], contraintes=""
    )

    assert "Non renseigné" in consigne
    assert "Aucun historique." in consigne
