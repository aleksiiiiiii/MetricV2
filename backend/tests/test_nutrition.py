"""Domaine Nutrition (`NUT-01` → `NUT-10`).

La sécurité du service des photos vit dans `test_photos.py` ; ici, le métier.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.dates import today_local, tz
from app.domains.nutrition.models import MealType
from app.domains.nutrition.service import suggested_type
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

NUTRITION = "/api/nutrition"
MEALS_FILE = "Metric/nutrition/meals.csv"
HEADER = "datetime,meal_type,comment,photo,protein_g,added_sugar_g,calories,source\n"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture
def app_client(client: TestClient, store: FileStore) -> TestClient:
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


def log_meal(client: TestClient, auth: dict[str, str], **fields: Any) -> Any:
    # Un formulaire multipart ne transporte que du texte : les nombres partent en chaînes,
    # exactement comme le ferait un navigateur.
    data = {
        "meal_type": "déjeuner",
        "comment": "poulet riz",
        **{name: str(value) for name, value in fields.items()},
    }
    response = client.post(NUTRITION, data=data, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


def moment(day: Any, hour: int = 12) -> str:
    return datetime.combine(day, datetime.min.time(), tzinfo=tz()).replace(hour=hour).isoformat()


# ── Saisie (`NUT-01`, `NUT-02`) ───────────────────────


def test_a_meal_needs_a_photo_or_a_description(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`NUT-01` : au moins l'un des deux. Un repas sans ni l'un ni l'autre ne relève rien."""
    response = app_client.post(NUTRITION, data={"meal_type": "déjeuner"}, headers=auth)

    assert response.status_code == 422
    assert "photo ou d'une description" in response.json()["message"]


def test_a_description_alone_is_enough(app_client: TestClient, auth: dict[str, str]) -> None:
    meal = log_meal(app_client, auth, comment="salade de lentilles")

    assert meal["comment"] == "salade de lentilles"
    assert meal["photo"] is None


def test_a_photo_alone_is_enough(app_client: TestClient, auth: dict[str, str]) -> None:
    response = app_client.post(
        NUTRITION,
        data={"meal_type": "dîner"},
        files={"photo": ("repas.jpg", JPEG, "image/jpeg")},
        headers=auth,
    )

    assert response.status_code == 201
    assert response.json()["photo"] is not None


