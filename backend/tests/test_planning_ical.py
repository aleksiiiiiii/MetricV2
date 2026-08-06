"""Export iCal du planning (`PLAN-05`, RFC 5545).

Deux moitiés, et la première est la raison d'être du module : `ical.py` ne connaît ni
dépôt ni HTTP, donc sa justesse se vérifie sur des valeurs fixes, sans rien monter. Les
règles du format cassent toutes en silence — un flux mal plié n'échoue pas, il affiche un
calendrier vide.

La seconde moitié vérifie la garde de l'URL publique. C'est la seule route du projet qui
sert des données personnelles sans jeton, et elle n'a droit à aucune approximation.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.config import ICAL_SECRET_MIN_LENGTH, Settings
from app.core.dates import today_local
from app.domains.planning import ical
from app.domains.planning.schemas import PlannedSession
from app.main import create_app
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.conftest import TEST_PASSWORD, TEST_USERNAME

PARIS = ZoneInfo("Europe/Paris")
STAMP = datetime(2026, 8, 4, 9, 30, tzinfo=PARIS)

#: Clé de test, au-dessus du plancher exigé par la configuration.
SECRET = "x" * ICAL_SECRET_MIN_LENGTH
PLAN_FILE = "Metric/planning/plan.csv"
PLAN_HEADER = "id,date,time,kind,title,duration_min,note,source\n"


def session(**fields: Any) -> PlannedSession:
    base: dict[str, Any] = {
        "id": 0,
        "token": "jeton",
        "session_id": "abc123",
        "date": date(2026, 8, 5),
        "time": "18:30",
        "kind": "muscu",
        "title": "Haut du corps",
        "duration_min": 60,
        "note": None,
        "source": "manual",
    }
    return PlannedSession(**{**base, **fields})


def lines(*sessions: PlannedSession) -> list[str]:
    return ical.render(sessions, stamp=STAMP, tz=PARIS).split("\r\n")


# ── Le format (`PLAN-05`, RFC 5545) ───────────────────


def test_the_calendar_carries_its_mandatory_envelope() -> None:
    body = lines(session())

    assert body[0] == "BEGIN:VCALENDAR"
    assert "VERSION:2.0" in body
    assert any(line.startswith("PRODID:") for line in body)
    assert "CALSCALE:GREGORIAN" in body
    assert body[-2] == "END:VCALENDAR"


def test_every_line_ends_with_crlf() -> None:
    """§3.1. Un flux en LF est accepté par certains clients et rejeté par d'autres, et le
    symptôme est un calendrier vide sans message."""
    raw = ical.render([session()], stamp=STAMP, tz=PARIS)

    assert raw.endswith("\r\n")
    assert "\n" not in raw.replace("\r\n", "")


def test_a_timed_session_leaves_in_utc() -> None:
    """18 h 30 à Paris en août, c'est 16 h 30 UTC — l'heure d'été comprise."""
    body = lines(session(time="18:30", duration_min=60))

    assert "DTSTART:20260805T163000Z" in body
    assert "DTEND:20260805T173000Z" in body


def test_a_winter_session_uses_the_right_offset() -> None:
    """La même heure locale en janvier donne un décalage différent.

    C'est ce que la conversion par évènement achète, et ce qu'une heure recopiée telle
    quelle sans `VTIMEZONE` aurait faux une moitié de l'année.
    """
    body = lines(session(date=date(2026, 1, 14), time="18:30"))

    assert "DTSTART:20260114T173000Z" in body


def test_a_session_without_a_time_becomes_an_all_day_event() -> None:
    """Décision 3 du lot, vue depuis le format : une cellule `time` vide est un cas
    **normal**, et elle doit produire un évènement valide, pas une erreur."""
    body = lines(session(time=None))

    assert "DTSTART;VALUE=DATE:20260805" in body
    # `DTEND` est exclusif (§3.6.1) : sans le lendemain, la séance occuperait deux jours.
    assert "DTEND;VALUE=DATE:20260806" in body


def test_a_session_without_a_duration_only_says_when_it_starts() -> None:
    """Cas que seule une édition à la main du CSV peut produire.

    Inventer une heure de fin serait inventer une donnée ; la RFC autorise un `DTSTART`
    seul (§3.6.1).
    """
    body = lines(session(duration_min=0))

    assert "DTSTART:20260805T163000Z" in body
    assert not any(line.startswith("DTEND") for line in body)


