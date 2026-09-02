"""Les séances tabata — ce qui a eu lieu (`docs/refonte-activite.md` §3, phase 1).

Deux fichiers neufs, `circuit_sessions.csv` et `circuit_session_sets.csv`, et un seul
geste qui les remplit : déclarer un circuit fait. C'est le monde qui restera quand la
musculation historique sera supprimée, et la phase 1 se juge sur une seule chose — **les
deux mondes disent la même séance**, ligne pour ligne.

Les familles sont celles de `docs/patron-domaine.md` §4. Trois ne s'appliquent pas encore,
et les nommer vaut mieux que de les mimer :

* **la garde anti-conflit** (3) — déclarer un circuit fait est une **addition**, pas une
  modification : la route n'exige aucun `If-Match`, et c'est écrit dans son docstring.
  Rien n'est encore corrigible dans ces deux fichiers, donc il n'y a rien à garder ;
* **les fenêtres de calcul** (6) — aucun indicateur n'est calculé sur ces fichiers avant
  la phase 3 bis ;
* **la pagination** (8) — aucune route ne les expose ; les sept consommateurs les liront
  par le service, à la phase 2.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.validation import today_local
from app.domains.activity.models import CircuitExerciseRow, CircuitRow
from app.domains.activity.service import CircuitSessionService
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

ACTIVITY = "/api/activity"
SESSIONS_FILE = "Metric/activity/circuit_sessions.csv"
SETS_FILE = "Metric/activity/circuit_session_sets.csv"
WORKOUTS_FILE = "Metric/activity/workouts.csv"
LOG_FILE = "Metric/activity/exercise_log.csv"

TODAY = today_local()


@pytest.fixture
def app_client(client: TestClient, store: FileStore) -> TestClient:
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


def payload(**fields: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Haut du corps",
        "rounds": 4,
        "round_rest_s": 60,
        "exercises": [
            {"name": "Push-Ups Classic", "muscle_group": "pectoraux", "reps": 15, "rest_s": 20},
            {"name": "Écarté", "muscle_group": "épaules", "duration_s": 45, "rest_s": 15},
        ],
    }
    body.update(fields)
    return body


def create(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    response = client.post(f"{ACTIVITY}/circuits", json=payload(**fields), headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


def complete(client: TestClient, auth: dict[str, str], index: int = 0, **fields: Any) -> Any:
    body: dict[str, Any] = {"duration_min": 18}
    body.update(fields)
    response = client.post(f"{ACTIVITY}/circuits/{index}/done", json=body, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


def rows(dav: FakeWebDav, path: str) -> list[list[str]]:
    """Les lignes de données d'un fichier, découpées. L'en-tête se lit à part."""
    return [line.split(",") for line in dav.content_of(path).splitlines()[1:]]


# ── 1. Le fichier (`STO-02`) ──────────────────────────


def test_a_completed_circuit_is_written_across_two_readable_files(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Deux fichiers plutôt qu'une liste de groupes dans une cellule : l'assiduité compte
    des séries par groupe et par jour, et une cellule à rallonge perdrait ce compte tout
    en cessant d'être lisible dans un tableur."""
    create(app_client, auth)
    complete(app_client, auth)

    sessions = dav.content_of(SESSIONS_FILE)
    sets = dav.content_of(SETS_FILE)

    assert sessions.splitlines()[0] == (
        "session_id,circuit_id,date,name,rounds,duration_min,rpe,source"
    )
    assert sets.splitlines()[0] == "session_id,date,exercise_name,muscle_group,sets,reps"
    assert "Haut du corps" in sessions


