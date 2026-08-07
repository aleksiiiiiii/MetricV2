"""Conversation contextuelle et mémoire proposée (`IA-09`, `IA-10`, `IA-12`).

Deux moitiés, comme partout depuis le lot L12 : la conversation ne sait pas écrire, le
carnet ne sait pas interroger un modèle. Entre les deux, un écran et un appui.

**Aucun test de ce fichier ne touche le vrai OpenRouter.** Tout passe par
`tests/fake_openrouter.py`, qui permet en prime de scénariser ce que le vrai service ne
produirait pas sur commande : un modèle qui recopie le condensé dans la mémoire, un autre
qui rend un objet là où la consigne demande une liste.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.core.dates import today_local, week_start
from app.domains.assistant import context
from app.domains.assistant.conversation import INSTRUCTION, build_prompt, read_reply
from tests.fake_openrouter import FakeOpenRouter
from tests.fake_webdav import FakeWebDav

ASSISTANT = "/api/assistant"
MEMORY_FILE = "Metric/insights/memory.csv"
MEMORY_HEADER = "id,created,topic,note,source"
GOALS_FILE = "Metric/goals/goals.csv"
GOALS_HEADER = "id,created,title,metric,target,unit,deadline,rationale,source,status,outcome"
MEALS_FILE = "Metric/nutrition/meals.csv"

TODAY = today_local()

#: Un condensé de référence, à la forme que `context.build` produit réellement.
CONTEXT = [
    "Nous sommes le mercredi 05/08/2026",
    "Objectif en cours : aucun",
    "Séances par semaine : 1,8 séances (moyenne des 4 dernières semaines complètes)",
    "Poids : 80,4 kg (relevé du 03/08/2026)",
]


def answer(**fields: Any) -> str:
    base: dict[str, Any] = {"reply": "Tu tournes à 1,8 séance par semaine.", "remember": []}
    return json.dumps({**base, **fields})


def ask(client: TestClient, auth: dict[str, str], **body: Any) -> Any:
    payload = {"question": "Où j'en suis cette semaine ?", **body}
    return client.post(f"{ASSISTANT}/chat", json=payload, headers=auth)


# ── La relecture, sans rien monter (`IA-10`) ──────────


def test_a_plain_answer_is_read_as_a_reply() -> None:
    reply, remember, dropped = read_reply(json.loads(answer()), context=CONTEXT)

    assert reply == "Tu tournes à 1,8 séance par semaine."
    assert remember == []
    assert dropped == []


def test_a_stated_fact_is_proposed_for_the_notebook() -> None:
    """Le cœur de `IA-10` : ce que l'utilisateur vient de dire sur lui-même."""
    payload = json.loads(
        answer(remember=[{"topic": "blessure", "note": "Genou droit douloureux depuis dix jours"}])
    )

    _, remember, _ = read_reply(payload, context=CONTEXT)

    assert len(remember) == 1
    assert remember[0].topic == "blessure"
    assert "Genou droit" in remember[0].note


def test_a_note_that_only_repeats_the_context_is_dropped() -> None:
    """La décision du lot : la mémoire porte ce que l'utilisateur a dit, pas ce que les
    CSV savent. Une note figeant « 1,8 séance par semaine » serait fausse le mois suivant
    et contredirait le condensé, qui, lui, est recalculé à chaque question."""
    payload = json.loads(
        answer(remember=[{"topic": "autre", "note": "Séances par semaine : 1,8 séances"}])
    )

    _, remember, dropped = read_reply(payload, context=CONTEXT)

    assert remember == []
    assert any("disaient déjà" in reason for reason in dropped)


def test_a_note_that_merely_mentions_a_number_is_kept() -> None:
    """Le test de contenance laisse passer ce qu'un seuil de ressemblance aurait écarté :
    « douleur » et « genou » ne figurent dans aucune statistique."""
    payload = json.loads(
        answer(
            remember=[
                {"topic": "douleur", "note": "Je ne peux pas courir plus de 5 km sans douleur"}
            ]
        )
    )

    _, remember, _ = read_reply(payload, context=CONTEXT)

    assert len(remember) == 1


