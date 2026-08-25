"""Les fils de discussion de l'assistant (`IA-13`).

Le serveur ne stockait rien : l'écran rendait l'historique à chaque question et le perdait
au rechargement. Ce fichier couvre ce qui remplace cette absence — un fil qui a une
identité, qui se retrouve, qui se relit et qui se supprime.

**Tout ce fichier tourne sans clé API.** C'est délibéré et c'est la même règle que pour le
carnet (`IA-07`) : relire ce qu'on s'est dit ne demande aucun modèle, et une panne
d'OpenRouter ne doit pas fermer l'accès à ses propres discussions. Ce que la conversation
*écrit* dans un fil est couvert par `test_assistant_ai.py`, qui monte la doublure.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.fake_webdav import FakeWebDav

ASSISTANT = "/api/assistant"

THREADS_FILE = "Metric/assistant/threads.csv"
MESSAGES_FILE = "Metric/assistant/messages.csv"

THREADS_HEADER = "id,created,updated,title"
MESSAGES_HEADER = "thread_id,seq,role,content,created,actions,context"


def seed(dav: FakeWebDav, threads: str = "", messages: str = "") -> None:
    """Pose des fils déjà écrits, sans passer par un modèle."""
    dav.seed(THREADS_FILE, f"{THREADS_HEADER}\n{threads}")
    dav.seed(MESSAGES_FILE, f"{MESSAGES_HEADER}\n{messages}")


def threads(client: TestClient, auth: dict[str, str]) -> Any:
    response = client.get(f"{ASSISTANT}/threads", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()["threads"]


# ── 1. Lire ───────────────────────────────────────────


def test_an_empty_store_has_no_thread(store_client: TestClient, auth: dict[str, str]) -> None:
    """Aucun fichier n'existe encore : la liste est vide, pas en erreur."""
    assert threads(store_client, auth) == []