def test_the_files_are_written_with_a_bom_and_keep_their_accents(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le BOM est ce qui fait qu'Excel ouvre « épaules » et non « Ã©paules ». Les deux
    fichiers neufs suivent la règle du reste du stockage, pas une leur."""
    create(app_client, auth)
    complete(app_client, auth)

    assert dav.files[SETS_FILE].content.startswith(b"\xef\xbb\xbf")
    assert "épaules" in dav.content_of(SETS_FILE)
    assert "Écarté" in dav.content_of(SETS_FILE)


def test_the_session_carries_no_load_at_all(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """**C4** : `circuit_loads.csv` reste la seule autorité sur ce qu'on charge, et le
    tonnage reste hors du monde tabata. Un exercice au temps porte `reps = -1` ; une
    colonne de charge ici produirait un tonnage négatif au premier calcul."""
    create(app_client, auth)
    complete(app_client, auth)

    header = (
        dav.content_of(SETS_FILE).splitlines()[0] + dav.content_of(SESSIONS_FILE).splitlines()[0]
    )

    assert "weight" not in header
    assert "volume" not in header


# ── 2. Bornes refusées ────────────────────────────────


def test_a_refused_completion_writes_in_neither_world(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """La durée n'est pas déduite d'un champ absent (**D4**). Un refus doit rester un
    refus **des deux côtés** : un monde qui enregistre ce que l'autre refuse est
    exactement la divergence que cette phase existe pour empêcher."""
    circuit = create(app_client, auth)

    response = app_client.post(f"{ACTIVITY}/circuits/{circuit['id']}/done", json={}, headers=auth)

    assert response.status_code == 422
    assert SESSIONS_FILE not in dav.files
    assert SETS_FILE not in dav.files


def test_declaring_an_unknown_circuit_done_writes_nothing(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Une position hors bornes est une erreur de client, pas une séance."""
    response = app_client.post(
        f"{ACTIVITY}/circuits/7/done", json={"duration_min": 18}, headers=auth
    )

    assert response.status_code == 404
    assert SESSIONS_FILE not in dav.files


# ── 3. Les deux mondes disent la même séance ──────────


def test_one_gesture_fills_both_worlds(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """**Le test qui porte la phase 1.** Tant que les sept consommateurs lisent l'ancien
    monde, le nouveau se vérifie contre lui — c'est toute la raison de les remplir
    ensemble avant de rebrancher quoi que ce soit."""
    create(app_client, auth)
    complete(app_client, auth)

    workout = rows(dav, WORKOUTS_FILE)[0]
    session = rows(dav, SESSIONS_FILE)[0]

    # date, durée, provenance : les trois colonnes que les agrégats et le planning lisent.
    assert session[2] == workout[0] == TODAY.isoformat()
    assert session[5] == workout[2] == "18.0"
    assert session[7] == workout[6] == "cadence"


def test_each_round_counts_as_one_set_in_both_worlds(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Quatre rounds, quatre séries de chaque exercice — et le chiffre est calculé **une
    fois**. Deux calculs donneraient quatre séries d'un côté et cent de l'autre le jour où
    un fichier corrigé à la main sort des bornes de Cadence."""
    create(app_client, auth)
    complete(app_client, auth)

    assert [row[4] for row in rows(dav, SETS_FILE)] == ["4", "4"]
    assert [row[6] for row in rows(dav, LOG_FILE)] == ["4", "4"]
    assert rows(dav, SESSIONS_FILE)[0][4] == "4"


def test_the_muscle_groups_travel_into_the_sets(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """C'est la colonne qui rendra l'assiduité possible sans `exercise_log.csv`. Sans
    elle, tous les tabatas finiraient dans « autre » et l'équilibre par groupe cesserait
    de vouloir dire quelque chose exactement là où le tabata compte."""
    create(app_client, auth)
    complete(app_client, auth)

    assert [(row[2], row[3]) for row in rows(dav, SETS_FILE)] == [
        ("Push-Ups Classic", "pectoraux"),
        ("Écarté", "épaules"),
    ]


def test_a_timed_exercise_carries_the_sentinel(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`-1` **dit** « au temps » à qui ouvre le fichier, là où une cellule vide laisserait
    deviner. Même règle que `circuit_exercises.csv` : c'est `reps` qui dit la nature de la
    ligne, et rien ne la multiplie par une charge."""
    create(app_client, auth)
    complete(app_client, auth)

    assert [row[5] for row in rows(dav, SETS_FILE)] == ["15", "-1"]


def test_the_confirmed_duration_is_the_one_written(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """**D4** : l'estimation est proposée à l'écran, corrigée au doigt, et c'est le chiffre
    confirmé qui entre dans le fichier — jamais l'estimation, qui serait une valeur
    inventée dans le volume hebdomadaire."""
    create(app_client, auth)
    complete(app_client, auth, duration_min=23, rpe=8)

    session = rows(dav, SESSIONS_FILE)[0]

    assert (session[5], session[6]) == ("23.0", "8")


def test_the_day_comes_from_the_server(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Aucune date dans la charge utile : Cadence ne peut pas dire à Metric qu'une séance
    a eu lieu (**D6**), donc c'est un geste, et un geste se fait maintenant. La date est
    recopiée sur les séries pour qu'une semaine se compte en lisant ce seul fichier."""
    create(app_client, auth)
    complete(app_client, auth)

    assert rows(dav, SESSIONS_FILE)[0][2] == TODAY.isoformat()
    assert {row[1] for row in rows(dav, SETS_FILE)} == {TODAY.isoformat()}


# ── 4. Provenance et rattachements (`IMP-05`, `ACT-06`) ──


def test_the_session_points_at_its_circuit_and_keeps_its_name(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`circuit_id` dit d'où vient la séance, `name` dit ce qu'elle était. La duplication
    est celle d'`exercise_log.csv` et pour la même raison (`ACT-06`)."""
    circuit = create(app_client, auth)
    complete(app_client, auth)

    session = rows(dav, SESSIONS_FILE)[0]

    assert session[1] == circuit["circuit_id"]
    assert session[3] == "Haut du corps"


def test_deleting_the_circuit_leaves_the_history_readable(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le point de la duplication, et il ne se voit qu'ici : sans le nom recopié, une
    ligne d'historique deviendrait muette dès que son patron disparaît — dans
    l'application comme dans un tableur trois ans plus tard."""
    circuit = create(app_client, auth)
    complete(app_client, auth)

    app_client.delete(
        f"{ACTIVITY}/circuits/{circuit['id']}", headers={**auth, "If-Match": circuit["token"]}
    )

    session = rows(dav, SESSIONS_FILE)[0]
    assert session[3] == "Haut du corps"
    assert [row[2] for row in rows(dav, SETS_FILE)] == ["Push-Ups Classic", "Écarté"]


def test_each_completion_gets_its_own_stable_identifier(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Deux fois la même séance, ce sont deux séances : rien n'empêche de déclarer un
    circuit deux fois (**D6**), et les confondre effacerait la seconde. Les séries suivent
    leur session, jamais sa position dans le fichier."""
    create(app_client, auth)
    complete(app_client, auth)
    complete(app_client, auth)

    sessions = rows(dav, SESSIONS_FILE)
    identifiers = [row[0] for row in sessions]

    assert len(sessions) == 2
    assert len(set(identifiers)) == 2
    assert [row[0] for row in rows(dav, SETS_FILE)] == [
        identifiers[0],
        identifiers[0],
        identifiers[1],
        identifiers[1],
    ]


def test_the_session_identifier_is_not_the_workout_one(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Reprendre le `workout_id` serait commode le temps de la transition, et l'identifiant
    disparaîtrait avec le fichier qui le porte. Ce monde-ci doit tenir debout seul le jour
    où l'autre est supprimé."""
    create(app_client, auth)
    workout = complete(app_client, auth)

    assert rows(dav, SESSIONS_FILE)[0][0] != workout["workout_id"]


# ── 5. Lire, y compris sur historique vide ────────────


async def test_the_service_reads_an_empty_history_without_failing(store: FileStore) -> None:
    """Les sept consommateurs liront ces fichiers avant qu'un seul circuit soit déclaré
    fait. Un fichier absent est un historique vide, jamais une panne — sans quoi le
    tableau de bord tomberait en `502` sur une installation neuve."""
    service = CircuitSessionService(store)

    assert await service.all() == []
    assert await service.sets() == []


async def test_the_service_reads_back_what_the_route_wrote(
    app_client: TestClient, auth: dict[str, str], store: FileStore
) -> None:
    """La phase 2 rebranchera les consommateurs sur ce service, pas sur les fichiers.
    Ce qu'il rend doit donc porter les colonnes dont ils vivent : la date, la durée et le
    groupe musculaire."""
    create(app_client, auth)
    complete(app_client, auth)

    sessions = await CircuitSessionService(store).all()
    sets = await CircuitSessionService(store).sets()

    assert [(row.model.date, row.model.duration_min) for row in sessions] == [(TODAY, 18.0)]
    assert [row.model.muscle_group for row in sets] == ["pectoraux", "épaules"]


# ── 7. L'ordre ────────────────────────────────────────


def test_the_sets_follow_the_written_position_of_the_exercises(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`circuit_exercises.csv` porte une `position` écrite, et c'est elle qui ordonne la
    séance — pas l'ordre des lignes, qu'un tri dans un tableur peut intervertir."""
    create(
        app_client,
        auth,
        exercises=[
            {"name": "Squat", "muscle_group": "jambes", "reps": 12, "rest_s": 20},
            {"name": "Plank", "muscle_group": "abdos", "duration_s": 30, "rest_s": 10},
            {"name": "Rowing", "muscle_group": "dos", "reps": 10, "rest_s": 15},
        ],
    )
    complete(app_client, auth)

    assert [row[2] for row in rows(dav, SETS_FILE)] == ["Squat", "Plank", "Rowing"]


# ── Les cas limites du fichier (`STO-04`) ─────────────


async def test_an_exercise_without_a_group_is_read_as_other(store: FileStore) -> None:
    """Une ligne écrite à la main ou avant que la colonne existe se lit comme `autre`,
    jamais en faisant tomber le fichier. La règle est celle de `_group_of` — une seule
    implémentation, sinon les deux mondes rangeraient le même exercice ailleurs."""
    service = CircuitSessionService(store)

    await service.record(
        CircuitRow(id="c1", name="Haut du corps"),
        [CircuitExerciseRow(circuit_id="c1", position=1, name="Burpees", reps=10)],
        day=TODAY,
        rounds=4,
        duration_min=18,
    )

    assert [row.model.muscle_group for row in await service.sets()] == ["autre"]


def test_an_exercise_without_a_name_does_not_break_the_completion(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Un `500` **après** que la séance ait été écrite, et il a survécu à la phase 1.

    Le catalogue filtrait les exercices sans nom, le journal les appariait ensuite par
    `zip(strict=True)` : les deux listes n'avaient plus la même longueur. Une ligne de
    `circuit_exercises.csv` corrigée à la main — ou vidée dans un tableur — suffisait.
    """
    dav.seed(
        "Metric/activity/circuits.csv",
        "id,name,rounds,round_rest_s,created,note\nc1,Haut du corps,4,60,,\n",
    )
    dav.seed(
        "Metric/activity/circuit_exercises.csv",
        "circuit_id,position,name,muscle_group,duration_s,reps,rest_s\n"
        "c1,1,Squat,jambes,20,10,15\n"
        "c1,2, ,jambes,20,10,15\n",
    )

    workout = complete(app_client, auth)

    assert [entry["exercise_name"] for entry in workout["exercises"]] == ["Squat"]
    assert [row[2] for row in rows(dav, SETS_FILE)] == ["Squat"]


async def test_an_exercise_without_a_name_produces_no_line(store: FileStore) -> None:
    """`ACT-06` duplique le nom pour que l'historique reste lisible sans son patron ; une
    ligne muette n'y répondrait pas. Le fichier corrigé à la main est le seul chemin qui y
    mène — le schéma exige un nom à la saisie."""
    service = CircuitSessionService(store)

    await service.record(
        CircuitRow(id="c1", name="Haut du corps"),
        [
            CircuitExerciseRow(circuit_id="c1", position=1, name="Squat", muscle_group="jambes"),
            CircuitExerciseRow(circuit_id="c1", position=2, name=" ", muscle_group="jambes"),
        ],
        day=TODAY,
        rounds=4,
        duration_min=18,
    )

    assert [row.model.exercise_name for row in await service.sets()] == ["Squat"]


# ── 8. Le rebranchement : compté **une** fois, partout ──
#
# La phase 2 remplace `workouts.csv` par `circuit_sessions.csv` chez les sept
# consommateurs (`docs/refonte-activite.md` §4). Le remplacement est **exclusif**, et
# c'est ce que cette section garde : depuis la phase 1 un même geste écrit dans les deux
# mondes, donc un consommateur qui lirait les deux compterait chaque tabata deux fois.
# Aucun test de la batterie ne l'aurait vu — les deux chiffres sont plausibles.


def test_a_circuit_done_counts_once_on_the_dashboard(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """**Le test qui porte la phase 2.** Une séance faite, une séance comptée.

    `TrainingTotals` lisait runs + `workouts.csv` ; il lit runs + `circuit_sessions.csv`.
    Additionner les deux donnerait `2`, ce qui est exactement le genre de chiffre faux
    qu'aucune assertion existante n'attrape.
    """
    create(app_client, auth)
    complete(app_client, auth)

    training = app_client.get("/api/aggregates/dashboard", headers=auth).json()["training"]

    assert training["sessions_total"] == 1
    assert training["minutes_total"] == pytest.approx(18)
    assert [(part["kind"], part["sessions"]) for part in training["split"]] == [("tabata", 1)]


def test_the_streak_counts_the_day_once(app_client: TestClient, auth: dict[str, str]) -> None:
    """La série d'assiduité de suivi (`AGG-03`) : la source `workouts` désigne la séance,
    pas le fichier. Un jour actif reste un jour, quel que soit le nombre de fichiers
    écrits par le geste qui l'a rempli."""
    create(app_client, auth)
    complete(app_client, auth)

    streak = app_client.get("/api/aggregates/dashboard", headers=auth).json()["streak"]
    aujourd_hui = next(day for day in streak["last_seven"] if day["date"] == TODAY.isoformat())

    assert aujourd_hui["sources"] == ["workouts"]


def test_a_circuit_done_honours_one_planned_session_and_not_two(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`PLAN-06` compte `min(prévu, réalisé)` par journée. Deux séances prévues le même
    jour et un seul tabata fait : une seule honorée. Si le planning lisait les deux
    mondes, la seconde le serait aussi — et le taux de respect annoncerait 100 % sur une
    journée à moitié tenue."""
    create(app_client, auth)
    complete(app_client, auth)

    body = {
        "date": TODAY.isoformat(),
        "kind": "muscu",
        "title": "Haut du corps",
        "duration_min": 60,
    }
    for heure in ("08:00", "19:00"):
        response = app_client.post(
            "/api/planning/sessions", json={**body, "time": heure}, headers=auth
        )
        assert response.status_code == 201, response.text

    view = app_client.get("/api/planning/adherence", params={"weeks": 1}, headers=auth).json()

    assert view["planned"] == 2
    assert view["weeks"][0]["done"] == 1
    assert view["honoured"] == 1


async def test_a_circuit_done_feeds_the_muscle_tracks(
    app_client: TestClient, auth: dict[str, str], store: FileStore
) -> None:
    """L'assiduité par groupe compte des **séries**, et elles viennent désormais de
    `circuit_session_sets.csv`. Quatre rounds sur un exercice de pectoraux, c'est quatre
    séries de pectoraux — le même compte que l'ancien monde en tirait d'`exercise_log`."""
    from app.domains.heatmap.sources import daily_values

    create(app_client, auth)
    complete(app_client, auth)

    valeurs = await daily_values(store, "activity.muscle_group", "pectoraux")
    minutes = await daily_values(store, "activity.duration", "")

    assert valeurs[TODAY] == pytest.approx(4)
    assert minutes[TODAY] == pytest.approx(18)


async def test_the_day_detail_names_the_circuit_and_its_exercises(
    app_client: TestClient, auth: dict[str, str], store: FileStore
) -> None:
    """Le détail d'une case (`HEAT-29`) : le **nom du circuit** pour les minutes, les
    exercices pour les séries. Tous deux recopiés sur la session (`ACT-06`), donc lisibles
    quand le patron aura disparu."""
    from app.domains.heatmap.sources import explain_day

    create(app_client, auth)
    complete(app_client, auth)

    minutes = await explain_day(store, "activity.duration", "", TODAY)
    series = await explain_day(store, "activity.muscle_group", "", TODAY)

    assert [item.label for item in minutes] == ["Haut du corps"]
    assert [item.label for item in series] == ["Push-Ups Classic", "Écarté"]
    # `-1` reste dans le fichier et ne sort pas de l'API : c'est `reps` à `null` qui dit
    # qu'un exercice était au temps.
    assert [item.reps for item in series] == [15, None]