def test_a_note_already_in_the_notebook_is_not_proposed_twice() -> None:
    """Une mémoire qui se répète à chaque conversation remplirait le carnet de la même
    phrase, et le carnet part entier dans chaque question."""
    note = "Genou droit douloureux depuis dix jours"
    payload = json.loads(answer(remember=[{"topic": "blessure", "note": note}]))

    _, remember, dropped = read_reply(payload, context=CONTEXT, known=[note])

    assert remember == []
    assert any("déjà noté" in reason for reason in dropped)


def test_a_note_too_short_to_mean_anything_is_dropped() -> None:
    """« ok », « le genou » : personne ne les comprendra dans six mois, et les allonger
    reviendrait à les écrire soi-même."""
    payload = json.loads(answer(remember=[{"topic": "autre", "note": "le genou"}]))

    _, remember, _ = read_reply(payload, context=CONTEXT)

    assert remember == []


def test_an_object_where_a_list_was_asked_is_read_all_the_same() -> None:
    """Un modèle rend parfois un objet là où la consigne demande une liste. Le refuser
    coûterait la note, et l'appel payant avec."""
    payload = json.loads(
        answer(
            remember={"topic": "sommeil", "note": "Je dors mal depuis mon changement d'horaires"}
        )
    )

    _, remember, _ = read_reply(payload, context=CONTEXT)

    assert len(remember) == 1


def test_no_more_than_three_notes_come_back() -> None:
    """Une conversation ne révèle pas cinq faits durables d'un coup ; au-delà, le modèle a
    compris qu'on lui demandait de résumer."""
    notes = [
        {"topic": "autre", "note": f"Un fait durable numéro {index} sur ma santé"}
        for index in range(6)
    ]

    _, remember, dropped = read_reply(json.loads(answer(remember=notes)), context=CONTEXT)

    assert len(remember) == 3
    assert dropped


def test_a_shapeless_answer_yields_nothing_rather_than_failing() -> None:
    """Un modèle bavard qui rend `{"texte": "…"}` ne doit pas faire tomber la route."""
    reply, remember, _ = read_reply({"texte": "bonjour"}, context=CONTEXT)

    assert reply == ""
    assert remember == []


# ── La consigne (`IA-09`, `IA-12`) ────────────────────


def test_the_instruction_forbids_playing_doctor() -> None:
    """`IA-12`. Une application de santé dont l'assistant interprète une douleur au genou
    rend un service **négatif** : le conseil paraît sûr du seul fait qu'il est bien
    écrit."""
    assert "pas médecin" in INSTRUCTION
    assert "diagnostic" in INSTRUCTION
    assert "professionnel de santé" in INSTRUCTION


def test_the_prompt_carries_the_context_the_memory_and_the_question() -> None:
    prompt = build_prompt(
        question="Pourquoi je stagne ?",
        context=CONTEXT,
        memory=["blessure — Genou droit sensible"],
    )

    assert "1,8 séances" in prompt
    assert "Genou droit sensible" in prompt
    assert "Pourquoi je stagne ?" in prompt


def test_the_prompt_forbids_copying_the_context_into_the_memory() -> None:
    """On le lui dit **et** on le vérifie : une consigne suivie neuf fois sur dix produit
    une note figée une fois sur dix, et celle-là serait conservée."""
    prompt = build_prompt(question="?", context=CONTEXT, memory=[])

    assert "recalculées à chaque question" in prompt


def test_an_absent_history_leaves_no_empty_heading() -> None:
    """Une rubrique vide dans une consigne invite le modèle à la remplir lui-même."""
    prompt = build_prompt(question="?", context=CONTEXT, memory=[])

    assert "Ce qu'on s'est déjà dit" not in prompt


