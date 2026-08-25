"""Circuits ouverts dans Cadence Tabata (**D2**, **D3**, **D4**, **D7**).

Les familles suivent `docs/patron-domaine.md` §4. Deux lui sont propres, et portent les
décisions du lot :

* **Un tabata est du sport** — le déclarer fait écrit une séance *et* ses séries, avec le
  groupe musculaire choisi à la création du circuit. Rien ne reste à côté du système.
* **Le lien vient du serveur** — le client reçoit une adresse faite, ou `null`, et jamais
  de quoi en fabriquer une.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.validation import today_local
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

ACTIVITY = "/api/activity"
CIRCUITS_FILE = "Metric/activity/circuits.csv"
ITEMS_FILE = "Metric/activity/circuit_exercises.csv"
WORKOUTS_FILE = "Metric/activity/workouts.csv"
LOG_FILE = "Metric/activity/exercise_log.csv"
SETTINGS_FILE = "Metric/settings/settings.csv"

BASE = "https://cadence.exemple.fr"


@pytest.fixture
def app_client(client: TestClient, store: FileStore) -> TestClient:
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


@pytest.fixture
def linked(dav: FakeWebDav) -> None:
    """Une adresse de Cadence réglée. Sans elle, aucun circuit ne porte de lien."""
    dav.seed(SETTINGS_FILE, f"key,value\ncadence_base_url,{BASE}\n")


def payload(**fields: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Haut du corps",
        "rounds": 4,
        "round_rest_s": 60,
        "exercises": [
            {"name": "Push-Ups Classic", "muscle_group": "pectoraux", "reps": 15, "rest_s": 20},
            {"name": "Plank", "muscle_group": "abdos", "duration_s": 45, "rest_s": 15},
        ],
    }
    body.update(fields)
    return body


def create(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    response = client.post(f"{ACTIVITY}/circuits", json=payload(**fields), headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


def listing(client: TestClient, auth: dict[str, str]) -> Any:
    response = client.get(f"{ACTIVITY}/circuits", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


# ── Le fichier (`STO-02`, `STO-04`) ───────────────────


def test_a_circuit_is_written_across_two_readable_files(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Deux fichiers plutôt qu'une liste dans une cellule : c'est la seule forme qui reste
    lisible dans un tableur, et c'est le même partage que `workouts` / `exercise_log`."""
    create(app_client, auth)

    circuits = dav.content_of(CIRCUITS_FILE)
    items = dav.content_of(ITEMS_FILE)

    assert circuits.splitlines()[0] == "id,name,rounds,round_rest_s,created,note"
    assert items.splitlines()[0] == "circuit_id,position,name,muscle_group,duration_s,reps,rest_s"
    assert "Haut du corps" in circuits


