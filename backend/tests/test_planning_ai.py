"""Génération assistée du planning (`PLAN-03`, `PLAN-04`, `IA-07`).

Deux moitiés, comme à l'import Apple, et la séparation est la garantie du lot : la
génération ne sait pas écrire, l'adoption ne sait pas interroger un modèle. Entre les
deux, un écran et un appui.

**Aucun test de ce fichier ne touche le vrai OpenRouter.** Un appel réel est non
déterministe par nature — même consigne, deux réponses — et une batterie branchée dessus
dirait tantôt vert tantôt rouge sans qu'une ligne de code ait bougé. Tout passe par
`tests/fake_openrouter.py`, qui permet en prime de scénariser ce que le vrai service ne
produirait pas sur commande : une date de l'an dernier, un doublon, une durée en toutes
lettres.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.dates import today_local, week_start
from app.domains.planning.generation import build_prompt, read_proposals
from tests.fake_openrouter import FakeOpenRouter
from tests.fake_webdav import FakeWebDav

PLANNING = "/api/planning"
PLAN_FILE = "Metric/planning/plan.csv"
PLAN_HEADER = "id,date,time,kind,title,duration_min,note,source\n"
WORKOUTS_FILE = "Metric/activity/workouts.csv"

#: Fenêtre par défaut d'une proposition : le lundi qui vient, sur sept jours.
MONDAY = week_start(today_local()) + timedelta(days=7)


def answer(*sessions: dict[str, Any]) -> str:
    return json.dumps({"sessions": list(sessions)})


def a_session(offset: int = 0, **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "date": (MONDAY + timedelta(days=offset)).isoformat(),
        "time": "18:30",
        "kind": "muscu",
        "title": "Haut du corps",
        "duration_min": 60,
        "reason": "dos non travaillé depuis 12 jours",
    }
    return {**base, **fields}


def propose(client: TestClient, auth: dict[str, str], **body: Any) -> Any:
    return client.post(f"{PLANNING}/proposal", json=body, headers=auth)


# ── La relecture, sans rien monter (`PLAN-03`) ────────


def window() -> dict[str, Any]:
    return {"start": MONDAY, "end": MONDAY + timedelta(days=6), "taken": set()}


def test_a_plain_answer_is_read_as_proposed_sessions() -> None:
    kept, dropped = read_proposals({"sessions": [a_session()]}, **window())

    assert dropped == []
    assert len(kept) == 1
    assert kept[0].date == MONDAY
    assert kept[0].time == "18:30"
    assert kept[0].duration_min == 60
    assert kept[0].reason == "dos non travaillé depuis 12 jours"


def test_a_date_outside_the_window_is_dropped_not_corrected() -> None:
    """« Hors bornes, on écarte ; on ne ramène pas à la borne », appliqué au temps.

    Un modèle à qui l'on demande « la semaine prochaine » répond parfois avec les dates de
    l'an dernier. Recaler la séance sur le lundi le plus proche inventerait une date ;
    l'écarter ne coûte rien, puisque rien n'existe encore.
    """
    far = (MONDAY - timedelta(days=365)).isoformat()

    kept, dropped = read_proposals({"sessions": [a_session(date=far)]}, **window())

    assert kept == []
    assert any("hors de la période" in reason for reason in dropped)


def test_an_unreadable_date_is_named_in_the_reasons() -> None:
    kept, dropped = read_proposals({"sessions": [a_session(date="lundi prochain")]}, **window())

    assert kept == []
    assert any("lundi prochain" in reason for reason in dropped)


def test_a_session_already_planned_is_not_proposed_twice() -> None:
    """`PLAN-03` : « évite de dupliquer l'existant ».

    Le modèle reçoit pourtant la liste de ce qui est prévu — on le lui dit **et** on le
    vérifie, parce qu'une consigne suivie neuf fois sur dix produit un doublon par semaine.
    """
    taken = {(MONDAY, "muscu")}

    kept, dropped = read_proposals({"sessions": [a_session()]}, **{**window(), "taken": taken})

    assert kept == []
    assert any("déjà prévue" in reason for reason in dropped)


def test_the_model_cannot_duplicate_inside_its_own_answer() -> None:
    """Cas plus fréquent que la collision avec l'existant."""
    kept, dropped = read_proposals(
        {"sessions": [a_session(), a_session(title="Encore le haut du corps")]}, **window()
    )

    assert len(kept) == 1
    assert any("déjà prévue" in reason for reason in dropped)


