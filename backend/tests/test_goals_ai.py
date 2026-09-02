"""Génération d'objectif et bilan hebdomadaire (`GOAL-01` → `GOAL-03`, `IA-08`, `IA-07`).

Deux moitiés, comme au planning et à l'import Apple, et la séparation est la garantie du
lot : la génération ne sait pas écrire, l'adoption ne sait pas interroger un modèle. Entre
les deux, un écran et un appui.

**Aucun test de ce fichier ne touche le vrai OpenRouter.** Un appel réel est non
déterministe par nature — même consigne, deux réponses — et une batterie branchée dessus
dirait tantôt vert tantôt rouge sans qu'une ligne de code ait bougé. Tout passe par
`tests/fake_openrouter.py`, qui permet en prime de scénariser ce que le vrai service ne
produirait pas sur commande : une métrique inventée, une cible de quarante séances, une
échéance à l'an prochain.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.dates import today_local, week_start
from app.domains.goals.generation import build_prompt, metric_lines, read_goal
from app.domains.goals.weekly import build_prompt as build_weekly_prompt
from app.domains.goals.weekly import read_review
from tests.fake_openrouter import FakeOpenRouter
from tests.fake_webdav import FakeWebDav

GOALS = "/api/goals"
GOALS_FILE = "Metric/goals/goals.csv"
GOALS_HEADER = "id,created,title,metric,target,unit,deadline,rationale,source,status,outcome"
WEEKLY_FILE = "Metric/insights/weekly.csv"
MEALS_FILE = "Metric/nutrition/meals.csv"
SESSIONS_FILE = "Metric/activity/circuit_sessions.csv"
PLAN_FILE = "Metric/planning/plan.csv"

TODAY = today_local()
FLOOR = TODAY + timedelta(weeks=4)
CEILING = TODAY + timedelta(weeks=8)
DEADLINE = TODAY + timedelta(weeks=6)


def a_goal(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Trois séances par semaine",
        "metric": "weekly_sessions",
        "target": 3,
        "deadline": DEADLINE.isoformat(),
        "rationale": "1,8 séance par semaine sur les quatre dernières",
    }
    return {**base, **fields}


def answer(**fields: Any) -> str:
    return json.dumps(a_goal(**fields))


def propose(client: TestClient, auth: dict[str, str], **body: Any) -> Any:
    return client.post(f"{GOALS}/proposal", json=body, headers=auth)


def seed_sessions(dav: FakeWebDav, count: int) -> None:
    """`count` séances réparties sur les quatre semaines révolues."""
    monday = week_start(TODAY)
    lines = "".join(
        f"s{index},c1,"
        f"{(monday - timedelta(weeks=1 + index % 4, days=index % 5)).isoformat()},"
        f"Haut du corps,4,60,,cadence\n"
        for index in range(count)
    )
    dav.seed(
        SESSIONS_FILE, "session_id,circuit_id,date,name,rounds,duration_min,rpe,source\n" + lines
    )


# ── La relecture, sans rien monter (`GOAL-01`) ────────


def window() -> dict[str, Any]:
    return {"floor": FLOOR, "ceiling": CEILING}


def test_a_plain_answer_is_read_as_a_proposed_goal() -> None:
    goal, dropped = read_goal(a_goal(), **window())

    assert dropped == []
    assert goal is not None
    assert goal.metric == "weekly_sessions"
    assert goal.target == 3
    assert goal.unit == "séances", "l'unité vient du registre, pas de la réponse"
    assert goal.label == "Séances par semaine"


def test_a_metric_nothing_measures_is_refused() -> None:
    """Le modèle a le droit de répondre « sommeil ». Adopter un objectif immesurable
    donnerait un écran qui affiche une cible et un tiret jusqu'à son échéance."""
    goal, dropped = read_goal(a_goal(metric="sommeil"), **window())

    assert goal is None
    assert any("sommeil" in reason for reason in dropped)


@pytest.mark.parametrize("target", [40, 0, -3, 1000])
def test_a_target_outside_the_bounds_is_dropped_not_clamped(target: float) -> None:
    """« Hors bornes, on écarte ; on ne ramène pas à la borne » — la règle du L12,
    appliquée à une intention. Quarante séances rabotées à quatorze donneraient un
    objectif faux d'apparence honnête."""
    goal, dropped = read_goal(a_goal(target=target), **window())

    assert goal is None
    assert dropped


@pytest.mark.parametrize("raw", ["trois", None, "", "environ 3"])
def test_an_unreadable_target_is_refused(raw: Any) -> None:
    """Volontairement étroit : extraire « 3 » de « environ 3 séances » serait deviner une
    cible, donc l'inventer."""
    goal, _ = read_goal(a_goal(target=raw), **window())

    assert goal is None


