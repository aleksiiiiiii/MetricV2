"""Le carnet de mémoire (`IA-11`).

Les familles du patron de domaine qui s'appliquent à un fichier de **texte libre** — il n'y
a ni bornes de vraisemblance ni série à calculer, mais tout le reste vaut : l'écriture
réelle dans le CSV, la garde anti-conflit, la préservation de la provenance, et la
résistance à une cellule vide.

**Tout ce fichier tourne sans clé API.** C'est la moitié de DoD que la simulation peut
couvrir : le carnet est un carnet, et l'assistant n'apporte que de *proposer* ce qu'on
aurait noté soi-même (`IA-07`).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.dates import today_local
from app.domains.assistant.models import TOPICS, normalise_topic
from tests.fake_webdav import FakeWebDav

ASSISTANT = "/api/assistant"
MEMORY_FILE = "Metric/insights/memory.csv"
MEMORY_HEADER = "id,created,topic,note,source,resolved"

TODAY = today_local()


def remember(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    body = {"topic": "blessure", "note": "Genou droit sensible depuis le 12 juillet", **fields}
    return client.post(f"{ASSISTANT}/memory", json=body, headers=auth)


def remembered(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    response = remember(client, auth, **fields)
    assert response.status_code == 201, response.text
    return response.json()


def view(client: TestClient, auth: dict[str, str]) -> Any:
    response = client.get(f"{ASSISTANT}/memory", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


# ── 1. Écriture réelle dans le CSV ────────────────────


def test_a_note_is_written_with_the_annex_columns(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Colonnes et ordre de l'annexe du backlog, accents et BOM compris."""
    remembered(store_client, auth)

    header, line = dav.content_of(MEMORY_FILE).splitlines()[:2]

    assert header == MEMORY_HEADER
    assert dav.files[MEMORY_FILE].content.startswith(b"\xef\xbb\xbf")
    assert "Genou droit sensible" in line
    # `resolved` vide en dernière colonne : une note naît active, et une cellule vide est
    # ce que le fichier doit porter — pas une date d'aujourd'hui qui la dirait déjà finie.
    assert line.endswith(",manual,")


def test_a_note_written_by_the_assistant_reads_back_as_such(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`IMP-05` appliqué au carnet : l'origine d'une note reste lisible.

    Le carnet se remplit tout seul pendant la conversation désormais, et la colonne
    `source` est ce qui permet, six mois plus tard, de distinguer ce qu'on a noté de ce
    que l'assistant a retenu à notre place. Elle se lit **sans clé API** — c'est tout
    l'objet de ce fichier.
    """
    dav.seed(
        MEMORY_FILE,
        f"{MEMORY_HEADER}\nm1,{TODAY.isoformat()},sommeil,Je dors mal les soirs de séance,ai\n",
    )

    notes = view(store_client, auth)["memories"]

    assert notes[0]["source"] == "ai"
    assert notes[0]["note"] == "Je dors mal les soirs de séance"


def test_the_notebook_comes_back_newest_first(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    remembered(store_client, auth, note="La première note du carnet")
    remembered(store_client, auth, note="La seconde note du carnet")

    notes = [item["note"] for item in view(store_client, auth)["memories"]]

    assert notes[0] == "La seconde note du carnet"


def test_the_suggested_topics_are_served_not_guessed(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """Le client n'en tient pas de copie : une liste recopiée dans deux langages finit par
    ne plus décrire la même chose."""
    assert view(store_client, auth)["topics"] == list(TOPICS)


# ── 2. Bornes ─────────────────────────────────────────


def test_an_empty_note_is_refused(store_client: TestClient, auth: dict[str, str]) -> None:
    """Une note vide n'est pas un souvenir."""
    assert remember(store_client, auth, note="").status_code == 422


def test_an_overlong_note_is_refused(store_client: TestClient, auth: dict[str, str]) -> None:
    """Le carnet part **entier** dans chaque question : c'est ce qui impose la borne."""
    assert remember(store_client, auth, note="x" * 500).status_code == 422


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Blessure", "blessure"),
        ("  SOMMEIL ", "sommeil"),
        ("", "autre"),
        ("kinésithérapie", "kinésithérapie"),
    ],
)
def test_a_topic_is_cleaned_without_being_constrained(raw: str, expected: str) -> None:
    """La liste est **ouverte**. « Je travaille de nuit trois semaines sur quatre » ne
    rentre dans aucune case prévue, et c'est exactement ce que la mémoire existe pour
    porter."""
    assert normalise_topic(raw) == expected


