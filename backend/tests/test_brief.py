"""La lecture du jour : relecture pure, routes, semis du fil, ordonnanceur.

Quatre moitiés, et la séparation est la garantie du lot :

* `compose.py` est **pur** — sa relecture s'éprouve sur des dictionnaires fixes, sans
  monter d'application ni toucher un fichier.
* `GET` lit et `POST` écrit — un test le vérifie plutôt que de faire confiance à la phrase.
* Le fil est semé **au premier appui**, et le second rend le même.
* L'ordonnanceur fait une passe quand on la lui demande : `tick()` prend l'instant, il ne
  dort jamais. Sans cette séparation, ce fichier attendrait une heure pour vérifier qu'il
  ne s'est rien passé.

**Aucun test ici ne touche le vrai OpenRouter**, pour la raison déjà écrite dans
`test_goals_ai.py` : un appel réel est non déterministe, et une batterie branchée dessus
dirait tantôt vert tantôt rouge sans qu'une ligne de code ait bougé.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.dates import today_local
from app.domains.brief import compose
from app.domains.brief.models import current_slot
from app.domains.brief.scheduler import BriefScheduler
from app.domains.brief.service import BriefService
from app.storage.files import FileStore
from tests.fake_openrouter import FakeOpenRouter
from tests.fake_webdav import FakeWebDav

BRIEF = "/api/brief"
BRIEF_FILE = "Metric/insights/brief.csv"
THREADS_FILE = "Metric/assistant/threads.csv"
MESSAGES_FILE = "Metric/assistant/messages.csv"

TODAY = today_local()


def _text(dav: FakeWebDav, path: str) -> str:
    """Le contenu d'un fichier du faux WebDAV, en clair."""
    return dav.files[path].content.decode("utf-8-sig")


def _rows(dav: FakeWebDav, path: str) -> list[list[str]]:
    """Les lignes **CSV** d'un fichier, en-tête compris.

    Et non `splitlines()` : la colonne `basis` porte le condensé, une ligne par élément,
    donc des sauts de ligne protégés par des guillemets. Les compter comme des lignes de
    fichier donnerait trente et une lignes pour trois lectures.
    """
    return list(csv.reader(io.StringIO(_text(dav, path))))


LECTURE = (
    "Deux séances cette semaine sur les **3** visées, et le poids descend de **0,4 kg**. "
    "Il reste une séance d'ici dimanche."
)


def answer(message: str = LECTURE) -> str:
    return json.dumps({"message": message})


# ── La relecture, sans rien monter ────────────────────


def test_read_message_takes_the_string() -> None:
    assert compose.read_message({"message": "  Belle semaine.  "}) == "Belle semaine."


def test_read_message_joins_a_list() -> None:
    """Les modèles gratuits alternent entre une chaîne et une liste pour la même consigne.

    Refuser la seconde coûterait une lecture sur deux ; l'accepter coûte trois lignes.
    """
    assert compose.read_message({"message": ["Deux séances.", "Encore une."]}) == (
        "Deux séances. Encore une."
    )


@pytest.mark.parametrize("raw", ["", "   ", "null", "None", "—", True, None, 0])
def test_read_message_refuses_what_means_nothing(raw: object) -> None:
    """« null » rendu en toutes lettres ne doit jamais arriver à l'écran comme une lecture."""
    assert compose.read_message({"message": raw}) == ""


def test_read_message_is_bounded() -> None:
    assert len(compose.read_message({"message": "a" * 5000})) == 600


def test_prompt_carries_the_facts_and_the_weekday() -> None:
    """Un modèle n'a pas de calendrier : le jour lui est donné, il ne le déduit pas."""
    prompt = compose.build_prompt(day=date(2026, 8, 19), context=["Poids : 78,4 kg"])
    assert "mercredi" in prompt
    assert "19/08/2026" in prompt
    assert "- Poids : 78,4 kg" in prompt


def test_prompt_says_when_there_is_nothing() -> None:
    """Un condensé vide se dit, il ne se laisse pas deviner par une section absente."""
    assert "Aucune donnée relevée." in compose.build_prompt(day=TODAY, context=[])


# ── Les routes ────────────────────────────────────────


def test_get_is_absent_before_anything_is_written(
    ai_app_client: TestClient, auth: dict[str, str]
) -> None:
    """`GET` ne réveille aucun modèle et n'écrit rien : il dit qu'il n'y a rien."""
    body = ai_app_client.get(BRIEF, headers=auth).json()

    assert body["state"] == "absent"
    assert body["message"] == ""
    assert body["thread_id"] is None
    assert body["day"] == TODAY.isoformat()


