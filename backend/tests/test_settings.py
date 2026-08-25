"""Réglages (`L08-01`, `L08-02`).

Deux exigences se croisent ici. Les valeurs de repli doivent être **identiques des deux
côtés** — c'est pourquoi le serveur les sert au lieu d'espérer que le client les recopie
juste. Et un fichier de configuration modifiable dans un tableur doit rester inoffensif :
une valeur abîmée à la main ne casse aucun écran.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.domains.app_settings.service import DEFAULTS
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

SETTINGS = "/api/settings"
FILE = "Metric/settings/settings.csv"


@pytest.fixture
def app_client(client: TestClient, store: FileStore) -> TestClient:
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


def read(client: TestClient, auth: dict[str, str]) -> Any:
    response = client.get(SETTINGS, headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def patch(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    """Modifie, en renvoyant le jeton lu — c'est le geste exact du client."""
    token = read(client, auth)["token"]
    return client.patch(SETTINGS, json=fields, headers={**auth, "If-Match": token})


# ── Lecture et valeurs de repli (`L08-01`) ────────────


def test_the_defaults_apply_before_any_setting(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """L'application doit être utilisable immédiatement, avant tout réglage."""
    values = read(app_client, auth)["values"]

    assert values["target_weight_kg"] == 70
    assert values["target_protein_g"] == 150
    assert values["max_added_sugar_g"] == 30
    assert values["target_hydration_ml"] == 2000
    assert values["hydration_presets_ml"] == [250, 500, 750]
    assert values["heatmap_metric"] == "activity"
    # Vide, et volontairement : le pont vers Cadence Tabata est en sommeil tant que son
    # adresse n'est pas renseignée (**D1**). Un domaine deviné serait une valeur inventée.
    assert values["cadence_base_url"] == ""


def test_the_server_serves_the_defaults_rather_than_trusting_the_client(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """La garantie qui remplace la discipline.

    Le backlog exige que backend et frontend s'accordent sur ce que vaut un objectif non
    renseigné. Le faire tenir par la même constante recopiée dans deux langages durerait
    jusqu'au premier oubli ; le serveur l'envoie, et il n'y a plus qu'une source.
    """
    body = read(app_client, auth)

    assert body["defaults"]["target_weight_kg"] == 70
    assert body["defaults"] == body["values"], "sans fichier, l'effectif est le défaut"


def test_the_view_says_which_settings_were_actually_chosen(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Un repli ne doit pas passer pour un choix : l'écran peut le dire."""
    dav.seed(FILE, "key,value\ntarget_weight_kg,68\n")

    body = read(app_client, auth)

    assert body["stored"] == ["target_weight_kg"]
    assert body["values"]["target_weight_kg"] == 68
    assert body["values"]["target_protein_g"] == 150


def test_the_typed_defaults_are_derived_from_the_textual_ones(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Deux listes de défauts à tenir en phase finiraient par diverger : la forme typée
    est calculée depuis `DEFAULTS`, jamais recopiée."""
    defaults = read(app_client, auth)["defaults"]

    assert str(int(defaults["target_weight_kg"])) == DEFAULTS["target_weight_kg"]
    assert (
        ",".join(str(value) for value in defaults["hydration_presets_ml"])
        == (DEFAULTS["hydration_presets_ml"])
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("abc", 70.0),  # illisible → défaut
        ('"72,5"', 72.5),  # virgule française, protégée comme le ferait un tableur
        ("", 70.0),  # cellule vidée à la main
    ],
)
def test_a_setting_mangled_by_hand_never_breaks_a_screen(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav, raw: str, expected: float
) -> None:
    """Le fichier est éditable dans un tableur : une valeur abîmée y est une possibilité
    normale, pas un incident. C'est un confort d'affichage, pas une donnée de suivi."""
    dav.seed(FILE, f"key,value\ntarget_weight_kg,{raw}\n")

    assert read(app_client, auth)["values"]["target_weight_kg"] == expected


def test_a_bogus_preset_list_keeps_the_readable_values(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Une virgule en trop ne doit pas faire disparaître les raccourcis corrects."""
    dav.seed(FILE, 'key,value\nhydration_presets_ml,"200,,abc,800"\n')

    assert read(app_client, auth)["values"]["hydration_presets_ml"] == [200, 800]


@pytest.mark.parametrize(
    "raw",
    [
        "cadence.exemple.fr",  # sans protocole : un href relatif, pas une adresse
        "javascript:alert(1)",  # protocole qu'on ne rend jamais dans un href
        "https://cadence.exemple.fr/?utm=x",  # une query string qui casserait le `?w=`
        "   ",  # cellule vidée à la main
    ],
)
def test_an_unusable_base_url_gives_no_link_rather_than_a_broken_one(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav, raw: str
) -> None:
    """Le repli d'une adresse abîmée est **rien**, et pas le texte tel quel.

    C'est la différence entre un écran qui dit « adresse non renseignée » — un état qu'il
    sait afficher — et un bouton « Ouvrir » qui mène à une page d'erreur. Le refus à la
    saisie ne suffit pas : le fichier s'ouvre dans un tableur, et une cellule collée de
    travers y est une possibilité normale.
    """
    dav.seed(FILE, f"key,value\ncadence_base_url,{raw}\n")

    assert read(app_client, auth)["values"]["cadence_base_url"] == ""


def test_a_usable_base_url_is_served_as_written(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """La barre finale est conservée : c'est l'adresse de l'utilisateur, pas la nôtre."""
    dav.seed(FILE, "key,value\ncadence_base_url,https://cadence.exemple.fr/\n")

    assert read(app_client, auth)["values"]["cadence_base_url"] == "https://cadence.exemple.fr/"


# ── Modification (`L08-02`) ───────────────────────────


def test_a_setting_can_be_changed(app_client: TestClient, auth: dict[str, str]) -> None:
    response = patch(app_client, auth, target_weight_kg=68.5)

    assert response.status_code == 200, response.text
    assert response.json()["values"]["target_weight_kg"] == 68.5
    assert read(app_client, auth)["values"]["target_weight_kg"] == 68.5


def test_the_file_stays_readable_in_a_spreadsheet(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`STO-02` : un objectif de 70 kg s'écrit « 70 », pas « 70.0 ». Un zéro décimal
    inutile est du bruit dans une colonne qu'on relira à l'œil."""
    patch(app_client, auth, target_weight_kg=70, target_hydration_ml=2500)

    content = dav.content_of(FILE)

    assert content.startswith("key,value\n")
    assert "target_weight_kg,70\n" in content
    assert "target_hydration_ml,2500\n" in content


def test_a_list_setting_survives_its_own_writer(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """La valeur contient des virgules dans un fichier qui les utilise comme séparateur :
    ce que l'application écrit, elle doit savoir le relire."""
    patch(app_client, auth, hydration_presets_ml=[200, 400, 800])

    assert read(app_client, auth)["values"]["hydration_presets_ml"] == [200, 400, 800]


def test_an_omitted_field_keeps_its_value(app_client: TestClient, auth: dict[str, str]) -> None:
    """Modification **partielle** : l'écran n'écrit que ce qu'il a changé, et un champ
    absent n'est pas remis à son défaut."""
    patch(app_client, auth, target_weight_kg=68)
    patch(app_client, auth, target_protein_g=180)

    values = read(app_client, auth)["values"]

    assert values["target_weight_kg"] == 68
    assert values["target_protein_g"] == 180


def test_an_unknown_key_is_preserved(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le fichier peut porter des réglages posés à la main ou par un lot ultérieur — les
    créneaux de rappel de `NOT-03`. Changer le poids cible n'a aucune raison de les
    effacer."""
    dav.seed(FILE, "key,value\nreminders_meal,12:30\n")

    patch(app_client, auth, target_weight_kg=68)

    assert "reminders_meal,12:30" in dav.content_of(FILE)


def test_the_change_reaches_the_domain_that_consumes_it(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """La vérification qui compte : un réglage n'a d'intérêt que s'il agit."""
    patch(app_client, auth, target_hydration_ml=3000, hydration_presets_ml=[300, 600])

    hydration = app_client.get("/api/hydration", headers=auth).json()

    assert hydration["stats"]["target_ml"] == 3000
    assert hydration["presets_ml"] == [300, 600]


# ── Garde anti-conflit (`STO-05`) ─────────────────────


def test_a_change_without_the_token_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Un `If-Match` absent est un conflit, jamais une permission : sinon la garde se
    contournerait en omettant l'en-tête."""
    response = app_client.patch(SETTINGS, json={"target_weight_kg": 60}, headers=auth)

    assert response.status_code == 409
    assert read(app_client, auth)["values"]["target_weight_kg"] == 70


def test_a_stale_token_is_refused(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le jeton porte sur le **fichier entier** : un jeu de réglages s'édite en bloc, et
    deux appareils qui l'ouvrent en même temps ne doivent pas s'écraser en silence."""
    stale = read(app_client, auth)["token"]
    dav.seed(FILE, "key,value\ntarget_weight_kg,65\n")

    response = app_client.patch(
        SETTINGS, json={"target_weight_kg": 60}, headers={**auth, "If-Match": stale}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert read(app_client, auth)["values"]["target_weight_kg"] == 65, "rien n'a été écrit"


def test_the_token_changes_when_the_file_changes(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    before = read(app_client, auth)["token"]
    patch(app_client, auth, target_weight_kg=68)

    assert read(app_client, auth)["token"] != before


# ── Bornes de vraisemblance (`API-06`) ────────────────


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_weight_kg", 0),
        ("target_weight_kg", 501),
        ("target_protein_g", -1),
        ("max_added_sugar_g", 1001),
        ("target_hydration_ml", 100),  # un objectif quotidien n'est pas un verre
        ("target_hydration_ml", 20000),
        ("hydration_presets_ml", []),
        ("hydration_presets_ml", [100, 200, 300, 400, 500, 600, 700]),
        ("heatmap_metric", ""),
        # Les trois formes que `BaseUrl` refuse. La chaîne vide, elle, est légitime et
        # se vérifie plus bas — c'est l'effacement du réglage.
        ("cadence_base_url", "cadence.exemple.fr"),
        ("cadence_base_url", "javascript:alert(1)"),
        ("cadence_base_url", "https://cadence.exemple.fr/?w=deja"),
    ],
)
def test_an_aberrant_setting_is_refused(
    app_client: TestClient, auth: dict[str, str], field: str, value: Any
) -> None:
    response = patch(app_client, auth, **{field: value})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_the_base_url_can_be_set_then_cleared(app_client: TestClient, auth: dict[str, str]) -> None:
    """**Le seul réglage de cet écran qui doit pouvoir revenir à vide.**

    Les autres retombent sur un défaut : ne pas régler son poids cible donne 70 kg, ce qui
    est un état utilisable. Une adresse absente n'a aucun repli — et c'est justement pour
    ça que l'effacement doit marcher. Le chemin passe par `update`, qui ignore les champs
    à `None` mais **écrit** une chaîne vide : la distinction porte tout le comportement.
    """
    assert patch(app_client, auth, cadence_base_url="https://cadence.exemple.fr").status_code == 200
    assert read(app_client, auth)["values"]["cadence_base_url"] == "https://cadence.exemple.fr"

    assert patch(app_client, auth, cadence_base_url="").status_code == 200
    assert read(app_client, auth)["values"]["cadence_base_url"] == ""