def test_a_comma_decimal_is_read_as_a_number() -> None:
    """Un modèle qui répond en français écrit « 7,5 ». C'est un nombre, pas du texte."""
    goal, _ = read_goal(a_goal(metric="weekly_distance_km", target="7,5"), **window())

    assert goal is not None
    assert goal.target == 7.5


def test_a_deadline_outside_the_window_is_dropped_not_corrected() -> None:
    """Pas de recalage sur le lundi le plus proche : une date qu'on rectifie est une date
    qu'on a inventée."""
    goal, dropped = read_goal(
        a_goal(deadline=(TODAY + timedelta(weeks=30)).isoformat()), **window()
    )

    assert goal is None
    assert any("hors de la fenêtre" in reason for reason in dropped)


def test_an_unreadable_deadline_is_named_in_the_reasons() -> None:
    goal, dropped = read_goal(a_goal(deadline="dans six semaines"), **window())

    assert goal is None
    assert any("dans six semaines" in reason for reason in dropped)


def test_a_missing_title_falls_back_to_the_metric_label() -> None:
    """Repli de **présentation**, pas de donnée : « Séances par semaine » ne dit rien que
    la métrique ne disait déjà. Sans lui, l'objectif serait inadoptable pour un titre."""
    goal, _ = read_goal(a_goal(title=None), **window())

    assert goal is not None
    assert goal.title == "Séances par semaine"


def test_a_shapeless_answer_yields_nothing_rather_than_failing() -> None:
    """Un modèle bavard qui rend `{"objectif": "…"}` ne doit pas faire tomber la route."""
    goal, dropped = read_goal({"objectif": "cours plus"}, **window())

    assert goal is None
    assert dropped


def test_in_thin_data_mode_only_a_regularity_goal_is_accepted() -> None:
    """`GOAL-01` : « données maigres → repli sur un objectif de régularité ».

    On le dit au modèle **et** on le vérifie : sans historique, tout chiffre de performance
    serait tiré d'un point de départ qui n'existe pas.
    """
    refused, dropped = read_goal(
        a_goal(metric="weekly_distance_km", target=20), fallback=True, **window()
    )
    accepted, _ = read_goal(a_goal(), fallback=True, **window())

    assert refused is None
    assert any("trop maigres" in reason for reason in dropped)
    assert accepted is not None


# ── La consigne (`GOAL-02`) ───────────────────────────


def test_the_prompt_lists_the_five_metrics_with_their_bounds() -> None:
    """On lui donne le catalogue plutôt que d'espérer qu'il le devine."""
    lines = metric_lines()

    assert len(lines) == 5
    assert any('"weekly_sessions"' in line for line in lines)
    assert any("entre 30 et 300" in line for line in lines)  # poids


def test_the_prompt_spells_both_ends_of_the_deadline_window() -> None:
    prompt = build_prompt(summary=[], past=[], floor=FLOOR, ceiling=CEILING)

    assert FLOOR.isoformat() in prompt
    assert CEILING.isoformat() in prompt


def test_the_prompt_carries_the_summary_and_the_past_goals() -> None:
    prompt = build_prompt(
        summary=["Poids : 80 kg (relevé du 03/08/2026)"],
        past=["« Courir 20 km » (distance hebdomadaire, cible 20 km) : abandonné"],
        floor=FLOOR,
        ceiling=CEILING,
    )

    assert "80 kg" in prompt
    assert "abandonné" in prompt


def test_an_absent_focus_leaves_no_empty_heading() -> None:
    """Une rubrique vide dans une consigne invite le modèle à la remplir lui-même."""
    prompt = build_prompt(summary=[], past=[], floor=FLOOR, ceiling=CEILING)

    assert "Ce que je veux travailler" not in prompt
    assert "Contrainte" not in prompt


def test_the_fallback_note_names_the_regularity_metric() -> None:
    prompt = build_prompt(summary=[], past=[], floor=FLOOR, ceiling=CEILING, fallback=True)

    assert "régularité" in prompt
    assert "weekly_sessions" in prompt


# ── Bout en bout, contre le double ASGI ───────────────