def test_threads_come_back_most_recently_active_first(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """C'est `updated` qui trie, pas `created` : un fil rouvert remonte.

    Sans quoi la discussion qu'on vient de poursuivre resterait au fond de la liste, ce
    qui est exactement l'inverse de ce qu'on cherche en l'ouvrant.
    """
    seed(
        dav,
        threads=(
            "aaa,2026-08-01T09:00:00+02:00,2026-08-01T09:00:00+02:00,Ancien fil\n"
            "bbb,2026-08-02T09:00:00+02:00,2026-08-07T18:00:00+02:00,Fil rouvert\n"
            "ccc,2026-08-05T09:00:00+02:00,2026-08-05T09:00:00+02:00,Fil du milieu\n"
        ),
    )

    titles = [item["title"] for item in threads(store_client, auth)]

    assert titles == ["Fil rouvert", "Fil du milieu", "Ancien fil"]


def test_a_thread_carries_its_message_count(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """La liste s'affiche sans charger les messages, mais elle sait combien il y en a."""
    seed(
        dav,
        threads="aaa,2026-08-01T09:00:00+02:00,2026-08-01T09:00:00+02:00,Un fil\n",
        messages=(
            "aaa,0,user,Bonjour,2026-08-01T09:00:00+02:00,\n"
            "aaa,1,assistant,Salut,2026-08-01T09:00:01+02:00,\n"
        ),
    )

    assert threads(store_client, auth)[0]["messages"] == 2


def test_a_thread_reads_back_in_the_order_it_was_written(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`seq` ordonne, et non l'horodatage — deux tours peuvent tomber la même seconde."""
    seed(
        dav,
        threads="aaa,2026-08-01T09:00:00+02:00,2026-08-01T09:00:00+02:00,Un fil\n",
        messages=(
            "aaa,1,assistant,La réponse,2026-08-01T09:00:00+02:00,\n"
            "aaa,0,user,La question,2026-08-01T09:00:00+02:00,\n"
        ),
    )

    body = store_client.get(f"{ASSISTANT}/threads/aaa", headers=auth).json()

    assert [item["content"] for item in body["messages"]] == ["La question", "La réponse"]


def test_a_thread_only_carries_its_own_messages(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Un seul fichier pour tous les fils : le filtre par `thread_id` est la garantie."""
    seed(
        dav,
        threads=(
            "aaa,2026-08-01T09:00:00+02:00,2026-08-01T09:00:00+02:00,Premier\n"
            "bbb,2026-08-02T09:00:00+02:00,2026-08-02T09:00:00+02:00,Second\n"
        ),
        messages=(
            "aaa,0,user,Pour le premier,2026-08-01T09:00:00+02:00,\n"
            "bbb,0,user,Pour le second,2026-08-02T09:00:00+02:00,\n"
        ),
    )

    body = store_client.get(f"{ASSISTANT}/threads/aaa", headers=auth).json()

    assert [item["content"] for item in body["messages"]] == ["Pour le premier"]


def test_an_unknown_thread_is_a_not_found(store_client: TestClient, auth: dict[str, str]) -> None:
    response = store_client.get(f"{ASSISTANT}/threads/inconnu", headers=auth)

    assert response.status_code == 404
    assert response.json()["code"] == "storage_not_found"


# ── 2. Résister à ce qu'un tableur peut écrire ────────


def test_a_thread_retyped_without_its_offset_does_not_break_the_list(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """La promesse de la famille *planning* : une ligne abîmée coûte un fil, pas l'écran.

    Comparer un horodatage naïf à un horodatage situé lève une `TypeError` en Python. Une
    seule ligne retapée dans un tableur sans son décalage suffirait donc à rendre toute la
    liste inaccessible en `502` — c'est la panne qu'un `goals.csv` a déjà causée.
    """
    seed(
        dav,
        threads=(
            "aaa,2026-08-01T09:00:00+02:00,2026-08-01T09:00:00+02:00,Avec décalage\n"
            "bbb,2026-08-02 09:00:00,2026-08-02 09:00:00,Retapé à la main\n"
        ),
    )

    titles = [item["title"] for item in threads(store_client, auth)]

    assert titles == ["Retapé à la main", "Avec décalage"]


def test_a_thread_without_any_date_stays_readable(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Une cellule vide est une possibilité normale : le fil descend, il ne disparaît pas."""
    seed(
        dav,
        threads=("aaa,,,Sans date\nbbb,2026-08-02T09:00:00+02:00,2026-08-02T09:00:00+02:00,Daté\n"),
    )

    titles = [item["title"] for item in threads(store_client, auth)]

    assert titles == ["Daté", "Sans date"]


def test_a_thread_without_an_id_is_dropped_from_the_view_but_kept_in_the_file(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """On n'affiche pas ce qu'on ne saurait pas ouvrir — et on n'efface pas pour autant.

    Même règle que pour une note de carnet sans identifiant : la ligne survit dans le
    fichier, parce qu'on n'efface pas ce qu'on ne comprend pas.
    """
    seed(
        dav,
        threads=(
            ",2026-08-01T09:00:00+02:00,2026-08-01T09:00:00+02:00,Orphelin\n"
            "bbb,2026-08-02T09:00:00+02:00,2026-08-02T09:00:00+02:00,Lisible\n"
        ),
    )

    assert [item["title"] for item in threads(store_client, auth)] == ["Lisible"]
    assert "Orphelin" in dav.content_of(THREADS_FILE)


# ── 3. Supprimer ──────────────────────────────────────


def test_deleting_a_thread_takes_its_messages_with_it(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Sans quoi le fichier de messages ne ferait que croître, avec des orphelins."""
    seed(
        dav,
        threads=(
            "aaa,2026-08-01T09:00:00+02:00,2026-08-01T09:00:00+02:00,À supprimer\n"
            "bbb,2026-08-02T09:00:00+02:00,2026-08-02T09:00:00+02:00,À garder\n"
        ),
        messages=(
            "aaa,0,user,Message du fil supprimé,2026-08-01T09:00:00+02:00,\n"
            "bbb,0,user,Message du fil gardé,2026-08-02T09:00:00+02:00,\n"
        ),
    )

    assert store_client.delete(f"{ASSISTANT}/threads/aaa", headers=auth).status_code == 204

    assert [item["title"] for item in threads(store_client, auth)] == ["À garder"]
    remaining = dav.content_of(MESSAGES_FILE)
    assert "Message du fil supprimé" not in remaining
    assert "Message du fil gardé" in remaining


def test_deleting_an_unknown_thread_is_a_not_found(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    assert store_client.delete(f"{ASSISTANT}/threads/inconnu", headers=auth).status_code == 404


def test_clearing_every_thread_leaves_the_notebook_untouched(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le partage voulu entre les deux (`IA-11`).

    Ce qui a été retenu survit à l'effacement des discussions qui l'ont produit : le
    carnet est un carnet, pas un journal de conversation.
    """
    seed(
        dav,
        threads="aaa,2026-08-01T09:00:00+02:00,2026-08-01T09:00:00+02:00,Un fil\n",
        messages="aaa,0,user,Quelque chose,2026-08-01T09:00:00+02:00,\n",
    )
    dav.seed(
        "Metric/insights/memory.csv",
        "id,created,topic,note,source\nm1,2026-08-01,blessure,Genou droit sensible,ai\n",
    )

    assert store_client.delete(f"{ASSISTANT}/threads", headers=auth).status_code == 204

    assert threads(store_client, auth) == []
    memories = store_client.get(f"{ASSISTANT}/memory", headers=auth).json()["memories"]
    assert [item["note"] for item in memories] == ["Genou droit sensible"]


# ── 4. Renommer (`C04-3`) ─────────────────────────────

# Les titres sont écrits par le modèle à l'ouverture, et il se trompe. On ne pouvait que
# supprimer le fil — ce qui emportait la conversation avec son mauvais titre.


def test_a_thread_can_be_renamed(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    seed(dav, threads="f1,2026-08-01T09:00:00+02:00,2026-08-01T09:30:00+02:00,Où j’en suis")

    response = store_client.patch(
        f"{ASSISTANT}/threads/f1", json={"title": "Reprise après le genou"}, headers=auth
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Reprise après le genou"
    assert threads(store_client, auth)[0]["title"] == "Reprise après le genou"


def test_renaming_does_not_move_the_thread_up_the_list(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Renommer n'est pas parler.

    Faire remonter un fil parce qu'on a corrigé son libellé rangerait l'historique dans un
    ordre qui ne veut plus rien dire — la liste est triée sur la dernière activité.
    """
    seed(
        dav,
        threads=(
            "vieux,2026-07-01T09:00:00+02:00,2026-07-01T09:00:00+02:00,Ancien\n"
            "recent,2026-08-01T09:00:00+02:00,2026-08-01T09:00:00+02:00,Récent"
        ),
    )

    store_client.patch(f"{ASSISTANT}/threads/vieux", json={"title": "Corrigé"}, headers=auth)

    assert [thread["thread_id"] for thread in threads(store_client, auth)] == ["recent", "vieux"]


def test_an_empty_title_is_refused(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    seed(dav, threads="f1,2026-08-01T09:00:00+02:00,2026-08-01T09:30:00+02:00,Où j’en suis")

    response = store_client.patch(f"{ASSISTANT}/threads/f1", json={"title": "   "}, headers=auth)

    assert response.status_code == 422


def test_renaming_an_unknown_thread_is_a_not_found(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    seed(dav)

    response = store_client.patch(f"{ASSISTANT}/threads/absent", json={"title": "X"}, headers=auth)

    assert response.status_code == 404


def test_renaming_needs_no_api_key(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`IA-07` : corriger un libellé n'a pas à attendre qu'un modèle réponde.

    `store_client` monte l'application **sans** clé OpenRouter : si la route en dépendait,
    ce test rendrait `503`.
    """
    seed(dav, threads="f1,2026-08-01T09:00:00+02:00,2026-08-01T09:30:00+02:00,Titre")

    assert (
        store_client.patch(
            f"{ASSISTANT}/threads/f1", json={"title": "Autre"}, headers=auth
        ).status_code
        == 200
    )


# ── Ce qu'un fil rouvert redonne ──────────────────────


def test_a_reopened_thread_keeps_what_the_turn_did(
    ai_app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """**Le lien d'une séance ne périme pas**, contrairement au jeton d'une ligne.

    Rouvrir un fil pour y retrouver la séance qu'on s'est fait proposer est précisément ce
    qu'on vient y chercher ; les actions sont donc rangées avec la réponse.
    """
    from app.domains.assistant.schemas import ActionReport, UndoRef
    from app.domains.assistant.service import _read_actions, _render_actions

    report = ActionReport(
        name="circuit.create",
        level="add",
        status="done",
        summary="Séance « Abdos » enregistrée.",
        link="https://cadence.exemple.fr?w=Abdos~4~60~Plank:45s:15",
        resource_id="c-abdos",
        undo=UndoRef(domain="activity/circuits", row_id=0, token="jeton"),
    )

    relu = _read_actions(_render_actions([report]))

    assert len(relu) == 1
    assert relu[0].link == report.link
    assert relu[0].resource_id == "c-abdos"
    # Le jeton périme dès que la ligne change : proposer « annuler » trois jours plus tard
    # rendrait un `409` que rien n'explique.
    assert relu[0].undo is None


def test_a_refused_action_is_not_replayed() -> None:
    """Elle n'a rien produit. La relire ferait réapparaître un échec passé comme s'il
    venait d'avoir lieu."""
    from app.domains.assistant.schemas import ActionReport
    from app.domains.assistant.service import _render_actions

    refused = ActionReport(name="x.y", level="add", status="refused", summary="Inconnue.")

    assert _render_actions([refused]) == ""


def test_a_mangled_actions_cell_costs_its_turn_not_the_thread() -> None:
    """Le fichier s'ouvre dans un tableur : une cellule JSON coupée en deux y est une
    possibilité normale, et elle ne doit pas emporter le fil."""
    from app.domains.assistant.service import _read_actions

    assert _read_actions('[{"name": "circuit.create"') == []
    assert _read_actions('{"pas": "une liste"}') == []
    assert _read_actions("   ") == []