def test_a_whitespace_only_description_does_not_count(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    response = app_client.post(
        NUTRITION, data={"meal_type": "déjeuner", "comment": "   "}, headers=auth
    )

    assert response.status_code == 422


def test_the_photo_path_is_stored_relative(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Le stocker relatif permet de déplacer le dossier de données sans réécrire le
    fichier."""
    meal = app_client.post(
        NUTRITION,
        data={"meal_type": "déjeuner"},
        files={"photo": ("repas.jpg", JPEG, "image/jpeg")},
        headers=auth,
    ).json()

    assert not meal["photo"].startswith("/")
    assert not meal["photo"].startswith("nutrition/")
    assert meal["photo"] in dav.content_of(MEALS_FILE)


# ── Type suggéré (`NUT-03`) ───────────────────────────


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (7, MealType.BREAKFAST),
        (10, MealType.BREAKFAST),
        (12, MealType.LUNCH),
        (14, MealType.LUNCH),
        (16, MealType.SNACK),
        (20, MealType.DINNER),
        (23, MealType.DINNER),
    ],
)
def test_the_meal_type_is_suggested_from_the_hour(hour: int, expected: MealType) -> None:
    """Une présélection doit tomber juste souvent, pas toujours — le type reste libre."""
    assert suggested_type(datetime(2026, 7, 26, hour, tzinfo=tz())) is expected


def test_the_suggestion_comes_from_the_server(app_client: TestClient, auth: dict[str, str]) -> None:
    """Le client ne redéfinit pas la règle : deux découpages horaires divergeraient."""
    body = app_client.get(NUTRITION, headers=auth).json()

    assert body["suggested_type"] in body["types"]
    assert len(body["types"]) == 4


def test_the_declared_type_wins_over_the_suggestion(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    assert log_meal(app_client, auth, meal_type="collation")["meal_type"] == "collation"


# ── Macros et totaux (`NUT-05`, `NUT-06`) ─────────────


def test_macros_are_optional_and_manual(app_client: TestClient, auth: dict[str, str]) -> None:
    """`NUT-05` : saisissables à la main, avec ou sans IA."""
    meal = log_meal(app_client, auth, protein_g=42.5, added_sugar_g=6, calories=680)

    assert meal["protein_g"] == 42.5
    assert meal["calories"] == 680
    assert meal["source"] == "manual"


def test_a_meal_without_macros_is_accepted(app_client: TestClient, auth: dict[str, str]) -> None:
    """L'IA est un confort : relever un repas sans chiffres doit rester possible."""
    meal = log_meal(app_client, auth)

    assert meal["protein_g"] is None
    assert meal["calories"] is None


def test_the_day_totals_compare_to_the_settings(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    dav.seed(
        "Metric/settings/settings.csv",
        "key,value\ntarget_protein_g,150\nmax_added_sugar_g,30\n",
    )
    log_meal(app_client, auth, protein_g=40, added_sugar_g=10, calories=600)
    log_meal(app_client, auth, protein_g=35, added_sugar_g=5, calories=520)

    totals = app_client.get(NUTRITION, headers=auth).json()["totals"]

    assert totals["protein_g"] == 75
    assert totals["protein_target_g"] == 150
    assert totals["protein_ratio"] == pytest.approx(0.5)
    assert totals["added_sugar_g"] == 15
    assert totals["over_sugar"] is False
    assert totals["calories"] == 1120


def test_exceeding_the_sugar_ceiling_is_flagged(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Un dépassement est un signal, pas une réussite : il se dit à part du ratio."""
    dav.seed("Metric/settings/settings.csv", "key,value\nmax_added_sugar_g,30\n")
    log_meal(app_client, auth, added_sugar_g=45)

    totals = app_client.get(NUTRITION, headers=auth).json()["totals"]

    assert totals["over_sugar"] is True
    assert totals["added_sugar_g"] == 45


def test_partial_calories_are_announced_as_partial(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Un total de calories sur deux repas renseignés sur cinq ne veut pas dire grand
    chose : le client doit pouvoir le nuancer."""
    log_meal(app_client, auth, calories=600)
    log_meal(app_client, auth)

    totals = app_client.get(NUTRITION, headers=auth).json()["totals"]

    assert totals["meals"] == 2
    assert totals["calories_known"] == 1


def test_the_protein_ratio_is_capped(app_client: TestClient, auth: dict[str, str]) -> None:
    log_meal(app_client, auth, protein_g=400)

    assert app_client.get(NUTRITION, headers=auth).json()["totals"]["protein_ratio"] == 1.0


@pytest.mark.parametrize(
    ("field", "value"), [("protein_g", 900), ("added_sugar_g", 2000), ("calories", 99999)]
)
def test_an_implausible_macro_is_refused(
    app_client: TestClient, auth: dict[str, str], field: str, value: float
) -> None:
    response = app_client.post(
        NUTRITION,
        data={"meal_type": "déjeuner", "comment": "x", field: str(value)},
        headers=auth,
    )

    assert response.status_code == 422


# ── Liste du jour (`NUT-07`) ──────────────────────────


def test_only_the_meals_of_the_day_are_listed(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    yesterday = moment(today_local() - timedelta(days=1))
    dav.seed(MEALS_FILE, HEADER + f"{yesterday},déjeuner,hier,,,,,manual\n")
    log_meal(app_client, auth, comment="aujourd'hui")

    meals = app_client.get(NUTRITION, headers=auth).json()["meals"]

    assert [meal["comment"] for meal in meals] == ["aujourd'hui"]


def test_the_list_can_be_bounded(app_client: TestClient, auth: dict[str, str]) -> None:
    """`NUT-07` : bornée ou complète selon la requête."""
    for index in range(4):
        log_meal(app_client, auth, comment=f"repas {index}")

    assert len(app_client.get(NUTRITION, headers=auth).json()["meals"]) == 4
    assert len(app_client.get(f"{NUTRITION}?limit=2", headers=auth).json()["meals"]) == 2


def test_the_list_reads_from_the_most_recent(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    today = today_local()
    dav.seed(
        MEALS_FILE,
        HEADER
        + f"{moment(today, 8)},petit-déjeuner,matin,,,,,manual\n"
        + f"{moment(today, 20)},dîner,soir,,,,,manual\n",
    )

    comments = [meal["comment"] for meal in app_client.get(NUTRITION, headers=auth).json()["meals"]]

    assert comments == ["soir", "matin"]


# ── Correction (`NUT-09`) ─────────────────────────────


def test_correcting_a_meal_preserves_its_photo_and_source(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """`NUT-09` : corriger une macro estimée par l'IA ne supprime pas la photo ni ne
    réécrit la provenance."""
    created = app_client.post(
        NUTRITION,
        data={"meal_type": "déjeuner", "comment": "poulet"},
        files={"photo": ("repas.jpg", JPEG, "image/jpeg")},
        headers=auth,
    ).json()

    corrected = app_client.patch(
        f"{NUTRITION}/{created['id']}",
        json={"meal_type": "dîner", "comment": "poulet riz", "protein_g": 45},
        headers={**auth, "If-Match": created["token"]},
    ).json()

    assert corrected["photo"] == created["photo"]
    assert corrected["source"] == created["source"]
    assert corrected["meal_type"] == "dîner"
    assert corrected["protein_g"] == 45


def test_correcting_without_the_token_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    created = log_meal(app_client, auth)

    response = app_client.patch(
        f"{NUTRITION}/{created['id']}", json={"meal_type": "dîner"}, headers=auth
    )

    assert response.status_code == 409


def test_deleting_a_meal_leaves_the_photo_on_storage(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Décision assumée : la photo est rangée par date et consultable hors de l'app.
    L'effacer d'un clic ferait perdre un souvenir qu'aucune annulation ne rendrait."""
    created = app_client.post(
        NUTRITION,
        data={"meal_type": "déjeuner"},
        files={"photo": ("repas.jpg", JPEG, "image/jpeg")},
        headers=auth,
    ).json()
    stored = f"Metric/nutrition/photos/{created['photo']}"

    app_client.delete(
        f"{NUTRITION}/{created['id']}", headers={**auth, "If-Match": created["token"]}
    )

    assert app_client.get(NUTRITION, headers=auth).json()["meals"] == []
    assert stored in dav.files


# ── Favoris (`NUT-10`) ────────────────────────────────


def test_a_favorite_is_replayed_in_one_action(app_client: TestClient, auth: dict[str, str]) -> None:
    """Couvre les repas identiques du quotidien, sans photo ni IA."""
    favorite = app_client.post(
        f"{NUTRITION}/favorites",
        json={"name": "Skyr + flocons", "protein_g": 32, "calories": 380},
        headers=auth,
    ).json()

    meal = app_client.post(
        f"{NUTRITION}/favorites/{favorite['favorite_id']}/replay", headers=auth
    ).json()

    assert meal["comment"] == "Skyr + flocons"
    assert meal["protein_g"] == 32
    assert meal["calories"] == 380
    assert meal["photo"] is None


def test_replaying_uses_the_suggested_type(app_client: TestClient, auth: dict[str, str]) -> None:
    favorite = app_client.post(f"{NUTRITION}/favorites", json={"name": "Skyr"}, headers=auth).json()

    meal = app_client.post(
        f"{NUTRITION}/favorites/{favorite['favorite_id']}/replay", headers=auth
    ).json()

    assert meal["meal_type"] in [kind.value for kind in MealType]


def test_replaying_an_unknown_favorite_is_refused(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    assert (
        app_client.post(f"{NUTRITION}/favorites/inexistant/replay", headers=auth).status_code == 404
    )


def test_a_favorite_can_be_removed(app_client: TestClient, auth: dict[str, str]) -> None:
    favorite = app_client.post(f"{NUTRITION}/favorites", json={"name": "Skyr"}, headers=auth).json()

    response = app_client.delete(
        f"{NUTRITION}/favorites/{favorite['id']}",
        headers={**auth, "If-Match": favorite["token"]},
    )

    assert response.status_code == 204
    assert app_client.get(NUTRITION, headers=auth).json()["favorites"] == []


# ── Chaîne complète ───────────────────────────────────


def test_an_empty_day_answers_without_failing(app_client: TestClient, auth: dict[str, str]) -> None:
    body = app_client.get(NUTRITION, headers=auth).json()

    assert body["meals"] == []
    assert body["totals"]["protein_g"] == 0
    assert body["totals"]["over_sugar"] is False


def test_the_file_stays_readable_in_a_spreadsheet(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    log_meal(app_client, auth, comment="poulet, riz", protein_g=42.5, calories=680)

    lines = dav.content_of(MEALS_FILE).splitlines()

    assert lines[0] == ("datetime,meal_type,comment,photo,protein_g,added_sugar_g,calories,source")
    # La virgule du commentaire est protégée par des guillemets.
    assert '"poulet, riz"' in lines[1]
    assert lines[1].endswith(",42.5,,680,manual")