def test_two_sessions_of_different_kinds_can_share_a_day() -> None:
    """La garde porte sur `(jour, nature)` : une course le matin et de la muscu le soir
    ne sont pas un doublon."""
    kept, _ = read_proposals(
        {"sessions": [a_session(), a_session(kind="course", title="Sortie", time="08:00")]},
        **window(),
    )

    assert len(kept) == 2


def test_a_session_without_a_usable_duration_is_dropped() -> None:
    """Elle ne pourrait pas être adoptée — la saisie exige une durée — et lui en attribuer
    une reviendrait à décider à la place de quelqu'un."""
    kept, dropped = read_proposals({"sessions": [a_session(duration_min=None)]}, **window())

    assert kept == []
    assert any("durée illisible" in reason for reason in dropped)


@pytest.mark.parametrize(
    ("raw", "minutes"), [("1h30", 90.0), ("45", 45.0), ("45 min", 45.0), ("1:30:00", 90.0)]
)
def test_a_duration_is_read_with_the_grammar_of_the_keyboard(raw: str, minutes: float) -> None:
    """La même grammaire que pour une saisie au clavier (`ACT-01`).

    En écrire une seconde ici garantirait deux résultats divergents le jour où l'une des
    deux évolue.
    """
    kept, _ = read_proposals({"sessions": [a_session(duration_min=raw)]}, **window())

    assert kept[0].duration_min == minutes


@pytest.mark.parametrize("raw", [5000, "1:00", 2, 0])
def test_an_out_of_bounds_duration_is_dropped(raw: Any) -> None:
    """`1:00` est le cas qui vaut la borne basse.

    La grammaire du projet le lit comme **une minute** — c'est du `mm:ss`, celui qui fait
    de `28:45` vingt-huit minutes trois quarts. Un modèle qui l'écrit en pensant « une
    heure » produirait une séance fausse d'un facteur soixante, et rien à l'écran ne
    distinguerait cette minute-là d'une minute voulue. On l'écarte plutôt que de deviner.
    """
    kept, dropped = read_proposals({"sessions": [a_session(duration_min=raw)]}, **window())

    assert kept == []
    assert dropped


@pytest.mark.parametrize("raw", ["18h30", "25:00", "le soir", "", None])
def test_a_malformed_time_costs_the_time_not_the_session(raw: Any) -> None:
    """Une séance prévue mardi sans heure reste une séance prévue mardi."""
    kept, _ = read_proposals({"sessions": [a_session(time=raw)]}, **window())

    assert len(kept) == 1
    assert kept[0].time is None


@pytest.mark.parametrize("raw", ["cardio", "", "MUSCU ", None])
def test_an_unknown_kind_falls_back_to_other(raw: Any) -> None:
    kept, _ = read_proposals({"sessions": [a_session(kind=raw)]}, **window())

    assert kept[0].kind in {"autre", "muscu"}


def test_a_missing_title_falls_back_to_the_kind() -> None:
    """Repli de **présentation**, pas de donnée : « Muscu » ne dit rien que la nature ne
    disait déjà. Sans lui, la séance serait inadoptable pour un titre manquant."""
    kept, _ = read_proposals({"sessions": [a_session(title=None)]}, **window())

    assert kept[0].title == "Muscu"


def test_sessions_come_back_in_chronological_order() -> None:
    kept, _ = read_proposals(
        {
            "sessions": [
                a_session(offset=4, kind="course"),
                a_session(offset=0),
                a_session(offset=2, kind="autre"),
            ]
        },
        **window(),
    )

    assert [item.date for item in kept] == [
        MONDAY,
        MONDAY + timedelta(days=2),
        MONDAY + timedelta(days=4),
    ]