def test_get_writes_nothing(
    ai_app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    ai_app_client.get(BRIEF, headers=auth)
    assert BRIEF_FILE not in dav.files


def test_post_writes_the_reading(
    ai_app_client: TestClient,
    auth: dict[str, str],
    openrouter: FakeOpenRouter,
    dav: FakeWebDav,
) -> None:
    openrouter.say(answer())

    body = ai_app_client.post(BRIEF, headers=auth).json()

    assert body["state"] == "ready"
    assert body["message"] == LECTURE
    # Le condensé est publié : c'est la seule façon de vérifier à l'écran que les fichiers
    # n'ont pas été envoyés entiers (`IA-09`).
    assert body["basis"]
    assert LECTURE in _text(dav, BRIEF_FILE)


def test_get_then_serves_what_was_written(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    openrouter.say(answer())
    ai_app_client.post(BRIEF, headers=auth)

    body = ai_app_client.get(BRIEF, headers=auth).json()
    assert body["state"] == "ready"
    assert body["message"] == LECTURE


def test_one_day_one_row(
    ai_app_client: TestClient,
    auth: dict[str, str],
    openrouter: FakeOpenRouter,
    dav: FakeWebDav,
) -> None:
    """Régénérer **remplace** : deux lignes pour le 19 août rendraient la lecture ambiguë."""
    openrouter.say(answer("Première."), answer("Seconde."))

    ai_app_client.post(BRIEF, headers=auth)
    ai_app_client.post(BRIEF, headers=auth)

    rows = [line for line in _text(dav, BRIEF_FILE).splitlines() if TODAY.isoformat() in line]
    assert len(rows) == 1
    assert ai_app_client.get(BRIEF, headers=auth).json()["message"] == "Seconde."


def test_unreadable_answer_is_an_error_not_an_empty_reading(
    ai_app_client: TestClient,
    auth: dict[str, str],
    openrouter: FakeOpenRouter,
    dav: FakeWebDav,
) -> None:
    """Un modèle muet ne doit pas ranger une lecture vide qui se lirait comme « rien à dire »."""
    openrouter.say(json.dumps({"message": ""}))

    response = ai_app_client.post(BRIEF, headers=auth)

    assert response.status_code >= 400
    assert BRIEF_FILE not in dav.files


def test_brief_requires_a_token(client: TestClient) -> None:
    assert client.get(BRIEF).status_code == 401


# ── Le fil semé ───────────────────────────────────────


def test_thread_is_seeded_on_first_press(
    ai_app_client: TestClient,
    auth: dict[str, str],
    openrouter: FakeOpenRouter,
    dav: FakeWebDav,
) -> None:
    """Le fil commence **sur le message de l'assistant**, et non sur une question vide.

    C'est ce qui fait que « répondre à ce message-là » a un sens : le modèle voit son
    propre texte dans l'historique du fil au tour suivant.
    """
    openrouter.say(answer())
    ai_app_client.post(BRIEF, headers=auth)

    thread_id = ai_app_client.post(f"{BRIEF}/thread", headers=auth).json()["thread_id"]

    assert thread_id
    messages = _text(dav, MESSAGES_FILE)
    assert "assistant" in messages
    assert LECTURE in messages
    detail = ai_app_client.get(f"/api/assistant/threads/{thread_id}", headers=auth).json()
    assert [turn["role"] for turn in detail["messages"]] == ["assistant"]
    assert detail["messages"][0]["content"] == LECTURE


def test_thread_is_not_created_before_it_is_asked_for(
    ai_app_client: TestClient,
    auth: dict[str, str],
    openrouter: FakeOpenRouter,
    dav: FakeWebDav,
) -> None:
    """Semer à la génération remplirait « Discussions » de lectures que personne n'a lues."""
    openrouter.say(answer())
    ai_app_client.post(BRIEF, headers=auth)

    assert THREADS_FILE not in dav.files
    assert ai_app_client.get(BRIEF, headers=auth).json()["thread_id"] is None


def test_pressing_twice_continues_the_same_thread(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    openrouter.say(answer())
    ai_app_client.post(BRIEF, headers=auth)

    first = ai_app_client.post(f"{BRIEF}/thread", headers=auth).json()["thread_id"]
    second = ai_app_client.post(f"{BRIEF}/thread", headers=auth).json()["thread_id"]

    assert first == second
    assert ai_app_client.get(BRIEF, headers=auth).json()["thread_id"] == first


def test_thread_without_a_reading_is_a_not_found(
    ai_app_client: TestClient, auth: dict[str, str]
) -> None:
    assert ai_app_client.post(f"{BRIEF}/thread", headers=auth).status_code == 404


def test_regenerating_drops_the_old_thread(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """Le fil porte le message d'avant ; la nouvelle lecture en dit un autre.

    Les rattacher ferait répondre à un texte que l'écran n'affiche plus. L'ancien fil
    survit dans les discussions avec son propre contenu, ce qui est la lecture honnête.
    """
    openrouter.say(answer("Première."), answer("Seconde."))
    ai_app_client.post(BRIEF, headers=auth)
    first = ai_app_client.post(f"{BRIEF}/thread", headers=auth).json()["thread_id"]

    ai_app_client.post(BRIEF, headers=auth)

    assert ai_app_client.get(BRIEF, headers=auth).json()["thread_id"] is None
    second = ai_app_client.post(f"{BRIEF}/thread", headers=auth).json()["thread_id"]
    assert second != first


# ── L'ordonnanceur ────────────────────────────────────


def at(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(TODAY, time(hour, minute))


@pytest.mark.anyio
async def test_scheduler_waits_for_the_floor(
    store: FileStore, ai_service: Any, openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """Cinq heures du matin, ce n'est pas encore la lecture du jour."""
    openrouter.say(answer())
    scheduler = BriefScheduler(store, ai_service, now=lambda: at(5, 59))

    assert await scheduler.tick() is False
    assert BRIEF_FILE not in dav.files


@pytest.mark.anyio
async def test_scheduler_writes_once_past_the_floor(
    store: FileStore, ai_service: Any, openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    openrouter.say(answer())
    scheduler = BriefScheduler(store, ai_service, now=lambda: at(6, 30))

    assert await scheduler.tick() is True
    assert LECTURE in _text(dav, BRIEF_FILE)


@pytest.mark.anyio
async def test_scheduler_does_not_write_twice_in_a_day(
    store: FileStore, ai_service: Any, openrouter: FakeOpenRouter
) -> None:
    """Une passe par heure, une lecture **par créneau**. Sinon la carte changerait de
    texte toutes les heures sous les yeux de quelqu'un qui n'a rien demandé."""
    openrouter.say(answer())
    scheduler = BriefScheduler(store, ai_service, now=lambda: at(7))

    assert await scheduler.tick() is True
    assert await scheduler.tick() is False
    # Le créneau est **nommé** : sans lui, la vue rendrait celui de l'heure réelle
    # d'exécution du test, qui n'est pas celle qu'on a injectée dans l'ordonnanceur.
    assert (await BriefService(store).view(today=TODAY, slot="matin")).message == LECTURE


@pytest.mark.anyio
async def test_scheduler_leaves_a_manual_reading_alone(
    store: FileStore, ai_service: Any, openrouter: FakeOpenRouter
) -> None:
    """Le bouton de repli et l'ordonnanceur écrivent la même ligne par le même chemin :
    celui qui passe en second n'a rien à faire."""
    openrouter.say(answer("Écrite au doigt."))
    service = BriefService(store)
    await service.generate(ai_service, adherence=_no_adherence(), today=TODAY, slot="matin")

    scheduler = BriefScheduler(store, ai_service, now=lambda: at(9))
    assert await scheduler.tick() is False
    assert (await service.view(today=TODAY, slot="matin")).message == "Écrite au doigt."


def _no_adherence() -> Any:
    """Un écart plan / réalisé vide, tel que `PLAN-06` le rend sans planning."""
    from app.domains.planning.schemas import AdherenceView

    return AdherenceView(weeks=[], rate=None, planned=0, honoured=0)


# ── Trois moments, trois lectures ─────────────────────


def test_the_current_slot_is_the_last_one_whose_hour_has_passed() -> None:
    """L'écran ne le calcule pas : il n'a ni l'horloge ni le fuseau du serveur."""
    assert current_slot(at(5, 59)) == "matin"
    assert current_slot(at(6)) == "matin"
    assert current_slot(at(12, 59)) == "matin"
    assert current_slot(at(13)) == "midi"
    assert current_slot(at(18, 59)) == "midi"
    assert current_slot(at(19)) == "soir"
    assert current_slot(at(23, 30)) == "soir"


def test_before_six_it_is_this_morning_and_not_yesterday_evening() -> None:
    """Rendre la lecture du soir de la veille serait montrer un texte qui commente une
    autre journée sur un écran qui affiche celle d'aujourd'hui."""
    assert current_slot(at(3)) == "matin"


def test_each_slot_asks_a_different_thing() -> None:
    """Le même paragraphe servi trois fois par jour serait lu une fois puis ignoré."""
    faits = ["Protéines : 86 g sur 150"]

    matin = compose.build_prompt(day=TODAY, context=faits, slot="matin")
    midi = compose.build_prompt(day=TODAY, context=faits, slot="midi")
    soir = compose.build_prompt(day=TODAY, context=faits, slot="soir")

    assert "hier" in matin.lower()
    # Midi n'a pas le droit de faire un bilan : la journée peut encore changer, et un
    # bilan de mi-journée se lit comme un jugement.
    assert "aucun bilan" in midi.lower()
    assert "rattrape encore ce soir" in soir
    assert len({matin, midi, soir}) == 3


def test_an_unknown_slot_falls_back_where_the_file_does() -> None:
    """Une cellule abîmée et un argument fautif ne doivent pas donner deux lectures
    différentes du même mot."""
    assert compose.build_prompt(day=TODAY, context=[], slot="brunch") == compose.build_prompt(
        day=TODAY, context=[], slot="matin"
    )


@pytest.mark.anyio
async def test_a_reading_written_before_this_lot_counts_as_the_morning(
    store: FileStore, dav: FakeWebDav
) -> None:
    """Les lignes sans créneau sont les lectures de six heures — c'était le seul. Les lire
    comme `matin` est exact, pas un repli de commodité (`STO-04`)."""
    dav.seed(
        "Metric/insights/brief.csv",
        f"day,slot,created,message,basis,thread_id,source\n{TODAY.isoformat()},,,Ancienne.,,,ai\n",
    )

    assert (await BriefService(store).view(today=TODAY, slot="matin")).message == "Ancienne."


@pytest.mark.anyio
async def test_the_scheduler_writes_one_slot_per_pass(
    store: FileStore, ai_service: Any, openrouter: FakeOpenRouter
) -> None:
    """Ouvrir l'application à vingt heures après une journée sans passe ne doit pas
    déclencher trois appels de modèle d'affilée."""
    openrouter.say(answer("Du matin."))
    scheduler = BriefScheduler(store, ai_service, now=lambda: at(20))

    assert await scheduler.tick() is True

    service = BriefService(store)
    assert (await service.view(today=TODAY, slot="matin")).state == "ready"
    assert (await service.view(today=TODAY, slot="midi")).state == "absent"
    assert (await service.view(today=TODAY, slot="soir")).state == "absent"


@pytest.mark.anyio
async def test_three_slots_live_side_by_side_in_the_file(
    store: FileStore, ai_service: Any, openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    """`day` **et** `slot` forment la clé : écrire midi ne remplace pas le matin."""
    service = BriefService(store)
    for slot, texte in (("matin", "Du matin."), ("midi", "De midi."), ("soir", "Du soir.")):
        openrouter.say(answer(texte))
        await service.generate(ai_service, adherence=_no_adherence(), today=TODAY, slot=slot)

    lignes = _rows(dav, "Metric/insights/brief.csv")
    assert lignes[0][:2] == ["day", "slot"]
    assert len(lignes) == 4

    assert (await service.view(today=TODAY, slot="matin")).message == "Du matin."
    assert (await service.view(today=TODAY, slot="soir")).message == "Du soir."


@pytest.mark.anyio
async def test_regenerating_a_slot_replaces_only_its_own_line(
    store: FileStore, ai_service: Any, openrouter: FakeOpenRouter, dav: FakeWebDav
) -> None:
    service = BriefService(store)
    openrouter.say(answer("Du matin."))
    await service.generate(ai_service, adherence=_no_adherence(), today=TODAY, slot="matin")
    openrouter.say(answer("De midi."))
    await service.generate(ai_service, adherence=_no_adherence(), today=TODAY, slot="midi")

    openrouter.say(answer("Midi, corrigé."))
    await service.generate(ai_service, adherence=_no_adherence(), today=TODAY, slot="midi")

    assert len(_rows(dav, "Metric/insights/brief.csv")) == 3
    assert (await service.view(today=TODAY, slot="matin")).message == "Du matin."
    assert (await service.view(today=TODAY, slot="midi")).message == "Midi, corrigé."
