"""Ce que l'assistant écrit réellement dans les données (`IA-15`).

Ce fichier vérifie **que les lignes arrivent dans les CSV** — pas qu'un objet a été rendu.
C'est la différence entre un catalogue qui compile et un assistant qui agit, et c'est la
seule preuve qui vaille pour un lot dont la promesse est d'écrire.

Trois familles :

1. **Les deux niveaux.** Un ajout s'exécute et rend de quoi l'annuler ; un changement
   n'écrit rien tant que personne n'a confirmé. Le niveau vient de la table, jamais du
   modèle.
2. **Les refus.** Un nom inventé, des arguments manquants, un jeton périmé : chacun rend
   une phrase lisible et **aucun ne fait échouer l'échange**.
3. **La provenance.** Ce que l'assistant écrit est marqué `ia` là où le fichier a une
   colonne pour le dire (`IMP-05`).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from app.core.dates import today_local
from tests.fake_openrouter import FakeOpenRouter
from tests.fake_webdav import FakeWebDav

ASSISTANT = "/api/assistant"
TODAY = today_local()


def answer(**fields: Any) -> str:
    """Une réponse de modèle, avec ce qu'on veut y mettre."""
    base: dict[str, Any] = {"reply": "C'est noté.", "remember": [], "actions": []}
    return json.dumps({**base, **fields})


def ask(client: TestClient, auth: dict[str, str], **body: Any) -> Any:
    payload = {"question": "Note ma pesée de 82,4 kg", **body}
    return client.post(f"{ASSISTANT}/chat", json=payload, headers=auth)


def acted(client: TestClient, auth: dict[str, str], **body: Any) -> list[dict[str, Any]]:
    response = ask(client, auth, **body)
    assert response.status_code == 200, response.text
    reports: list[dict[str, Any]] = response.json()["actions"]
    return reports


# ── 1. Un ajout s'exécute ─────────────────────────────