def test_a_shapeless_answer_yields_nothing_rather_than_failing() -> None:
    """Un modèle bavard qui rend `{"planning": "…"}` ne doit pas faire tomber la route."""
    assert read_proposals({"planning": "voici votre semaine"}, **window()) == ([], [])


# ── La consigne (`PLAN-03`, `GOAL-02`) ────────────────


def test_the_prompt_spells_every_day_of_the_window() -> None:
    """La partie la plus chère de la consigne, et celle qui rapporte le plus.

    Un modèle n'a pas de calendrier, il a des habitudes typographiques. Lui donner
    « lundi : 2026-08-10 » supprime d'un coup les décalages d'un jour et les années
    fausses.
    """
    prompt = build_prompt(
        start=date(2026, 8, 10),
        end=date(2026, 8, 16),
        history=[],
        muscles=[],
        existing=[],
    )

    assert "- lundi : 2026-08-10" in prompt
    assert "- dimanche : 2026-08-16" in prompt
    assert prompt.count("2026-08-") >= 7


def test_the_prompt_carries_the_basis_and_the_constraints() -> None:
    prompt = build_prompt(
        start=date(2026, 8, 10),
        end=date(2026, 8, 16),
        history=["moyenne : 3,2 séance(s) par semaine"],
        muscles=["dos : jamais travaillé"],
        existing=["2026-08-12 : course — Sortie longue"],
        objective="Courir 10 km en moins de 50 minutes",
        constraints="pas le mercredi",
    )

    assert "3,2 séance(s) par semaine" in prompt
    assert "dos : jamais travaillé" in prompt
    assert "Sortie longue" in prompt
    assert "pas le mercredi" in prompt
    assert "Courir 10 km" in prompt


def test_an_absent_objective_leaves_no_empty_heading() -> None:
    """Une rubrique vide dans une consigne invite le modèle à la remplir lui-même."""
    prompt = build_prompt(start=MONDAY, end=MONDAY, history=[], muscles=[], existing=[])

    assert "Objectif en cours" not in prompt
    assert "Contraintes" not in prompt


# ── Bout en bout, contre le double ASGI ───────────────