def test_a_topic_outside_the_suggestions_is_accepted(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    entry = remembered(store_client, auth, topic="rythme de travail")

    assert entry["topic"] == "rythme de travail"


# ── 3. Garde anti-conflit ─────────────────────────────


def test_correcting_without_the_header_is_a_conflict_not_a_permission(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    entry = remembered(store_client, auth)

    response = store_client.patch(
        f"{ASSISTANT}/memory/{entry['id']}",
        json={"topic": "blessure", "note": "Une correction sans jeton"},
        headers=auth,
    )

    assert response.status_code == 409
    assert "Une correction sans jeton" not in dav.content_of(MEMORY_FILE)


def test_a_stale_token_leaves_the_file_untouched(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    entry = remembered(store_client, auth)
    before = dav.content_of(MEMORY_FILE)

    response = store_client.delete(
        f"{ASSISTANT}/memory/{entry['id']}", headers={**auth, "If-Match": "jeton-perime"}
    )

    assert response.status_code == 409
    assert dav.content_of(MEMORY_FILE) == before


def test_forgetting_a_note_removes_only_it(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    kept = remembered(store_client, auth, note="Celle qu'on garde absolument")
    doomed = remembered(store_client, auth, note="Celle qu'on retire du carnet")

    response = store_client.delete(
        f"{ASSISTANT}/memory/{doomed['id']}", headers={**auth, "If-Match": doomed["token"]}
    )

    assert response.status_code == 204
    assert "Celle qu'on retire" not in dav.content_of(MEMORY_FILE)
    assert kept["note"] in dav.content_of(MEMORY_FILE)


# ── 4. Préservation de la provenance ──────────────────


def test_correcting_a_note_from_the_assistant_does_not_make_it_manual(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Préciser « genou droit » ne transforme pas une note de l'assistant en note écrite de
    toutes pièces. Même règle qu'une séance déplacée au L13 et qu'une macro retouchée au
    L12.

    Elle compte davantage depuis que le carnet se remplit tout seul : corriger est
    devenu le geste **principal** sur une note, et non plus l'exception.
    """
    dav.seed(
        MEMORY_FILE,
        f"{MEMORY_HEADER}\nm1,{TODAY.isoformat()},blessure,Genou sensible,ai\n",
    )
    entry = view(store_client, auth)["memories"][0]

    corrected = store_client.patch(
        f"{ASSISTANT}/memory/{entry['id']}",
        json={"topic": "blessure", "note": "Genou droit sensible, face interne"},
        headers={**auth, "If-Match": entry["token"]},
    ).json()

    assert corrected["note"] == "Genou droit sensible, face interne"
    assert corrected["source"] == "ai"
    assert corrected["memory_id"] == entry["memory_id"], "l'identifiant survit à la correction"


# ── 5. `memory.csv` est un fichier de carnet ──────────


def test_an_empty_cell_does_not_bring_the_screen_down(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le contrôle direct de la décision qui a coûté le tableau de bord entier au premier
    usage réel, sur un fichier de la même famille."""
    dav.seed(
        MEMORY_FILE,
        f"{MEMORY_HEADER}\nabc123,,,Une note sans date ni sujet,\n",
    )

    body = view(store_client, auth)

    assert len(body["memories"]) == 1
    assert body["memories"][0]["topic"] == "autre", "le sujet manquant retombe sur le repli"
    assert body["memories"][0]["source"] == "manual"


def test_a_line_without_a_note_is_set_aside_but_survives_in_the_file(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """On ne saurait pas quoi afficher. On n'efface pas pour autant ce qu'on ne comprend
    pas."""
    raw = f"{MEMORY_HEADER}\nabc123,{TODAY.isoformat()},sommeil,,manual\n"
    dav.seed(MEMORY_FILE, raw)

    assert view(store_client, auth)["memories"] == []
    assert dav.content_of(MEMORY_FILE) == raw


# ── 6. Sans clé, le carnet est entier (`IA-07`) ───────


def test_the_whole_notebook_works_without_any_api_key(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """`IA-11` : la mémoire est un carnet, pas une fonction IA. Lire, écrire, corriger et
    retirer n'interrogent aucun modèle."""
    entry = remembered(store_client, auth)

    corrected = store_client.patch(
        f"{ASSISTANT}/memory/{entry['id']}",
        json={"topic": "blessure", "note": "Genou droit, ça va mieux depuis le repos"},
        headers={**auth, "If-Match": entry["token"]},
    )
    assert corrected.status_code == 200

    removed = store_client.delete(
        f"{ASSISTANT}/memory/{entry['id']}",
        headers={**auth, "If-Match": corrected.json()["token"]},
    )
    assert removed.status_code == 204
    assert view(store_client, auth)["memories"] == []


def test_without_a_key_the_conversation_refuses_with_a_catalogue_code(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """`AiServiceDep` fait échouer l'endpoint avant qu'il ne s'exécute."""
    response = store_client.post(
        f"{ASSISTANT}/chat", json={"question": "Où j'en suis ?"}, headers=auth
    )

    assert response.status_code == 503
    assert response.json()["code"] == "ai_unavailable"


def test_reading_the_notebook_does_not_create_the_file(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    assert view(store_client, auth)["memories"] == []
    assert MEMORY_FILE not in dav.files


def test_a_timestamp_in_the_created_column_does_not_bring_the_notebook_down(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Même famille, même promesse : le carnet absorbe ce qu'un tableur ou une version
    antérieure y auraient écrit de travers."""
    dav.seed(
        MEMORY_FILE,
        f"{MEMORY_HEADER}\nabc123,2026-07-10T16:26,sommeil,Je dors mal depuis juillet,manual\n",
    )

    body = view(store_client, auth)

    assert len(body["memories"]) == 1
    assert body["memories"][0]["created"] == "2026-07-10"
