"""Les charges des exercices de tabata (**C1** à **C7**).

Le plan est dans `docs/charges.md`. Ce qui est vérifié ici couvre les huit familles de
`docs/patron-domaine.md` §4, plus les deux décisions qui coûtent le plus cher à casser :
la charge remonte dans le **lien** (**C7**), et elle ne touche **pas** au tonnage (**C4**).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.validation import today_local
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

ACTIVITY = "/api/activity"
LOADS_FILE = "Metric/activity/circuit_loads.csv"
LOG_FILE = "Metric/activity/circuit_load_log.csv"
EXERCISE_LOG_FILE = "Metric/activity/exercise_log.csv"
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
    dav.seed(SETTINGS_FILE, f"key,value\ncadence_base_url,{BASE}\n")


@pytest.fixture
def circuit(app_client: TestClient, auth: dict[str, str]) -> Any:
    """Une séance de deux exercices — sans elle, la page n'a rien à montrer."""
    response = app_client.post(
        f"{ACTIVITY}/circuits",
        json={
            "name": "Haut du corps",
            "rounds": 4,
            "round_rest_s": 60,
            "exercises": [
                {"name": "Rowing", "muscle_group": "dos", "reps": 12, "rest_s": 30},
                {"name": "Gainage", "muscle_group": "abdos", "duration_s": 45, "rest_s": 15},
            ],
        },
        headers=auth,
    )
    assert response.status_code == 201, response.text
    return response.json()