def test_a_broken_time_cell_costs_the_time_not_the_feed() -> None:
    """Règle de la famille *planning*, appliquée au format de sortie."""
    body = lines(session(time="dix-huit heures"))

    assert "DTSTART;VALUE=DATE:20260805" in body


def test_the_uid_is_the_stable_identifier() -> None:
    """Un calendrier abonné reconnaît un évènement à son `UID`.

    Le voir changer lui ferait recréer toutes les séances à chaque suppression de ligne —
    c'est pourquoi ce n'est jamais la position dans le fichier.
    """
    body = lines(session(session_id="abc123", id=7))

    assert "UID:abc123@metric" in body


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("séries 3, 4, 5", "séries 3\\, 4\\, 5"),
        ("charge; repos", "charge\\; repos"),
        ("deux\nlignes", "deux\\nlignes"),
        ("chemin\\ici", "chemin\\\\ici"),
    ],
)
def test_special_characters_are_escaped(raw: str, expected: str) -> None:
    """§3.3.11. Sans cela, « séries 3, 4, 5 » produirait trois paramètres."""
    body = lines(session(note=raw))

    assert f"DESCRIPTION:{expected}" in body


def test_a_long_line_is_folded_at_seventy_five_octets() -> None:
    """§3.1, et le compte est en **octets**.

    « Épaules » pèse huit octets pour sept caractères : un compte en caractères laisserait
    passer des lignes trop longues dès le premier accent.
    """
    body = lines(session(title="Épaules et dos " * 12))

    assert all(len(line.encode("utf-8")) <= 75 for line in body), [
        line for line in body if len(line.encode("utf-8")) > 75
    ]
    assert any(line.startswith(" ") for line in body), "aucune ligne de continuation"


def test_folding_never_splits_a_character_in_two() -> None:
    """Un découpage en octets produirait des séquences UTF-8 invalides.

    Le pliage se mesure en octets et se **coupe** en caractères ; recoller le tout doit
    rendre exactement la ligne de départ.
    """
    long_line = "DESCRIPTION:" + "éàü" * 60
    folded = ical.fold(long_line)

    assert "".join(piece.removeprefix(" ") for piece in folded) == long_line
    for piece in folded:
        piece.encode("utf-8").decode("utf-8")  # lève si un caractère a été coupé


def test_the_summary_says_what_kind_of_session_it_is() -> None:
    """Un abonnement mélange le planning au reste de l'agenda : « Muscu · Haut du corps »
    se lit dans une liste, « Haut du corps » beaucoup moins."""
    body = lines(session(kind="muscu", title="Haut du corps"))

    assert "SUMMARY:Muscu · Haut du corps" in body


def test_a_title_that_already_says_it_is_not_repeated() -> None:
    assert "SUMMARY:Course longue" in lines(session(kind="course", title="Course longue"))


def test_an_empty_calendar_is_still_a_valid_calendar() -> None:
    """Aucune séance prévue : le flux existe et reste analysable.

    Un abonnement qui recevrait une réponse vide se déclarerait en erreur chez le client,
    et l'utilisateur croirait l'adresse fausse.
    """
    body = lines()

    assert body[0] == "BEGIN:VCALENDAR"
    assert body[-2] == "END:VCALENDAR"
    assert "BEGIN:VEVENT" not in body


# ── La garde de l'URL publique (`PLAN-05`, `AUTH-05`) ──


@pytest.fixture
def feed_settings(password_hash: str) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        auth_username=TEST_USERNAME,
        auth_password_hash=password_hash,
        jwt_secret="secret-de-test-suffisamment-long-pour-etre-credible",
        ical_secret=SECRET,
    )


def build(settings: Settings, store: FileStore) -> TestClient:
    client = TestClient(create_app(settings))
    client.__enter__()
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


@pytest.fixture
def feed_client(feed_settings: Settings, store: FileStore) -> Any:
    client = build(feed_settings, store)
    yield client
    client.__exit__(None, None, None)