def test_a_proposal_writes_absolutely_nothing(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """Le cœur de `PLAN-04`, et la moitié de la DoD du lot.

    Ce test échouerait au premier raccourci « tant qu'on y est, écrivons-les » — le genre
    de raccourci qui paraît inoffensif un vendredi soir.
    """
    openrouter.say(answer(a_session(), a_session(offset=2, kind="course", title="Sortie")))

    response = propose(ai_app_client, auth)

    assert response.status_code == 200, response.text
    assert len(response.json()["sessions"]) == 2
    assert PLAN_FILE not in dav.files


def test_the_proposal_says_what_it_is_based_on(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """Une suggestion dont on voit l'argument se discute ; une suggestion nue se croit ou
    se rejette."""
    day = today_local() - timedelta(days=3)
    dav.seed(
        WORKOUTS_FILE,
        "date,type,duration_min,calories,rpe,note,source,id\n"
        f"{day.isoformat()},musculation,60,,,,manual,w1\n",
    )
    openrouter.say(answer(a_session()))

    basis = propose(ai_app_client, auth).json()["basis"]

    assert basis
    assert "séance par semaine" in basis[0]


def test_the_window_defaults_to_next_monday(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """On ne remplit pas une semaine déjà entamée, dont les jours passés ne se
    planifient plus."""
    openrouter.say(answer(a_session()))

    body = propose(ai_app_client, auth).json()

    assert body["start"] == MONDAY.isoformat()
    assert body["end"] == (MONDAY + timedelta(days=6)).isoformat()


def test_two_weeks_widen_the_window(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    openrouter.say(answer(a_session()))

    body = propose(ai_app_client, auth, weeks=2).json()

    assert body["end"] == (MONDAY + timedelta(days=13)).isoformat()


def test_more_than_two_weeks_is_refused(ai_app_client: TestClient, auth: dict[str, str]) -> None:
    """Au-delà, la fréquence réelle sur laquelle la proposition s'appuie a le temps de
    changer."""
    assert propose(ai_app_client, auth, weeks=4).status_code == 422


def test_an_answer_with_nothing_usable_is_refused_with_a_catalogue_code(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """La chaîne a fonctionné, la réponse ne contient rien qu'on puisse écrire.

    `422` et non `503` : rien n'est en panne. Réessayer ou planifier à la main sont deux
    conduites également valables, et le message le dit.
    """
    openrouter.say(answer(a_session(date="2001-01-01")))

    response = propose(ai_app_client, auth)

    assert response.status_code == 422
    assert response.json()["code"] == "ai_unreadable"
    assert "à la main" in response.json()["message"]


def test_the_existing_plan_reaches_the_model(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    dav.seed(
        PLAN_FILE,
        PLAN_HEADER + f"abc123,{MONDAY.isoformat()},18:30,course,Sortie longue,45,,manual\n",
    )
    openrouter.say(answer(a_session(offset=1)))

    propose(ai_app_client, auth)

    sent = openrouter.calls[0]
    assert sent.with_image is False, "un planning ne s'accompagne d'aucune image (`IA-04`)"


def test_a_session_already_in_the_file_is_not_proposed_again(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    dav.seed(PLAN_FILE, PLAN_HEADER + f"abc123,{MONDAY.isoformat()},18:30,muscu,Haut,60,,manual\n")
    openrouter.say(answer(a_session(), a_session(offset=1, kind="course", title="Sortie")))

    body = propose(ai_app_client, auth).json()

    assert [item["date"] for item in body["sessions"]] == [(MONDAY + timedelta(days=1)).isoformat()]
    assert body["dropped"]


def test_adopting_a_proposal_writes_it_marked_ai(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """Le second temps de `PLAN-04` : ce qui reste après retrait s'enregistre en une fois."""
    openrouter.say(answer(a_session(), a_session(offset=2, kind="course", title="Sortie")))
    proposal = propose(ai_app_client, auth).json()

    # Le retrait individuel a lieu à l'écran : le client renvoie **ce qu'il garde**.
    kept = [
        {
            "date": item["date"],
            "time": item["time"],
            "kind": item["kind"],
            "title": item["title"],
            "duration_min": item["duration_min"],
            "note": item["note"],
        }
        for item in proposal["sessions"][:1]
    ]

    response = ai_app_client.post(
        f"{PLANNING}/proposal/adopt", json={"sessions": kept}, headers=auth
    )

    assert response.status_code == 201
    created = response.json()["created"]
    assert len(created) == 1
    assert created[0]["source"] == "ai"
    assert dav.content_of(PLAN_FILE).count("\n") == 2  # en-tête + une séance


# ── Sans clé, rien n'est bloqué (`IA-07`) ─────────────


def test_without_a_key_the_proposal_refuses_with_a_catalogue_code(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """`AiServiceDep` fait échouer l'endpoint avant qu'il ne s'exécute : l'appelant n'a
    rien à vérifier lui-même."""
    response = propose(store_client, auth)

    assert response.status_code == 503
    assert response.json()["code"] == "ai_unavailable"


def test_without_a_key_planning_by_hand_is_untouched(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """L'IA est un confort, jamais un prérequis. C'est la moitié de DoD que la simulation
    peut couvrir, et elle doit rester vraie lot après lot."""
    created = store_client.post(
        f"{PLANNING}/sessions",
        json={
            "date": MONDAY.isoformat(),
            "kind": "muscu",
            "title": "Haut du corps",
            "duration_min": 60,
        },
        headers=auth,
    )
    assert created.status_code == 201

    month = store_client.get(
        f"{PLANNING}/month", params={"month": MONDAY.strftime("%Y-%m")}, headers=auth
    )
    assert month.status_code == 200

    adopted = store_client.post(
        f"{PLANNING}/proposal/adopt",
        json={
            "sessions": [
                {
                    "date": (MONDAY + timedelta(days=1)).isoformat(),
                    "kind": "course",
                    "title": "Sortie",
                    "duration_min": 45,
                }
            ]
        },
        headers=auth,
    )
    assert adopted.status_code == 201, "l'adoption n'interroge aucun modèle"

    assert store_client.get(f"{PLANNING}/export.ics", headers=auth).status_code == 200