def loads(client: TestClient, auth: dict[str, str]) -> Any:
    response = client.get(f"{ACTIVITY}/loads", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def card(client: TestClient, auth: dict[str, str], name: str) -> Any:
    return next(item for item in loads(client, auth)["loads"] if item["name"] == name)


def declare(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    response = client.post(f"{ACTIVITY}/loads", json=fields, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


# ── 1. Le fichier (`STO-02`) ──────────────────────────


def test_a_load_is_written_across_two_readable_files(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav, circuit: Any
) -> None:
    """Deux fichiers : la valeur courante, qui se corrige, et le journal, qui ne se
    corrige jamais. En-tête explicite, accents intacts."""
    declare(app_client, auth, name="Rowing", weight_kg=12)

    current = dav.content_of(LOADS_FILE)
    journal = dav.content_of(LOG_FILE)

    assert current.splitlines()[0] == "name,weight_kg,bodyweight,updated"
    assert journal.splitlines()[0] == "name,date,weight_kg,bodyweight"
    assert "Rowing,12.0,false," in current
    assert f"Rowing,{today_local().isoformat()},12.0,false" in journal


def test_bodyweight_and_a_load_never_coexist_on_a_line(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav, circuit: Any
) -> None:
    """Une ligne ne peut pas dire « poids du corps à 12 kg » : déclarer l'un efface
    l'autre, et c'est le service qui le tient."""
    created = declare(app_client, auth, name="Rowing", weight_kg=12)
    app_client.patch(
        f"{ACTIVITY}/loads/{created['id']}",
        json={"name": "Rowing", "bodyweight": True},
        headers={**auth, "If-Match": created["token"]},
    )

    line = next(row for row in dav.content_of(LOADS_FILE).splitlines() if row.startswith("Rowing"))

    assert line == "Rowing,,true," + today_local().isoformat()


# ── 2. Bornes refusées ────────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        {"name": "Rowing"},
        {"name": "Rowing", "weight_kg": 12, "bodyweight": True},
        {"name": "Rowing", "weight_kg": 0},
        {"name": "Rowing", "weight_kg": -5},
        {"name": "Rowing", "weight_kg": 1001},
        {"name": "", "weight_kg": 12},
    ],
)
def test_a_contradictory_or_out_of_range_declaration_is_refused(
    app_client: TestClient, auth: dict[str, str], circuit: Any, body: dict[str, Any]
) -> None:
    """`weight_kg = 0` est refusé ici alors qu'il signifie « poids du corps » dans
    `exercise_log.csv` : le poids du corps a son propre drapeau, et deux façons de dire la
    même chose laisseraient l'écran choisir laquelle afficher."""
    assert app_client.post(f"{ACTIVITY}/loads", json=body, headers=auth).status_code == 422


def test_declaring_twice_is_a_conflict_and_not_a_second_line(
    app_client: TestClient, auth: dict[str, str], circuit: Any
) -> None:
    """Deux lignes pour un nom feraient deux charges, et la lecture n'en garderait qu'une
    sans rien dire de l'autre."""
    declare(app_client, auth, name="Rowing", weight_kg=12)

    again = app_client.post(
        f"{ACTIVITY}/loads", json={"name": "Rowing", "weight_kg": 16}, headers=auth
    )

    assert again.status_code == 409, again.text


# ── 3. La garde anti-conflit (`STO-05`) ───────────────


def test_a_correction_without_its_token_is_refused_and_changes_nothing(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav, circuit: Any
) -> None:
    """Un `If-Match` absent est un **conflit**, jamais une permission."""
    created = declare(app_client, auth, name="Rowing", weight_kg=12)
    before = dav.content_of(LOADS_FILE)

    refused = app_client.patch(
        f"{ACTIVITY}/loads/{created['id']}", json={"name": "Rowing", "weight_kg": 16}, headers=auth
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "conflict"
    assert dav.content_of(LOADS_FILE) == before


def test_a_stale_token_is_refused_and_the_file_stays_intact(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav, circuit: Any
) -> None:
    created = declare(app_client, auth, name="Rowing", weight_kg=12)
    app_client.patch(
        f"{ACTIVITY}/loads/{created['id']}",
        json={"name": "Rowing", "weight_kg": 16},
        headers={**auth, "If-Match": created["token"]},
    )
    after_first = dav.content_of(LOADS_FILE)

    refused = app_client.patch(
        f"{ACTIVITY}/loads/{created['id']}",
        json={"name": "Rowing", "weight_kg": 20},
        headers={**auth, "If-Match": created["token"]},
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "conflict"
    assert dav.content_of(LOADS_FILE) == after_first


# ── 5. Indicateurs, y compris sur historique vide ─────


def test_the_page_lists_only_what_a_tabata_uses(
    app_client: TestClient, auth: dict[str, str], circuit: Any
) -> None:
    """La liste vient de `circuit_exercises.csv` et d'elle seule : un exercice de
    musculation n'y entre pas, sa charge est déjà journalisée série par série."""
    app_client.post(
        f"{ACTIVITY}/exercises",
        json={"name": "Développé couché", "muscle_group": "pectoraux"},
        headers=auth,
    )

    names = [item["name"] for item in loads(app_client, auth)["loads"]]

    assert names == ["Gainage", "Rowing"]


def test_an_exercise_never_declared_shows_no_value_at_all(
    app_client: TestClient, auth: dict[str, str], circuit: Any
) -> None:
    """L'état `unset` porte `null` partout : un zéro passerait pour une mesure, et l'écran
    affiche un tiret. `id` et `token` à `null` disent aussi qu'il n'y a pas de ligne.

    Les deux chiffres du coach suivent la même règle : `null` et non `0`, parce qu'aucun
    changement n'est au journal — « montée il y a 0 jour » serait faux, et « 0 séance
    tenue » supposerait une charge à tenir.
    """
    assert card(app_client, auth, "Rowing") == {
        "id": None,
        "token": None,
        "name": "Rowing",
        "state": "unset",
        "weight_kg": None,
        "updated": None,
        "circuits": 1,
        "days_since_change": None,
        "sessions_since": None,
    }


def test_the_three_states_are_decided_by_the_server(
    app_client: TestClient, auth: dict[str, str], circuit: Any
) -> None:
    """« pas encore renseigné » n'est pas « poids du corps ». L'écran groupe sur cette
    étiquette ; la lui faire déduire d'un `null` lui confierait la règle."""
    declare(app_client, auth, name="Rowing", weight_kg=12)
    declare(app_client, auth, name="Gainage", bodyweight=True)

    assert card(app_client, auth, "Rowing")["state"] == "weighted"
    assert card(app_client, auth, "Gainage")["state"] == "bodyweight"


def test_the_detail_answers_on_an_exercise_with_no_history(
    app_client: TestClient, auth: dict[str, str], circuit: Any
) -> None:
    """Historique vide : l'API répond, elle n'échoue pas — et la ligne de points fait
    quand même ses trente jours."""
    view = app_client.get(f"{ACTIVITY}/loads/detail?name=Rowing", headers=auth).json()

    assert view["state"] == "unset"
    assert view["history"] == []
    assert len(view["sessions"]) == 30
    assert {day["count"] for day in view["sessions"]} == {0}
    assert view["circuits"] == ["Haut du corps"]


def test_an_exercise_outside_any_circuit_has_no_detail(
    app_client: TestClient, auth: dict[str, str], circuit: Any
) -> None:
    assert app_client.get(f"{ACTIVITY}/loads/detail?name=Squat", headers=auth).status_code == 404


# ── 6. Fenêtres de calcul — la borne exacte ───────────


def test_the_dot_row_is_exactly_thirty_days_ending_today(
    app_client: TestClient, auth: dict[str, str], circuit: Any
) -> None:
    """Trente entrées, la dernière étant le jour du **serveur**. L'écran ne connaît ni la
    longueur de la fenêtre ni la date d'aujourd'hui."""
    view = app_client.get(f"{ACTIVITY}/loads/detail?name=Rowing", headers=auth).json()
    days = [day["date"] for day in view["sessions"]]

    assert len(days) == 30
    assert days[-1] == today_local().isoformat()
    assert days == sorted(days)


def test_a_declared_session_lights_its_day_and_only_its_day(
    app_client: TestClient, auth: dict[str, str], circuit: Any
) -> None:
    """Le compte est celui des **séances**, pas des lignes de journal."""
    app_client.post(
        f"{ACTIVITY}/circuits/{circuit['id']}/done", json={"duration_min": 20}, headers=auth
    )

    view = app_client.get(f"{ACTIVITY}/loads/detail?name=Rowing", headers=auth).json()
    lit = [day for day in view["sessions"] if day["count"]]

    assert len(lit) == 1
    assert lit[0] == {"date": today_local().isoformat(), "count": 1}


# ── 7. Ordre ──────────────────────────────────────────


def test_the_history_is_read_in_order_not_assumed_to_be_in_it(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav, circuit: Any
) -> None:
    """Le fichier peut être réordonné dans un tableur, et une courbe qui repart en arrière
    ne se voit pas comme un défaut de lecture."""
    dav.seed(
        LOG_FILE,
        "name,date,weight_kg,bodyweight\n"
        "Rowing,2026-08-20,14.0,False\n"
        "Rowing,2026-08-02,10.0,False\n"
        "Rowing,2026-08-11,12.0,False\n",
    )

    view = app_client.get(f"{ACTIVITY}/loads/detail?name=Rowing", headers=auth).json()

    assert [point["weight_kg"] for point in view["history"]] == [10.0, 12.0, 14.0]


def test_what_remains_to_declare_comes_first(
    app_client: TestClient, auth: dict[str, str], circuit: Any
) -> None:
    """C'est le seul endroit de la page où il reste un geste à faire."""
    declare(app_client, auth, name="Rowing", weight_kg=12)

    states = [item["state"] for item in loads(app_client, auth)["loads"]]

    assert states == ["unset", "weighted"]


# ── C2 — le journal ne retient que ce qui a bougé ─────


def test_re_saving_the_same_value_adds_no_point_to_the_curve(
    app_client: TestClient, auth: dict[str, str], circuit: Any
) -> None:
    """Sans cette garde, réenregistrer une carte sans y toucher poserait un point de plus
    au même niveau — une évolution qui n'a pas eu lieu."""
    created = declare(app_client, auth, name="Rowing", weight_kg=12)
    app_client.patch(
        f"{ACTIVITY}/loads/{created['id']}",
        json={"name": "Rowing", "weight_kg": 12},
        headers={**auth, "If-Match": created["token"]},
    )

    view = app_client.get(f"{ACTIVITY}/loads/detail?name=Rowing", headers=auth).json()

    assert len(view["history"]) == 1


def test_switching_to_bodyweight_breaks_the_curve_rather_than_dropping_it_to_zero(
    app_client: TestClient, auth: dict[str, str], circuit: Any
) -> None:
    """Zéro serait une charge nulle ; l'absence est autre chose, et la courbe s'interrompt."""
    created = declare(app_client, auth, name="Rowing", weight_kg=12)
    app_client.patch(
        f"{ACTIVITY}/loads/{created['id']}",
        json={"name": "Rowing", "bodyweight": True},
        headers={**auth, "If-Match": created["token"]},
    )

    view = app_client.get(f"{ACTIVITY}/loads/detail?name=Rowing", headers=auth).json()

    assert [point["weight_kg"] for point in view["history"]] == [12.0, None]


# ── C7 — la charge remonte dans le lien ───────────────


def test_the_link_carries_the_load_as_its_fourth_field(
    app_client: TestClient, auth: dict[str, str], linked: None, circuit: Any
) -> None:
    """C'est la raison d'être du lot : la séance ouverte dans Cadence affiche « 12 kg »
    sous « Rowing », sans qu'on ait à s'en souvenir."""
    declare(app_client, auth, name="Rowing", weight_kg=12)

    view = app_client.get(f"{ACTIVITY}/circuits", headers=auth).json()["circuits"][0]

    assert view["url"] == f"{BASE}?w=Haut+du+corps~4~60~Rowing:12x:30:12+kg~Gainage:45s:15"
    # `link_note` est ce que Cadence affichera ; `note` est ce qui a été saisi, et personne
    # n'a rien saisi ici. Les confondre ferait recopier « 12 kg » dans le champ de saisie
    # au premier affichage, et l'enregistrement suivant l'écrirait en dur.
    assert [item["link_note"] for item in view["exercises"]] == ["12 kg", None]
    assert [item["note"] for item in view["exercises"]] == ["", ""]


def test_bodyweight_adds_nothing_to_the_link(
    app_client: TestClient, auth: dict[str, str], linked: None, circuit: Any
) -> None:
    """Un tabata sans charge n'a rien de plus à dire sous le nom de l'exercice, et une
    ligne « poids du corps » sur chaque écran de repos serait du bruit."""
    declare(app_client, auth, name="Rowing", bodyweight=True)

    view = app_client.get(f"{ACTIVITY}/circuits", headers=auth).json()["circuits"][0]

    assert view["url"] == f"{BASE}?w=Haut+du+corps~4~60~Rowing:12x:30~Gainage:45s:15"


def test_changing_a_load_changes_every_circuit_that_uses_it(
    app_client: TestClient, auth: dict[str, str], linked: None, circuit: Any
) -> None:
    """La charge vaut pour l'exercice, pas pour le circuit (**C1**). Le lien est fabriqué
    à la lecture, il n'est stocké nulle part — un changement se voit immédiatement."""
    app_client.post(
        f"{ACTIVITY}/circuits",
        json={
            "name": "Dos",
            "rounds": 2,
            "round_rest_s": 30,
            "exercises": [{"name": "rowing", "muscle_group": "dos", "reps": 10, "rest_s": 20}],
        },
        headers=auth,
    )
    declare(app_client, auth, name="Rowing", weight_kg=12)

    urls = [
        item["url"]
        for item in app_client.get(f"{ACTIVITY}/circuits", headers=auth).json()["circuits"]
    ]

    assert all("12+kg" in url for url in urls)


# ── C4 — le tonnage ne bouge pas ──────────────────────


def test_a_declared_tabata_still_logs_bodyweight(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav, circuit: Any
) -> None:
    """La décision inconfortable du lot, vérifiée pour qu'elle ne change pas par accident :
    `exercise_log.weight_kg` reste à 0, donc `weight_kg × sets × reps` reste à 0 — et un
    gainage au temps (`reps = -1`) ne produit pas de tonnage négatif."""
    declare(app_client, auth, name="Rowing", weight_kg=12)
    app_client.post(
        f"{ACTIVITY}/circuits/{circuit['id']}/done", json={"duration_min": 20}, headers=auth
    )

    written = dav.content_of(EXERCISE_LOG_FILE)

    assert ",12.0," not in written
    assert all(",0.0," in row or "weight_kg" in row for row in written.splitlines() if row.strip())


# ── 9. Quand monter — les deux chiffres du coach (§5 bis) ──
#
# Ils **constatent**, ils ne concluent pas : « trois séances tenues à 10 kg, dernier
# changement il y a 24 jours » est une mesure, la décision appartient à l'utilisateur
# (**R10**). Aucun 1RM, aucun record : un tabata n'a pas de charge maximale lisible.


def test_a_declared_load_says_since_when_it_has_not_moved(
    app_client: TestClient, auth: dict[str, str], circuit: Any
) -> None:
    """Le jour même de la déclaration : zéro jour, et zéro **est** la mesure ici."""
    declare(app_client, auth, name="Rowing", weight_kg=12)

    assert card(app_client, auth, "Rowing")["days_since_change"] == 0


def test_a_session_held_at_that_load_is_counted(
    app_client: TestClient, auth: dict[str, str], circuit: Any
) -> None:
    """**La borne inclut le jour du changement.** La page Charges existe pour remplir le
    4ᵉ champ du lien **avant** la séance (**C7**) : noter 12 kg puis jouer le tabata dans
    la foulée est le geste normal, et les deux tombent le même jour. Les exclure ferait un
    compteur qui n'avance jamais pour qui note sa charge au bon moment."""
    declare(app_client, auth, name="Rowing", weight_kg=12)
    app_client.post(
        f"{ACTIVITY}/circuits/{circuit['id']}/done", json={"duration_min": 20}, headers=auth
    )

    assert card(app_client, auth, "Rowing")["sessions_since"] == 1


def test_a_session_before_the_change_does_not_count_towards_the_new_load(
    app_client: TestClient, auth: dict[str, str], circuit: Any, dav: FakeWebDav
) -> None:
    """C'est tout le sens du chiffre : ce qu'on a tenu **à cette charge**. Compter une
    séance d'avant la hausse ferait croire qu'on est prêt à monter encore."""
    day = today_local()
    dav.seed(
        "Metric/activity/circuit_session_sets.csv",
        "session_id,date,exercise_name,muscle_group,sets,reps\n"
        f"vieille,{day - timedelta(days=10)},Rowing,dos,4,12\n",
    )
    declare(app_client, auth, name="Rowing", weight_kg=12)

    assert card(app_client, auth, "Rowing")["sessions_since"] == 0


def test_re_saving_the_same_load_writes_nothing_the_counter_could_read(
    app_client: TestClient, auth: dict[str, str], circuit: Any, dav: FakeWebDav
) -> None:
    """**Le journal fait autorité, pas `updated`.**

    Rouvrir une carte et réenregistrer sans rien changer n'écrit aucune ligne de journal
    (**C2**). C'est ce qui empêche le compteur de rajeunir : lu dans
    `circuit_loads.updated`, qui bouge à **chaque** écriture, il dirait « changée
    aujourd'hui » à qui n'a rien touché.
    """
    declare(app_client, auth, name="Rowing", weight_kg=12)
    before = card(app_client, auth, "Rowing")

    response = app_client.patch(
        f"{ACTIVITY}/loads/{before['id']}",
        json={"name": "Rowing", "weight_kg": 12},
        headers={**auth, "If-Match": before["token"]},
    )

    assert response.status_code == 200, response.text
    # Une seule ligne de données au journal : c'est elle, et elle seule, que le compteur
    # date. Une seconde ligne au même niveau ferait repartir le compteur de zéro.
    assert len(dav.content_of(LOG_FILE).strip().splitlines()) == 2


def test_the_load_history_is_read_by_its_latest_date_not_its_last_line(
    app_client: TestClient, auth: dict[str, str], circuit: Any, dav: FakeWebDav
) -> None:
    """Le fichier se trie dans un tableur. Un journal réordonné ne doit pas rajeunir une
    charge — c'est la même garde que la courbe du détail, appliquée au compteur."""
    day = today_local()
    dav.seed(
        LOG_FILE,
        "name,date,weight_kg,bodyweight\n"
        f"Rowing,{day - timedelta(days=3)},12.0,false\n"
        f"Rowing,{day - timedelta(days=30)},10.0,false\n",
    )

    assert card(app_client, auth, "Rowing")["days_since_change"] == 3


# ── 10. La note saisie, 4ᵉ champ du lien (`llms.txt` §1) ──
#
# **C7 est révisée par ce lot.** La note n'est plus « fabriquée par le serveur, jamais
# saisie » : elle reste fabriquée ici — le client ne compose toujours aucune URL — mais
# elle peut porter ce que l'application n'a aucun moyen de savoir, « genoux au sol »,
# « tempo lent ». La charge s'y ajoute toute seule.


def created(client: TestClient, auth: dict[str, str], **exercise: Any) -> Any:
    """Un circuit d'un seul exercice, avec ce qu'on veut dessus."""
    body = {
        "name": "Haut du corps",
        "rounds": 4,
        "round_rest_s": 60,
        "exercises": [
            {"name": "Rowing", "muscle_group": "dos", "reps": 12, "rest_s": 30, **exercise}
        ],
    }
    response = client.post(f"{ACTIVITY}/circuits", json=body, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_typed_note_reaches_the_fourth_field_of_the_link(
    app_client: TestClient, auth: dict[str, str], linked: None
) -> None:
    """Ce que l'application n'a aucun moyen de savoir : « genoux au sol » ne se déduit
    d'aucune donnée, et c'est pourtant ce qu'on veut lire sous le nom pendant l'effort."""
    view = created(app_client, auth, note="genoux au sol")

    assert view["url"] == f"{BASE}?w=Haut+du+corps~4~60~Rowing:12x:30:genoux+au+sol"
    assert view["exercises"][0]["note"] == "genoux au sol"
    assert view["exercises"][0]["link_note"] == "genoux au sol"


def test_the_load_comes_first_and_the_note_follows(
    app_client: TestClient, auth: dict[str, str], linked: None
) -> None:
    """**Les deux sur la même ligne, la charge devant.**

    La charge est le chiffre qu'on cherche des yeux entre deux séries ; « tempo lent » se
    relit une fois et se sait. L'inverse ferait chercher le nombre derrière une phrase, sur
    un écran qu'on regarde une seconde.
    """
    created(app_client, auth, note="tempo lent")
    declare(app_client, auth, name="Rowing", weight_kg=12)

    view = app_client.get(f"{ACTIVITY}/circuits", headers=auth).json()["circuits"][0]

    assert view["exercises"][0]["link_note"] == "12 kg · tempo lent"
    # Le champ de saisie ne porte **que** ce qui a été saisi : y recopier la charge la
    # ferait écrire en dur au prochain enregistrement, et elle cesserait de suivre.
    assert view["exercises"][0]["note"] == "tempo lent"


def test_a_note_survives_a_correction_of_the_circuit(
    app_client: TestClient, auth: dict[str, str], linked: None
) -> None:
    """Les exercices sont remplacés en bloc à la correction : la note doit faire
    l'aller-retour comme le reste, sinon corriger un repos effacerait ce qu'on avait
    écrit sur chaque ligne."""
    view = created(app_client, auth, note="genoux au sol")

    response = app_client.patch(
        f"{ACTIVITY}/circuits/{view['id']}",
        json={
            "name": "Haut du corps",
            "rounds": 5,
            "round_rest_s": 60,
            "exercises": [
                {
                    "name": item["name"],
                    "muscle_group": item["muscle_group"],
                    "reps": item["reps"],
                    "rest_s": item["rest_s"],
                    "note": item["note"],
                }
                for item in view["exercises"]
            ],
        },
        headers={**auth, "If-Match": view["token"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["exercises"][0]["note"] == "genoux au sol"


def test_a_note_too_long_for_one_line_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`llms.txt` §11 : « les notes sont courtes : elles s'affichent sur une ligne ». Une
    note qui déborde ne se tronque pas dans Cadence — elle pousse le reste hors de l'écran
    de quelqu'un qui est en train de forcer. La borne est ici parce que c'est ici qu'on
    peut encore la refuser."""
    response = app_client.post(
        f"{ACTIVITY}/circuits",
        json={
            "name": "Haut du corps",
            "rounds": 4,
            "round_rest_s": 60,
            "exercises": [{"name": "Rowing", "muscle_group": "dos", "reps": 12, "note": "x" * 61}],
        },
        headers=auth,
    )

    assert response.status_code == 422


def test_a_pasted_link_still_ignores_the_note(
    app_client: TestClient, auth: dict[str, str], linked: None
) -> None:
    """**C8 tient.** Une note relue peut être celle que le serveur a composée — « 12 kg » —
    et la réimporter comme note saisie l'écrirait en dur, puis la doublerait au prochain
    lien. Elle est ignorée, comme avant ce lot."""
    response = app_client.post(
        f"{ACTIVITY}/circuits/import",
        json={"url": f"{BASE}?w=Test~3~45~Rowing:12x:30:12+kg"},
        headers=auth,
    )

    assert response.status_code == 201, response.text
    assert response.json()["exercises"][0]["note"] == ""