def test_a_proposal_writes_absolutely_nothing(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """Le cœur de `GOAL-03`, et la moitié de la DoD du lot.

    Ce test échouerait au premier raccourci « tant qu'on y est, écrivons-le » — le genre de
    raccourci qui paraît inoffensif un vendredi soir.
    """
    openrouter.say(answer())

    response = propose(ai_app_client, auth)

    assert response.status_code == 200, response.text
    assert response.json()["goal"]["target"] == 3
    assert GOALS_FILE not in dav.files


def test_the_proposal_publishes_the_condensed_facts_it_sent(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """`GOAL-02` publié plutôt que déclaré : `basis` est **le** condensé envoyé, pas un
    résumé du résumé. C'est ce qui rend la promesse vérifiable à l'écran."""
    openrouter.say(answer())

    basis = propose(ai_app_client, auth).json()["basis"]
    sent = openrouter.calls[0].prompt

    assert basis
    assert all(line in sent for line in basis)
    assert any("Séances par semaine" in line for line in basis)


def test_the_whole_files_never_reach_the_model(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """« Condensé factuel, jamais les fichiers entiers ».

    Une note de repas est ce qu'un fichier a de plus personnel et de moins utile à un
    modèle. Elle sert ici de traceur : si elle apparaît dans la consigne, c'est que le
    fichier y est passé.
    """
    dav.seed(
        MEALS_FILE,
        "datetime,meal_type,comment,photo,protein_g,added_sugar_g,calories,source\n"
        f"{TODAY.isoformat()}T12:30:00+02:00,dejeuner,"
        "Déjeuner avec Camille avant le rendez-vous médical,,40,5,600,manual\n",
    )
    openrouter.say(answer())

    propose(ai_app_client, auth)
    sent = openrouter.calls[0].prompt

    assert "Camille" not in sent
    assert "rendez-vous médical" not in sent
    assert "Protéines" in sent, "le chiffre, lui, part bien"


def test_past_goals_are_reinjected_into_the_next_generation(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """`GOAL-06`. Sans cela, le modèle reproposerait indéfiniment l'objectif qu'on vient
    d'abandonner — et une suggestion déjà refusée est la plus sûre façon de faire cesser
    de lire les suggestions."""
    dav.seed(
        GOALS_FILE,
        f"{GOALS_HEADER}\n"
        f"old001,{(TODAY - timedelta(weeks=12)).isoformat()},Courir 20 km,weekly_distance_km,"
        f"20,km,{(TODAY - timedelta(weeks=4)).isoformat()},,ai,closed,abandoned\n",
    )
    openrouter.say(answer())

    propose(ai_app_client, auth)

    assert "Courir 20 km" in openrouter.calls[0].prompt
    assert "abandonné" in openrouter.calls[0].prompt


def test_thin_data_asks_for_a_regularity_goal(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """Sans historique, proposer « 12 km par semaine » n'est pas un objectif mais un vœu."""
    openrouter.say(answer())

    body = propose(ai_app_client, auth).json()

    assert body["fallback"] is True
    assert "régularité" in openrouter.calls[0].prompt


def test_enough_history_lifts_the_fallback(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    seed_sessions(dav, 8)
    openrouter.say(answer())

    body = propose(ai_app_client, auth).json()

    assert body["fallback"] is False


def test_an_answer_with_nothing_usable_is_refused_with_a_catalogue_code(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """La chaîne a fonctionné, la réponse ne contient rien qu'on puisse écrire.

    `422` et non `503` : rien n'est en panne. Réessayer ou se fixer une cible à la main
    sont deux conduites également valables, et le message le dit.
    """
    openrouter.say(answer(metric="humeur"))

    response = propose(ai_app_client, auth)

    assert response.status_code == 422
    assert response.json()["code"] == "ai_unreadable"
    assert "à la main" in response.json()["message"]


def test_proposing_while_a_goal_is_running_is_refused_before_paying_for_it(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """Le refus tombe **avant** l'appel : le proposer pour le refuser ensuite serait payer
    pour apprendre une règle que le serveur connaissait déjà."""
    dav.seed(
        GOALS_FILE,
        f"{GOALS_HEADER}\n"
        f"abc123,{TODAY.isoformat()},Trois séances,weekly_sessions,3,séances,"
        f"{DEADLINE.isoformat()},,ai,active,\n",
    )
    openrouter.say(answer())

    response = propose(ai_app_client, auth)

    assert response.status_code == 409
    assert openrouter.calls == [], "aucun appel n'a été émis"


def test_adopting_a_proposal_writes_it_marked_ai(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """Le second temps de `GOAL-03` : ce qui a été relu s'enregistre, et pas avant."""
    openrouter.say(answer())
    proposed = propose(ai_app_client, auth).json()["goal"]

    response = ai_app_client.post(
        GOALS,
        json={
            "title": proposed["title"],
            "metric": proposed["metric"],
            "target": proposed["target"],
            "deadline": proposed["deadline"],
            "rationale": proposed["rationale"],
        },
        headers=auth,
    )

    assert response.status_code == 201
    assert response.json()["source"] == "ai"
    assert dav.content_of(GOALS_FILE).count("\n") == 2  # en-tête + un objectif


# ── La dette du L13 : l'objectif remplit le planning ──


def test_the_active_goal_reaches_the_planning_prompt_without_being_retyped(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """L'écart assumé du lot L13 est soldé.

    Le champ `objective` était alors saisi en texte libre, faute de `goals.csv` : un
    objectif qu'on venait d'adopter devait être **retapé** pour que le planning en tienne
    compte, et l'oublier une fois suffisait à obtenir une semaine qui l'ignorait sans le
    dire.
    """
    dav.seed(
        GOALS_FILE,
        f"{GOALS_HEADER}\n"
        f"abc123,{TODAY.isoformat()},Courir 20 km par semaine,weekly_distance_km,20,km,"
        f"{DEADLINE.isoformat()},,ai,active,\n",
    )
    monday = week_start(TODAY) + timedelta(days=7)
    openrouter.say(
        json.dumps(
            {
                "sessions": [
                    {
                        "date": monday.isoformat(),
                        "kind": "course",
                        "title": "Sortie longue",
                        "duration_min": 60,
                    }
                ]
            }
        )
    )

    response = ai_app_client.post("/api/planning/proposal", json={}, headers=auth)

    assert response.status_code == 200, response.text
    sent = openrouter.calls[0].prompt
    assert "Objectif en cours" in sent
    assert "Courir 20 km par semaine" in sent


def test_a_typed_objective_still_replaces_the_active_one(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """Le champ reste un **remplacement ponctuel** : « cette semaine je prépare une
    course » n'a pas vocation à devenir un objectif de six semaines dans `goals.csv`."""
    dav.seed(
        GOALS_FILE,
        f"{GOALS_HEADER}\n"
        f"abc123,{TODAY.isoformat()},Courir 20 km par semaine,weekly_distance_km,20,km,"
        f"{DEADLINE.isoformat()},,ai,active,\n",
    )
    monday = week_start(TODAY) + timedelta(days=7)
    openrouter.say(
        json.dumps(
            {
                "sessions": [
                    {
                        "date": monday.isoformat(),
                        "kind": "muscu",
                        "title": "Haut du corps",
                        "duration_min": 60,
                    }
                ]
            }
        )
    )

    ai_app_client.post(
        "/api/planning/proposal",
        json={"objective": "semaine de récupération, rien d'intense"},
        headers=auth,
    )

    sent = openrouter.calls[0].prompt
    assert "semaine de récupération" in sent
    assert "Courir 20 km par semaine" not in sent


# ── Bilan hebdomadaire (`IA-08`) ──────────────────────


def review_answer(**fields: Any) -> str:
    base: dict[str, Any] = {
        "progress": ["3 séances contre 2 la semaine d'avant"],
        "setbacks": ["hydratation à 1 400 ml par jour, en baisse"],
        "action": "Poser une gourde de 750 ml sur le bureau chaque matin.",
    }
    return json.dumps({**base, **fields})


def test_the_weekly_prompt_covers_the_completed_week_only() -> None:
    """Commenter un mardi le « décrochage » d'une semaine dont il reste cinq jours
    donnerait un bilan faux qui se corrigerait tout seul le dimanche."""
    monday = date(2026, 7, 27)

    prompt = build_weekly_prompt(monday=monday, summary=["3 séances"], history=[])

    assert "2026-07-27" in prompt
    assert "2026-08-02" in prompt


def test_a_review_returned_as_a_sentence_is_read_all_the_same() -> None:
    """Les modèles alternent entre une liste et une phrase pour la même demande. Refuser
    la seconde coûterait un bilan sur deux — et un appel payant avec."""
    progress, setbacks, action = read_review(
        {"progress": "trois séances", "setbacks": [], "action": "Poser la gourde."}
    )

    assert progress == ["trois séances"]
    assert setbacks == []
    assert action == "Poser la gourde."


def test_an_empty_setbacks_list_is_good_news_not_an_incomplete_answer() -> None:
    progress, setbacks, action = read_review(json.loads(review_answer(setbacks=[])))

    assert progress and action
    assert setbacks == []


def test_a_weekly_review_writes_nothing_until_it_is_kept(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """Un bilan qu'on trouve à côté de la plaque n'a aucune raison d'entrer dans
    l'historique d'où la génération suivante tirera son contexte."""
    openrouter.say(review_answer())

    response = ai_app_client.post(f"{GOALS}/weekly", json={}, headers=auth)

    assert response.status_code == 200, response.text
    assert response.json()["week"] == (week_start(TODAY) - timedelta(days=7)).isoformat()
    assert WEEKLY_FILE not in dav.files


def test_the_plan_versus_done_gap_reaches_the_review_without_being_recomputed(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """`PLAN-06` alimente le bilan et en détient l'unique implémentation. Un second calcul
    finirait par répondre autre chose pour la même semaine."""
    monday = week_start(TODAY) - timedelta(days=7)
    dav.seed(
        PLAN_FILE,
        "id,date,time,kind,title,duration_min,note,source\n"
        f"p1,{monday.isoformat()},18:30,muscu,Haut du corps,60,,manual\n",
    )
    openrouter.say(review_answer())

    body = ai_app_client.post(f"{GOALS}/weekly", json={}, headers=auth).json()

    assert any("séance(s) prévue(s)" in line for line in body["basis"])
    assert "1 séance(s) prévue(s), 0 honorée(s)" in openrouter.calls[0].prompt


def test_keeping_a_review_writes_one_line(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    openrouter.say(review_answer())
    review = ai_app_client.post(f"{GOALS}/weekly", json={}, headers=auth).json()

    response = ai_app_client.post(
        f"{GOALS}/weekly/keep",
        json={"week": review["week"], "summary": "Progrès : 3 séances. Action : la gourde."},
        headers=auth,
    )

    assert response.status_code == 201
    header, line = dav.content_of(WEEKLY_FILE).splitlines()[:2]
    assert header == "week,created,summary,source"
    assert line.startswith(review["week"])
    assert line.endswith(",ai")


def test_keeping_the_same_week_twice_replaces_rather_than_duplicates(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`week` est la clé naturelle du fichier : deux lignes pour la même semaine
    rendraient « le bilan de la semaine du 3 août » ambigu, et un fichier destiné à un
    tableur ne porte pas deux vérités pour une même ligne."""
    week = (week_start(TODAY) - timedelta(days=7)).isoformat()
    for summary in ("Premier jet.", "Deuxième jet, meilleur."):
        response = store_client.post(
            f"{GOALS}/weekly/keep", json={"week": week, "summary": summary}, headers=auth
        )
        assert response.status_code == 201, response.text

    lines = [line for line in dav.content_of(WEEKLY_FILE).splitlines() if line.strip()]

    assert len(lines) == 2, "en-tête + une seule ligne de bilan"
    assert "Deuxième jet" in lines[1]


def test_the_history_says_the_week_already_has_a_review(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    week = (week_start(TODAY) - timedelta(days=7)).isoformat()
    store_client.post(
        f"{GOALS}/weekly/keep", json={"week": week, "summary": "Un bilan."}, headers=auth
    )

    body = store_client.get(f"{GOALS}/weekly", headers=auth).json()

    assert body["already_kept"] is True
    assert [item["week"] for item in body["entries"]] == [week]


def test_a_review_with_nothing_in_it_is_refused_rather_than_kept_empty(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    openrouter.say(json.dumps({"progress": [], "setbacks": [], "action": ""}))

    response = ai_app_client.post(f"{GOALS}/weekly", json={}, headers=auth)

    assert response.status_code == 422
    assert response.json()["code"] == "ai_unreadable"


# ── Sans clé, rien n'est bloqué (`IA-07`) ─────────────


def test_without_a_key_the_proposal_refuses_with_a_catalogue_code(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """`AiServiceDep` fait échouer l'endpoint avant qu'il ne s'exécute : l'appelant n'a
    rien à vérifier lui-même."""
    response = propose(store_client, auth)

    assert response.status_code == 503
    assert response.json()["code"] == "ai_unavailable"


def test_without_a_key_the_weekly_review_refuses_but_the_history_answers(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """L'IA est un confort, jamais un prérequis : les bilans déjà conservés se relisent."""
    assert store_client.post(f"{GOALS}/weekly", json={}, headers=auth).status_code == 503
    assert store_client.get(f"{GOALS}/weekly", headers=auth).status_code == 200


def test_without_a_key_the_planning_proposal_still_reads_the_active_goal(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """La lecture de l'objectif n'est pas une fonction IA : elle lit un CSV. Sans clé,
    c'est la cascade qui refuse, pas `goals.csv`."""
    dav.seed(
        GOALS_FILE,
        f"{GOALS_HEADER}\n"
        f"abc123,{TODAY.isoformat()},Courir 20 km,weekly_distance_km,20,km,"
        f"{DEADLINE.isoformat()},,ai,active,\n",
    )

    assert store_client.get(GOALS, headers=auth).json()["state"] == "active"
    assert store_client.post("/api/planning/proposal", json={}, headers=auth).status_code == 503