def token_of(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_the_feed_is_served_without_a_token(feed_client: TestClient, dav: Any) -> None:
    """C'est tout l'objet de `PLAN-05` : un abonnement ne peut pas porter d'en-tête
    `Authorization`, il va chercher son fichier tout seul."""
    day = today_local() + timedelta(days=2)
    dav.seed(PLAN_FILE, PLAN_HEADER + f"abc123,{day.isoformat()},18:30,muscu,Haut,60,,manual\n")

    response = feed_client.get(f"/api/calendar/{SECRET}.ics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in response.text
    assert "UID:abc123@metric" in response.text


@pytest.mark.parametrize("secret", ["", "x" * (ICAL_SECRET_MIN_LENGTH - 1), "y" * 40, "X" * 40])
def test_a_wrong_key_is_refused(feed_client: TestClient, secret: str) -> None:
    """Clé fausse, trop courte, ou de la bonne longueur mais fausse : même refus."""
    assert feed_client.get(f"/api/calendar/{secret}.ics").status_code == 404


def test_without_a_configured_key_nothing_is_published(
    settings: Settings, store: FileStore, dav: Any
) -> None:
    """Une clé absente ne publie **rien**, au lieu de publier tout.

    Sans ce test, une configuration vide servirait le planning à quiconque demande
    `/api/calendar/.ics` — la comparaison `"" == ""` étant vraie.
    """
    dav.seed(PLAN_FILE, PLAN_HEADER)
    client = build(settings, store)
    try:
        assert client.get("/api/calendar/.ics").status_code == 404
        assert client.get(f"/api/calendar/{SECRET}.ics").status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_a_key_shorter_than_the_floor_is_treated_as_absent(
    password_hash: str, store: FileStore
) -> None:
    """Accepter `ICAL_SECRET=metric` publierait un an de planning derrière un mot de six
    lettres, et l'utilisateur croirait avoir posé une protection."""
    weak = Settings(
        _env_file=None,
        app_env="test",
        auth_username=TEST_USERNAME,
        auth_password_hash=password_hash,
        jwt_secret="secret-de-test-suffisamment-long-pour-etre-credible",
        ical_secret="metric",
    )
    assert weak.ical_enabled is False

    client = build(weak, store)
    try:
        assert client.get("/api/calendar/metric.ics").status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_the_feed_stays_out_of_the_published_contract(feed_client: TestClient) -> None:
    """La garde de `AUTH-05` lit l'OpenAPI et y exige un jeton sur toute opération de
    données. L'y déclarer demanderait une exception permanente dans le mécanisme même qui
    les interdit."""
    paths = feed_client.get("/api/openapi.json").json()["paths"]

    assert not any(path.startswith("/api/calendar") for path in paths)


# ── Téléchargement ponctuel, sous jeton ───────────────


def test_the_download_requires_a_token(feed_client: TestClient) -> None:
    assert feed_client.get("/api/planning/export.ics").status_code == 401


def test_the_download_works_without_any_configured_key(
    settings: Settings, store: FileStore, dav: Any
) -> None:
    """Le téléchargement passe par le jeton de session : il n'a aucune raison de dépendre
    de la clé d'abonnement, et reste utile quand celle-ci manque."""
    dav.seed(PLAN_FILE, PLAN_HEADER)
    client = build(settings, store)
    try:
        response = client.get("/api/planning/export.ics", headers=token_of(client))

        assert response.status_code == 200
        assert "attachment" in response.headers["content-disposition"]
        assert "BEGIN:VCALENDAR" in response.text
    finally:
        client.__exit__(None, None, None)


def test_the_subscription_endpoint_says_what_is_missing(
    settings: Settings, store: FileStore
) -> None:
    """Une clé absente est un **état**, pas une panne : `200` et une phrase actionnable."""
    client = build(settings, store)
    try:
        body = client.get("/api/planning/subscription", headers=token_of(client)).json()

        assert body["configured"] is False
        assert body["url"] is None
        assert "ICAL_SECRET" in body["message"]
    finally:
        client.__exit__(None, None, None)


def test_the_subscription_endpoint_gives_the_full_address(feed_client: TestClient) -> None:
    body = feed_client.get("/api/planning/subscription", headers=token_of(feed_client)).json()

    assert body["configured"] is True
    assert body["url"].endswith(f"/api/calendar/{SECRET}.ics")


def test_the_feed_leaves_out_the_distant_past(feed_client: TestClient, dav: Any) -> None:
    """Un abonnement n'a pas à porter trois ans de séances passées.

    La seule question qu'on pose au passé d'un planning est « qu'avais-je prévu le mois
    dernier ».
    """
    recent = today_local() - timedelta(days=10)
    ancient = today_local() - timedelta(days=200)
    dav.seed(
        PLAN_FILE,
        PLAN_HEADER
        + f"recent,{recent.isoformat()},18:30,muscu,Récente,60,,manual\n"
        + f"vieille,{ancient.isoformat()},18:30,muscu,Ancienne,60,,manual\n",
    )

    body = feed_client.get(f"/api/calendar/{SECRET}.ics").text

    assert "UID:recent@metric" in body
    assert "UID:vieille@metric" not in body