def test_a_timed_exercise_carries_the_sentinel_in_the_file(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`-1` **dit** « au temps » à qui ouvre le fichier ; une cellule vide laisserait
    deviner. La sentinelle vit ici, jamais dans `exercise_log.csv` (**D3**)."""
    create(app_client, auth)

    lines = dav.content_of(ITEMS_FILE).splitlines()

    assert lines[1].endswith("Push-Ups Classic,pectoraux,20,15,20")  # reps = 15
    assert lines[2].endswith("Plank,abdos,45,-1,15")  # au temps


def test_the_position_is_written_and_not_deduced_from_the_file_order(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """C'est ce qui permet de trier `circuit_exercises.csv` dans un tableur sans
    intervertir les exercices de tous les circuits."""
    create(app_client, auth)

    columns = [line.split(",") for line in dav.content_of(ITEMS_FILE).splitlines()[1:]]

    assert [row[1] for row in columns] == ["1", "2"]


# ── Le lien vient du serveur (**D7**) ─────────────────


def test_the_server_hands_over_a_finished_link(
    app_client: TestClient, auth: dict[str, str], linked: None
) -> None:
    """Le client ne fabrique rien. Le suffixe `x` distingue quinze répétitions de quinze
    secondes, et c'est la faute la plus fréquente de la spécification."""
    circuit = create(app_client, auth)

    assert circuit["url"] == (f"{BASE}?w=Haut+du+corps~4~60~Push-Ups+Classic:15x:20~Plank:45s:15")


def test_without_a_base_address_there_is_no_link_at_all(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`null`, et pas une adresse relative de repli : c'est un état que l'écran sait dire
    (**D1**), là où un lien tronqué serait un bouton qui mène nulle part."""
    circuit = create(app_client, auth)

    assert circuit["url"] is None
    assert listing(app_client, auth)["linkable"] is False


def test_the_listing_says_whether_a_link_is_possible_even_when_empty(
    app_client: TestClient, auth: dict[str, str], linked: None
) -> None:
    """Sur une liste vide, l'écran doit distinguer « aucun circuit » de « aucune
    adresse » : ces deux états ne proposent pas le même geste suivant."""
    empty = listing(app_client, auth)

    assert empty["circuits"] == []
    assert empty["linkable"] is True


def test_the_api_never_shows_the_sentinel(app_client: TestClient, auth: dict[str, str]) -> None:
    """`-1` est une convention de stockage. À l'API, c'est le champ à `null` qui dit la
    nature de l'autre — l'écran n'a aucune sentinelle à interpréter."""
    circuit = create(app_client, auth)

    reps, timed = circuit["exercises"]
    assert (reps["reps"], reps["duration_s"]) == (15, None)
    assert (timed["reps"], timed["duration_s"]) == (None, 45)


# ── L'estimation, et son droit de se dire exacte (§7) ─


def test_a_repetition_makes_the_duration_an_estimate(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Personne ne sait combien de temps prend une série. `exact` est ce que l'écran
    traduit en `~`, et l'invariant « aucune valeur inventée » dit la même chose."""
    circuit = create(app_client, auth)

    assert circuit["exact"] is False


def test_a_fully_timed_circuit_has_an_exact_duration(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    circuit = create(
        app_client,
        auth,
        rounds=2,
        round_rest_s=60,
        exercises=[{"name": "Plank", "muscle_group": "abdos", "duration_s": 60, "rest_s": 30}],
    )

    # (60 + 30) × 2 + 60 × 1 = 240 s
    assert circuit["exact"] is True
    assert circuit["estimated_duration_min"] == pytest.approx(4.0)


# ── Bornes refusées (`API-06`) ────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        {"rounds": 0},
        {"rounds": 100},
        {"round_rest_s": 901},
        {"exercises": []},
        {"exercises": [{"name": "Plank", "muscle_group": "abdos"}]},  # ni temps ni répétitions
        {
            "exercises": [{"name": "Plank", "muscle_group": "abdos", "duration_s": 30, "reps": 12}]
        },  # les deux
        {"exercises": [{"name": "Plank", "muscle_group": "abdos", "duration_s": 1000}]},
        {"exercises": [{"name": "Plank", "muscle_group": "abdos", "reps": 0}]},
        {"exercises": [{"name": "", "muscle_group": "abdos", "duration_s": 30}]},
        {"exercises": [{"name": "Plank", "duration_s": 30}]},  # groupe manquant
        {"exercises": [{"name": "Plank", "muscle_group": "cardio", "duration_s": 30}]},
    ],
)
def test_an_aberrant_circuit_is_refused(
    app_client: TestClient, auth: dict[str, str], body: dict[str, Any]
) -> None:
    response = app_client.post(f"{ACTIVITY}/circuits", json=payload(**body), headers=auth)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# ── Correction et garde anti-conflit (`STO-05`) ───────


def test_a_correction_keeps_the_stable_id_and_the_creation_day(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Une correction ne fait pas naître un nouveau circuit : le journal s'y rattache."""
    circuit = create(app_client, auth)

    response = app_client.patch(
        f"{ACTIVITY}/circuits/{circuit['id']}",
        json=payload(name="Haut du corps, plus court", rounds=3),
        headers={**auth, "If-Match": circuit["token"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["circuit_id"] == circuit["circuit_id"]
    assert response.json()["created"] == circuit["created"]
    assert response.json()["rounds"] == 3


def test_a_correction_replaces_the_exercises_wholesale(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """On ne sait pas apparier un exercice renommé avec celui qu'il remplace ; deviner
    ferait pire qu'une réécriture franche."""
    circuit = create(app_client, auth)

    app_client.patch(
        f"{ACTIVITY}/circuits/{circuit['id']}",
        json=payload(exercises=[{"name": "Burpees", "muscle_group": "jambes", "duration_s": 30}]),
        headers={**auth, "If-Match": circuit["token"]},
    )

    lines = dav.content_of(ITEMS_FILE).splitlines()[1:]
    assert len(lines) == 1
    assert "Burpees" in lines[0]


@pytest.mark.parametrize("headers", [{}, {"If-Match": "perime"}])
def test_a_change_without_a_fresh_token_is_refused(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav, headers: dict[str, str]
) -> None:
    """Un `If-Match` absent est un **conflit**, jamais une permission."""
    circuit = create(app_client, auth)
    before = dav.content_of(CIRCUITS_FILE)

    response = app_client.patch(
        f"{ACTIVITY}/circuits/{circuit['id']}", json=payload(), headers={**auth, **headers}
    )

    assert response.status_code == 409
    assert dav.content_of(CIRCUITS_FILE) == before


def test_deleting_a_circuit_purges_its_exercises(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    circuit = create(app_client, auth)

    response = app_client.delete(
        f"{ACTIVITY}/circuits/{circuit['id']}", headers={**auth, "If-Match": circuit["token"]}
    )

    assert response.status_code == 204
    assert dav.content_of(ITEMS_FILE).splitlines()[1:] == []


def test_deleting_one_circuit_leaves_the_other_ones_exercises_alone(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """La purge porte sur l'identifiant **stable**, pas sur la position : sinon supprimer
    le premier circuit emporterait les exercices du second."""
    first = create(app_client, auth)
    create(app_client, auth, name="Jambes")

    app_client.delete(
        f"{ACTIVITY}/circuits/{first['id']}", headers={**auth, "If-Match": first["token"]}
    )

    remaining = listing(app_client, auth)["circuits"]
    assert len(remaining) == 1
    assert len(remaining[0]["exercises"]) == 2


# ── Deux mondes séparés (**D2**, **D3**) ──────────────


def test_declaring_a_circuit_done_writes_a_workout_and_its_sets(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """**Le test qui porte D3.** Un tabata *est* du sport : il entre dans `workouts.csv`
    **et** dans le journal de charge, comme n'importe quelle séance."""
    circuit = create(app_client, auth)

    response = app_client.post(
        f"{ACTIVITY}/circuits/{circuit['id']}/done", json={"duration_min": 18}, headers=auth
    )

    assert response.status_code == 201, response.text
    workout = response.json()
    assert workout["type"] == "HIIT"
    assert workout["source"] == "cadence"
    assert workout["date"] == today_local().isoformat()
    assert workout["note"] == "Haut du corps"
    assert [entry["exercise_name"] for entry in workout["exercises"]] == [
        "Push-Ups Classic",
        "Plank",
    ]
    assert "Push-Ups Classic" in dav.content_of(LOG_FILE)


def test_each_round_counts_as_one_set(app_client: TestClient, auth: dict[str, str]) -> None:
    """Quatre rounds, c'est quatre séries de chaque exercice — c'est ce qu'on a fait."""
    circuit = create(app_client, auth)

    response = app_client.post(
        f"{ACTIVITY}/circuits/{circuit['id']}/done", json={"duration_min": 18}, headers=auth
    )

    assert [entry["sets"] for entry in response.json()["exercises"]] == [4, 4]


def test_a_timed_exercise_carries_the_sentinel_into_the_log(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`-1` dans `exercise_log.csv` aussi, et par un point d'entrée à part : desserrer la
    borne `Reps` la desserrerait pour la saisie manuelle, où ce serait une faute de frappe
    silencieuse dans un journal de charge."""
    circuit = create(app_client, auth)

    response = app_client.post(
        f"{ACTIVITY}/circuits/{circuit['id']}/done", json={"duration_min": 18}, headers=auth
    )

    assert [entry["reps"] for entry in response.json()["exercises"]] == [15, -1]


def test_a_bodyweight_circuit_adds_no_tonnage(app_client: TestClient, auth: dict[str, str]) -> None:
    """`weight_kg = 0` est le poids du corps, pas une absence. Le tonnage d'un tabata est
    donc nul — ce qui est vrai. Ce qu'il apporte, ce sont ses séries par groupe."""
    circuit = create(app_client, auth)

    response = app_client.post(
        f"{ACTIVITY}/circuits/{circuit['id']}/done", json={"duration_min": 18}, headers=auth
    )

    assert response.json()["volume_kg"] == 0


def test_the_muscle_groups_travel_all_the_way_to_the_log(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """C'est la colonne qui relie les deux mondes : sans elle, tous les tabatas finiraient
    dans « autre » et l'équilibre par groupe cesserait de vouloir dire quelque chose."""
    circuit = create(app_client, auth)

    app_client.post(
        f"{ACTIVITY}/circuits/{circuit['id']}/done", json={"duration_min": 18}, headers=auth
    )

    log = dav.content_of(LOG_FILE)
    assert "pectoraux" in log
    assert "abdos" in log


def test_the_duration_is_the_one_confirmed_and_not_the_estimate(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """**D4** : l'estimation est proposée à l'écran, corrigée au doigt, et c'est le chiffre
    confirmé qui entre dans le volume hebdomadaire."""
    circuit = create(app_client, auth)

    response = app_client.post(
        f"{ACTIVITY}/circuits/{circuit['id']}/done",
        json={"duration_min": 23, "rpe": 8},
        headers=auth,
    )

    assert response.json()["duration_min"] == pytest.approx(23)
    assert response.json()["rpe"] == 8


def test_a_completion_without_a_duration_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """La durée n'est pas déduite d'un champ absent : sur une séance en répétitions,
    l'écrire en silence mettrait une valeur inventée dans les agrégats."""
    circuit = create(app_client, auth)

    response = app_client.post(f"{ACTIVITY}/circuits/{circuit['id']}/done", json={}, headers=auth)

    assert response.status_code == 422


def test_the_exercises_join_the_catalogue_on_the_first_completion(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Sans ça le journal porterait un `exercise_id` vide, et « Progression des charges »
    ignorerait ces exercices. Le catalogue ne bouge pas tant que rien n'est fait."""
    circuit = create(app_client, auth)
    assert app_client.get(f"{ACTIVITY}/exercises", headers=auth).json() == []

    app_client.post(
        f"{ACTIVITY}/circuits/{circuit['id']}/done", json={"duration_min": 18}, headers=auth
    )

    catalogue = app_client.get(f"{ACTIVITY}/exercises", headers=auth).json()
    assert {item["name"]: item["muscle_group"] for item in catalogue} == {
        "Push-Ups Classic": "pectoraux",
        "Plank": "abdos",
    }


def test_a_second_completion_reuses_the_catalogue_entry(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Deux graphies du même mouvement ne doivent pas donner deux lignes de catalogue :
    l'historique de charge se couperait en deux au premier changement d'orthographe."""
    circuit = create(app_client, auth)
    body = {"duration_min": 18}

    app_client.post(f"{ACTIVITY}/circuits/{circuit['id']}/done", json=body, headers=auth)
    app_client.post(f"{ACTIVITY}/circuits/{circuit['id']}/done", json=body, headers=auth)

    assert len(app_client.get(f"{ACTIVITY}/exercises", headers=auth).json()) == 2


def test_an_existing_catalogue_entry_is_recognised_whatever_its_spelling(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`fold` ignore casse et accents — la même reconnaissance que la relecture d'une note
    manuscrite, et pas une seconde règle inventée ici.

    Le groupe déjà choisi n'est **pas** écrasé : le catalogue appartient à l'utilisateur,
    un circuit n'est pas une autorité sur lui.
    """
    app_client.post(
        f"{ACTIVITY}/exercises", json={"name": "PLANK", "muscle_group": "jambes"}, headers=auth
    )
    circuit = create(app_client, auth)

    app_client.post(
        f"{ACTIVITY}/circuits/{circuit['id']}/done", json={"duration_min": 18}, headers=auth
    )

    catalogue = app_client.get(f"{ACTIVITY}/exercises", headers=auth).json()
    assert {item["name"] for item in catalogue} == {"PLANK", "Push-Ups Classic"}
    assert next(item for item in catalogue if item["name"] == "PLANK")["muscle_group"] == "jambes"


def test_a_name_that_only_differs_by_a_missing_space_is_a_different_exercise(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`fold` n'est pas une distance d'édition : « push ups » et « Push-Ups » ne se
    rejoignent pas, parce que le tiret disparaît sans laisser d'espace. C'est le
    comportement de `notes.py` depuis toujours, et le reproduire vaut mieux qu'une seconde
    règle de reconnaissance qui divergerait au premier cas limite."""
    app_client.post(
        f"{ACTIVITY}/exercises",
        json={"name": "push ups classic", "muscle_group": "épaules"},
        headers=auth,
    )
    circuit = create(app_client, auth)

    app_client.post(
        f"{ACTIVITY}/circuits/{circuit['id']}/done", json={"duration_min": 18}, headers=auth
    )

    names = {item["name"] for item in app_client.get(f"{ACTIVITY}/exercises", headers=auth).json()}
    assert names == {"push ups classic", "Push-Ups Classic", "Plank"}


# ── Relire un lien collé ──────────────────────────────


def test_a_pasted_link_becomes_a_circuit(
    app_client: TestClient, auth: dict[str, str], linked: None
) -> None:
    """Ce qui récupère les séances construites dans Cadence avant que Metric sache en
    faire — sinon il faudrait les ressaisir une à une."""
    url = f"{BASE}?w=Full+Body~3~45~Crunchs:30s:10~Push-Ups+Classic:15x:20"

    response = app_client.post(f"{ACTIVITY}/circuits/import", json={"url": url}, headers=auth)

    assert response.status_code == 201, response.text
    circuit = response.json()
    assert circuit["name"] == "Full Body"
    assert circuit["rounds"] == 3
    assert [item["name"] for item in circuit["exercises"]] == ["Crunchs", "Push-Ups Classic"]
    # Un lien Cadence ne porte aucun groupe : `autre`, et l'écran laisse corriger.
    assert {item["muscle_group"] for item in circuit["exercises"]} == {"autre"}
    # Le lien reconstruit est celui qu'on a collé : l'aller-retour tient jusqu'à l'API.
    assert circuit["url"] == url


def test_an_unreadable_link_is_refused_with_a_code(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Un lien illisible n'est pas une panne mais une saisie à corriger. Le client décide
    sur le code, jamais sur le message (`API-07`)."""
    response = app_client.post(
        f"{ACTIVITY}/circuits/import", json={"url": f"{BASE}?w=A~8~60"}, headers=auth
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# ── Ordre et lignes héritées (`STO-04`) ───────────────


def test_the_listing_shows_the_newest_first(app_client: TestClient, auth: dict[str, str]) -> None:
    """Deux circuits créés le même jour gardent l'ordre d'écriture, le plus récent devant."""
    create(app_client, auth, name="Premier")
    create(app_client, auth, name="Second")

    assert [item["name"] for item in listing(app_client, auth)["circuits"]] == [
        "Second",
        "Premier",
    ]


def test_a_circuit_line_mangled_by_hand_never_breaks_the_screen(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Toutes les colonnes portent un défaut : le fichier s'ouvre dans un tableur, et une
    cellule vidée à la main y est une possibilité normale."""
    dav.seed(CIRCUITS_FILE, "id,name,rounds,round_rest_s,created,note\nabc,,,,,\n")

    circuits = listing(app_client, auth)["circuits"]

    assert len(circuits) == 1
    assert circuits[0]["exercises"] == []
    # Aucun exercice nommé : pas de lien, même avec une adresse réglée.
    assert circuits[0]["url"] is None


def test_orphan_exercise_lines_are_not_attached_to_an_unnamed_circuit(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Un circuit sans identifiant ne réclame rien : sinon toutes les lignes orphelines
    d'un fichier corrigé à la main lui seraient rattachées d'un coup."""
    dav.seed(CIRCUITS_FILE, "id,name,rounds,round_rest_s,created,note\n,Sans id,1,0,,\n")
    dav.seed(
        ITEMS_FILE,
        "circuit_id,position,name,muscle_group,duration_s,reps,rest_s\n,1,Plank,abdos,30,-1,0\n",
    )

    assert listing(app_client, auth)["circuits"][0]["exercises"] == []


# ── Les noms proposés à la saisie ─────────────────────


def test_the_cadence_names_come_first_and_are_marked(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Les 35 noms d'abord, dans leur ordre : ce sont les seuls qui affichent une
    illustration, et c'est le service qu'on rend en premier."""
    proposed = app_client.get(f"{ACTIVITY}/circuits/exercises", headers=auth).json()

    assert proposed[0] == {"name": "Bicycle Crunches", "illustrated": True, "muscle_group": None}
    assert sum(1 for item in proposed if item["illustrated"]) == 35


def test_the_users_own_exercises_follow_with_their_group(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    app_client.post(
        f"{ACTIVITY}/exercises",
        json={"name": "Développé couché", "muscle_group": "pectoraux"},
        headers=auth,
    )

    proposed = app_client.get(f"{ACTIVITY}/circuits/exercises", headers=auth).json()

    assert proposed[-1] == {
        "name": "Développé couché",
        "illustrated": False,
        "muscle_group": "pectoraux",
    }


def test_a_name_shared_by_both_catalogues_appears_once(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Proposer les deux graphies laisserait choisir celle qui n'a pas d'illustration.
    La reconnaissance passe par `fold`, celle du reste du domaine."""
    app_client.post(
        f"{ACTIVITY}/exercises", json={"name": "plank", "muscle_group": "abdos"}, headers=auth
    )

    proposed = app_client.get(f"{ACTIVITY}/circuits/exercises", headers=auth).json()
    planks = [item for item in proposed if item["name"].lower() == "plank"]

    assert len(planks) == 1
    # C'est la graphie de Cadence qui gagne — elle seule affiche une illustration —, et
    # elle repart avec le groupe musculaire que l'utilisateur avait déjà choisi.
    assert planks[0] == {"name": "Plank", "illustrated": True, "muscle_group": "abdos"}


def test_the_route_is_not_swallowed_by_the_row_id_one(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """« exercises » n'est pas un entier : déclarée après `/circuits/{row_id}`, cette
    route répondrait `422` au lieu de la liste."""
    response = app_client.get(f"{ACTIVITY}/circuits/exercises", headers=auth)

    assert response.status_code == 200, response.text