def test_the_history_comes_back_role_by_role() -> None:
    prompt = build_prompt(
        question="Et la semaine prochaine ?",
        context=CONTEXT,
        memory=[],
        history=[("user", "Où j'en suis ?"), ("assistant", "À 1,8 séance par semaine.")],
    )

    assert "- Moi : Où j'en suis ?" in prompt
    assert "- Toi : À 1,8 séance par semaine." in prompt


# ── Le condensé (`IA-09`) ─────────────────────────────


def test_the_notebook_is_put_into_sentences() -> None:
    """Le carnet est **dit**, le condensé est **mesuré** : deux natures d'information, deux
    rubriques. Les mélanger inviterait le modèle à traiter une phrase de mars comme un
    chiffre d'aujourd'hui."""
    assert context.memory_lines([("blessure", "Genou droit")]) == ["blessure — Genou droit"]


def test_the_notebook_is_bounded_before_it_is_sent() -> None:
    """Le carnet part entier dans chaque question : c'est ce qui impose la borne."""
    entries = [("autre", f"note {index}") for index in range(80)]

    assert len(context.memory_lines(entries)) == context.MAX_MEMORY_LINES


# ── Bout en bout, contre le double ASGI ───────────────


def test_a_conversation_writes_absolutely_nothing(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """Le cœur de `IA-10`, et la moitié de la DoD du lot.

    Ce test échouerait au premier raccourci « tant qu'on y est, notons-le » — le genre de
    raccourci qui paraît inoffensif un vendredi soir.
    """
    openrouter.say(
        answer(remember=[{"topic": "blessure", "note": "Genou droit douloureux depuis dix jours"}])
    )

    response = ask(ai_app_client, auth)

    assert response.status_code == 200, response.text
    assert len(response.json()["remember"]) == 1
    assert MEMORY_FILE not in dav.files


def test_the_reply_publishes_the_context_it_sent(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """`IA-09` publié plutôt que déclaré : `context` est **le** condensé envoyé. C'est ce
    qui rend la promesse vérifiable à l'écran."""
    openrouter.say(answer())

    body = ask(ai_app_client, auth).json()
    sent = openrouter.calls[0].prompt

    assert body["context"]
    assert all(line in sent for line in body["context"])
    assert any("Nous sommes le" in line for line in body["context"])
    assert any("Assiduité de suivi" in line for line in body["context"])


def test_the_whole_files_never_reach_the_model(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """« Condensé factuel, jamais les fichiers entiers », et la règle vaut ici avec plus de
    force qu'ailleurs : une conversation invite à tout envoyer « au cas où ».

    Une note de repas est ce qu'un fichier a de plus personnel et de moins utile à un
    modèle. Elle sert de traceur.
    """
    dav.seed(
        MEALS_FILE,
        "datetime,meal_type,comment,photo,protein_g,added_sugar_g,calories,source\n"
        f"{TODAY.isoformat()}T12:30:00+02:00,dejeuner,"
        "Déjeuner avec Camille avant le rendez-vous médical,,40,5,600,manual\n",
    )
    openrouter.say(answer())

    ask(ai_app_client, auth)
    sent = openrouter.calls[0].prompt

    assert "Camille" not in sent
    assert "rendez-vous médical" not in sent
    assert "Protéines" in sent, "le chiffre, lui, part bien"


def test_the_notebook_reaches_the_next_conversation(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """C'est toute la raison d'être du carnet : ce qu'on a retenu sert au tour suivant."""
    dav.seed(
        MEMORY_FILE,
        f"{MEMORY_HEADER}\n"
        f"abc123,{TODAY.isoformat()},blessure,Genou droit douloureux depuis dix jours,ai\n",
    )
    openrouter.say(answer())

    ask(ai_app_client, auth)

    assert "Genou droit douloureux" in openrouter.calls[0].prompt


def test_the_active_goal_reaches_the_conversation(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    dav.seed(
        GOALS_FILE,
        f"{GOALS_HEADER}\n"
        f"g1,{TODAY.isoformat()},Trois séances par semaine,weekly_sessions,3,séances,"
        f"{(TODAY + timedelta(weeks=6)).isoformat()},,ai,active,\n",
    )
    openrouter.say(answer())

    ask(ai_app_client, auth)

    assert "Trois séances par semaine" in openrouter.calls[0].prompt


def test_the_plan_versus_done_gap_reaches_the_conversation(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """`PLAN-06` alimente le condensé et en détient l'unique implémentation."""
    monday = week_start(TODAY)
    dav.seed(
        "Metric/planning/plan.csv",
        "id,date,time,kind,title,duration_min,note,source\n"
        f"p1,{monday.isoformat()},18:30,muscu,Haut du corps,60,,manual\n",
    )
    openrouter.say(answer())

    body = ask(ai_app_client, auth).json()

    assert any("Respect du planning" in line for line in body["context"])


def test_the_client_can_no_longer_supply_a_history(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """Le passé vient du fil, pas de l'appelant.

    Il était rendu par l'écran à chaque question. Sans portée tant que rien ne s'écrivait ;
    ça n'en est plus une dès lors qu'une réponse peut agir sur les données — un client
    fabriquerait alors le passé qui justifie l'action qu'il veut voir prendre.

    Le champ n'est plus au contrat : un client qui l'envoie se le voit refuser.
    """
    openrouter.say(answer())

    refuse = ask(ai_app_client, auth, history=[{"role": "user", "content": "inventé"}])

    assert refuse.status_code == 422


def test_the_history_comes_from_the_thread_and_is_bounded(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """Le fil nourrit la consigne, et il est reborné — la facture se compte en jetons."""
    openrouter.say(answer())
    thread_id = ask(ai_app_client, auth, question="tour numéro 0").json()["thread_id"]

    # Sept tours de plus : quatorze messages, au-delà des douze que la consigne emporte.
    for index in range(1, 8):
        openrouter.say(answer())
        ask(ai_app_client, auth, question=f"tour numéro {index}", thread_id=thread_id)

    openrouter.say(answer())
    ask(ai_app_client, auth, question="et donc ?", thread_id=thread_id)

    prompt = openrouter.calls[-1].prompt
    assert "tour numéro 7" in prompt, "le fil doit nourrir la consigne"
    assert "tour numéro 0" not in prompt, "et il doit être reborné"


def test_an_overlong_question_is_refused(ai_app_client: TestClient, auth: dict[str, str]) -> None:
    assert ask(ai_app_client, auth, question="x" * 2000).status_code == 422


def test_an_answer_with_nothing_usable_is_refused_with_a_catalogue_code(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """La chaîne a fonctionné, la réponse ne contient rien d'affichable. `422` et non
    `503` : rien n'est en panne, reformuler est la conduite utile."""
    openrouter.say(json.dumps({"remember": []}))

    response = ask(ai_app_client, auth)

    assert response.status_code == 422
    assert response.json()["code"] == "ai_unreadable"


def test_no_image_ever_accompanies_a_question(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """Une conversation ne descend jamais dans la cascade vision (`IA-04`)."""
    openrouter.say(answer())

    ask(ai_app_client, auth)

    assert openrouter.calls[0].with_image is False


def test_adopting_a_proposed_note_writes_it_marked_ai(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """Le second temps de `IA-10` : ce qui a été relu s'enregistre, et pas avant."""
    openrouter.say(
        answer(remember=[{"topic": "sommeil", "note": "Je dors mal les soirs de séance tardive"}])
    )
    proposed = ask(ai_app_client, auth).json()["remember"][0]

    response = ai_app_client.post(
        f"{ASSISTANT}/memory/adopt",
        json={"topic": proposed["topic"], "note": proposed["note"]},
        headers=auth,
    )

    assert response.status_code == 201
    assert response.json()["source"] == "ai"
    assert dav.content_of(MEMORY_FILE).count("\n") == 2  # en-tête + une note