def test_an_add_action_really_writes_the_row(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """La preuve du lot : la ligne est dans le CSV, pas seulement dans la réponse."""
    openrouter.say(
        answer(
            actions=[{"name": "weight.add", "args": {"date": TODAY.isoformat(), "weight_kg": 82.4}}]
        )
    )

    reports = acted(ai_app_client, auth)

    assert reports[0]["status"] == "done"
    assert "82,4" in reports[0]["summary"].replace(".", ",")
    assert "82.4" in dav.content_of("Metric/body/weight.csv")


def test_an_add_action_comes_back_with_what_undoes_it(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """Aucune machinerie d'annulation n'a été inventée.

    L'écran reçoit la ressource, la ligne et son jeton : il appelle la suppression du
    domaine, exactement celle qu'un utilisateur déclenche depuis l'écran Corps.
    """
    openrouter.say(
        answer(
            actions=[{"name": "weight.add", "args": {"date": TODAY.isoformat(), "weight_kg": 82.4}}]
        )
    )

    undo = acted(ai_app_client, auth)[0]["undo"]

    assert undo["domain"] == "body/weight"
    assert undo["row_id"] == 0
    assert undo["token"]


def test_what_the_assistant_writes_is_marked_as_its_own(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """`IMP-05` : une pesée notée par l'assistant n'est pas une pesée relevée à la main.

    La correction préservait déjà la provenance ; c'est la création qui ne savait pas
    encore la dire.
    """
    openrouter.say(
        answer(
            actions=[{"name": "weight.add", "args": {"date": TODAY.isoformat(), "weight_kg": 82.4}}]
        )
    )

    acted(ai_app_client, auth)

    assert dav.content_of("Metric/body/weight.csv").strip().endswith(",ia")


def test_several_actions_run_in_order(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    openrouter.say(
        answer(
            actions=[
                {"name": "water.add", "args": {"volume_ml": 500}},
                {"name": "water.add", "args": {"volume_ml": 250}},
            ]
        )
    )

    reports = acted(ai_app_client, auth)

    assert [item["status"] for item in reports] == ["done", "done"]
    written = dav.content_of("Metric/hydration/intake_log.csv")
    assert "500" in written and "250" in written


# ── 2. Un changement attend ───────────────────────────


def test_a_change_action_writes_nothing_and_waits(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """Le projet n'a pas de corbeille : effacer se demande."""
    dav.seed(
        "Metric/body/weight.csv",
        f"date,weight_kg,note,source\n{TODAY.isoformat()},82.4,,manual\n",
    )
    openrouter.say(
        answer(actions=[{"name": "weight.delete", "args": {"row_id": 0, "token": 'W/"1"'}}])
    )

    reports = acted(ai_app_client, auth)

    assert reports[0]["status"] == "pending"
    assert reports[0]["level"] == "change"
    assert "82.4" in dav.content_of("Metric/body/weight.csv"), "rien ne doit être écrit"


def test_a_pending_action_is_executed_by_confirming_it(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """Le second appui, et il n'interroge aucun modèle."""
    dav.seed(
        "Metric/body/weight.csv",
        f"date,weight_kg,note,source\n{TODAY.isoformat()},82.4,,manual\n",
    )
    openrouter.say(answer(actions=[{"name": "weight.delete", "args": {"row_id": 0, "token": "x"}}]))
    pending = acted(ai_app_client, auth)[0]

    # Le jeton d'une ligne est l'empreinte de son contenu, et non l'etag du fichier :
    # c'est ce que l'API expose, et donc ce que le condensé donnera au modèle.
    listed = ai_app_client.get("/api/body/weight", headers=auth).json()["entries"]
    token = listed[0]["token"]
    response = ai_app_client.post(
        f"{ASSISTANT}/actions/confirm",
        json={"name": pending["name"], "args": {"row_id": 0, "token": token}},
        headers=auth,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "done"
    assert "82.4" not in dav.content_of("Metric/body/weight.csv")


def test_confirming_still_obeys_the_conflict_guard(
    ai_app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`STO-05` vaut pour l'assistant comme pour un écran.

    Une action fabriquée sur une ligne lue il y a dix minutes échoue au lieu d'effacer la
    mauvaise — c'est toute la raison d'exiger le jeton dans les arguments.
    """
    dav.seed(
        "Metric/body/weight.csv",
        f"date,weight_kg,note,source\n{TODAY.isoformat()},82.4,,manual\n",
    )

    response = ai_app_client.post(
        f"{ASSISTANT}/actions/confirm",
        json={"name": "weight.delete", "args": {"row_id": 0, "token": "périmé"}},
        headers=auth,
    )

    assert response.json()["status"] == "refused"
    assert "82.4" in dav.content_of("Metric/body/weight.csv")


def test_confirming_revalidates_against_the_catalogue(
    ai_app_client: TestClient, auth: dict[str, str]
) -> None:
    """Rien n'est retenu entre la proposition et la confirmation.

    Donc rien ne peut être confirmé qui n'aurait pas pu être demandé — la confirmation
    repasse par la même porte que le modèle.
    """
    response = ai_app_client.post(
        f"{ASSISTANT}/actions/confirm",
        json={"name": "database.drop", "args": {}},
        headers=auth,
    )

    assert response.json()["status"] == "refused"
    assert "sais faire" in response.json()["summary"]


# ── 3. Les refus ne coûtent jamais l'échange ──────────


def test_an_unknown_action_is_refused_without_losing_the_reply(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """Un `500` parce que le modèle a mal nommé une action perdrait la réponse *et* la
    question, pour un tour où il a peut-être surtout bien répondu."""
    openrouter.say(
        answer(reply="Voilà où tu en es.", actions=[{"name": "weight.update", "args": {}}])
    )

    body = ask(ai_app_client, auth).json()

    assert body["reply"] == "Voilà où tu en es."
    assert body["actions"][0]["status"] == "refused"


def test_missing_arguments_say_what_is_missing(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """La raison est destinée à être lue.

    Si l'assistant a compris « ajoute ma séance » sans savoir combien de temps elle a
    duré, le dire vaut mieux que de laisser croire que c'est fait.
    """
    openrouter.say(answer(actions=[{"name": "weight.add", "args": {"weight_kg": 82.4}}]))

    report = acted(ai_app_client, auth)[0]

    assert report["status"] == "refused"
    assert "date" in report["summary"]


def test_a_domain_refusal_comes_back_in_french(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """L'IA ne peut rien que l'API ne permettrait : la borne du domaine s'applique.

    C'est la garantie centrale du catalogue — pas de validation parallèle, pas de chemin
    d'écriture parallèle. Une borne ajoutée un jour au domaine protège l'assistant le
    jour même, sans que personne y pense.
    """
    openrouter.say(
        answer(
            actions=[{"name": "weight.add", "args": {"date": TODAY.isoformat(), "weight_kg": 9000}}]
        )
    )

    report = acted(ai_app_client, auth)[0]

    assert report["status"] == "refused"
    assert report["summary"]


def test_a_bad_action_does_not_stop_the_good_one(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """Une réponse à moitié bonne vaut mieux qu'un échange perdu."""
    openrouter.say(
        answer(
            actions=[
                {"name": "inventé", "args": {}},
                {"name": "water.add", "args": {"volume_ml": 500}},
            ]
        )
    )

    reports = acted(ai_app_client, auth)

    assert [item["status"] for item in reports] == ["refused", "done"]
    assert "500" in dav.content_of("Metric/hydration/intake_log.csv")


# ── 4. Le cas normal : aucune action ──────────────────


def test_a_plain_question_writes_nothing(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """Et c'est le cas de très loin le plus fréquent.

    La consigne insiste là-dessus : un modèle à qui on offre une possibilité la prend, et
    chaque « où j'en suis ? » repartirait sinon avec une séance ajoutée.
    """
    openrouter.say(answer(reply="Tu tournes à 1,8 séance par semaine."))

    assert acted(ai_app_client, auth, question="Où j'en suis ?") == []


def test_the_catalogue_is_shown_to_the_model(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """Sans la liste, le modèle ne peut nommer aucune action — et n'en invente pas moins."""
    openrouter.say(answer())

    ask(ai_app_client, auth)

    prompt = openrouter.calls[0].prompt
    assert "weight.add" in prompt
    assert "Ce que tu peux faire dans mes données" in prompt


# ── 5. La seconde passe, et jamais de troisième (`IA-16`) ──


def test_a_requested_slice_comes_back_in_a_second_call(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """Supprimer le repas de midi demande son identifiant, et il n'est pas dans le condensé.

    Le charger dans **chaque** question reviendrait à envoyer les fichiers, ce que `IA-09`
    interdit précisément. D'où la demande, et la tranche servie en réponse.
    """
    dav.seed(
        "Metric/body/weight.csv",
        f"date,weight_kg,note,source\n{TODAY.isoformat()},82.4,,manual\n",
    )
    openrouter.say(answer(reply="Je regarde.", need=["pesees_recentes"]))
    openrouter.say(answer(reply="Voilà."))

    ask(ai_app_client, auth, question="Supprime ma dernière pesée")

    assert len(openrouter.calls) == 2
    # Le *nom* de la tranche est offert dès le premier tour — c'est ainsi que le modèle
    # sait pouvoir la demander. C'est son *contenu* qui n'arrive qu'au second.
    assert "row_id=" not in openrouter.calls[0].prompt
    assert "row_id=0" in openrouter.calls[1].prompt


def test_a_second_request_for_context_is_not_honoured(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """Le plafond est dans la forme du code : il y a deux appels parce qu'il y en a deux.

    Aucune borne à respecter, aucune récursion à surveiller — et donc aucune façon pour un
    modèle de faire tourner l'écran en réclamant indéfiniment.
    """
    openrouter.say(answer(reply="Je regarde.", need=["pesees_recentes"]))
    openrouter.say(answer(reply="Encore.", need=["exercices"]))

    response = ask(ai_app_client, auth, question="Supprime ma dernière pesée")

    assert response.status_code == 200
    assert len(openrouter.calls) == 2


def test_an_invented_slice_never_becomes_a_read(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """Le modèle choisit dans une liste, il ne nomme pas un fichier.

    Sans ce filtre, `"need": ["/etc/passwd"]` serait une demande comme une autre — et le
    seul rempart serait la bonne volonté du modèle.
    """
    openrouter.say(answer(reply="Je regarde.", need=["/etc/passwd", "tout"]))

    ask(ai_app_client, auth)

    assert len(openrouter.calls) == 1, "rien à servir : pas de seconde passe"


def test_the_offered_slices_are_named_in_the_prompt(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """Un modèle ne demande pas ce qu'il ignore pouvoir demander."""
    openrouter.say(answer())

    ask(ai_app_client, auth)

    assert "repas_du_jour" in openrouter.calls[0].prompt


def test_a_slice_carries_the_token_a_deletion_needs(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """C'est ce qui referme la boucle, et c'est une garantie de sécurité.

    Une suppression exige le jeton de la ligne (`STO-05`), et le seul endroit où le modèle
    peut l'obtenir est une tranche qu'on lui a servie. Il ne peut donc pas effacer une
    ligne qu'il n'a pas lue.
    """
    dav.seed(
        "Metric/body/weight.csv",
        f"date,weight_kg,note,source\n{TODAY.isoformat()},82.4,,manual\n",
    )
    openrouter.say(answer(reply="Je regarde.", need=["pesees_recentes"]))
    openrouter.say(answer(reply="Voilà."))

    ask(ai_app_client, auth, question="Supprime ma dernière pesée")

    second = openrouter.calls[1].prompt
    assert "token=" in second
    assert "82,4 kg" in second or "82.4 kg" in second


# ── 6. L'annulation vise de vraies routes ─────────────


def test_every_undo_domain_is_a_real_delete_route(ai_app_client: TestClient) -> None:
    """Le nom d'un domaine d'annulation **est** le chemin de sa ressource.

    L'écran ne tient aucune table de correspondance : il appelle
    `DELETE /api/{domain}/{row_id}`. Une faute de frappe dans le catalogue ne se verrait
    donc qu'au moment où l'utilisateur appuie sur « annuler », c'est-à-dire au pire
    moment — juste après que l'assistant a écrit quelque chose qu'il ne voulait pas.

    Ce test lit les routes réellement publiées et refuse un nom qui n'en désigne aucune.
    """
    from app.domains.assistant import actions as catalogue

    published = {
        path
        for path, operations in ai_app_client.app.openapi()["paths"].items()  # type: ignore[attr-defined]
        if "delete" in operations
    }

    domains = {
        "body/weight",
        "hydration",
        "nutrition",
        "activity/runs",
        "activity/workouts",
        "activity/exercises",
        "planning/sessions",
    }
    for domain in domains:
        assert f"/api/{domain}/{{row_id}}" in published, domain

    # Et le catalogue n'en emploie pas d'autres : sans cette moitié, ajouter demain une
    # action avec un domaine inventé passerait au travers.
    source = (catalogue.__file__ or "").replace(".pyc", ".py")
    with open(source, encoding="utf-8") as handle:
        used = {
            line.split('Undo("', 1)[1].split('"', 1)[0]
            for line in handle
            if 'Undo("' in line and "class" not in line
        }
    assert used <= domains, f"domaines inconnus : {used - domains}"
