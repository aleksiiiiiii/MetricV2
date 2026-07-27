"""Service des photos de repas : la surface d'attaque du projet (`NUT-08`, `L07-12`).

C'est le seul endpoint dont le chemin vient de l'extérieur. Ces tests sont écrits du
point de vue de quelqu'un qui essaie d'en sortir.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.domains.nutrition.photos import PhotoError, build_path, detect_extension, storage_path
from app.storage.errors import StorageNotFoundError
from app.storage.files import FileStore
from app.storage.provider import StorageProvider
from tests.fake_webdav import FakeWebDav

PHOTOS = "/api/nutrition/photos"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 64


@pytest.fixture
def app_client(client: TestClient, store: FileStore) -> TestClient:
    provider = client.app.state.storage  # type: ignore[attr-defined]
    assert isinstance(provider, StorageProvider)
    provider.use(store)
    return client


# ── Ce qui sort du dossier doit rester dehors ─────────


@pytest.mark.parametrize(
    "attack",
    [
        "../../../etc/passwd",
        "../../body/weight.csv",
        "..%2F..%2Fbody%2Fweight.csv",
        "/etc/passwd",
        "2026/07/26/../../../secret.jpg",
        "2026/07/26/..%00.jpg",
        r"..\..\body\weight.csv",
        "....//....//etc/passwd",
    ],
)
def test_a_path_that_tries_to_escape_is_refused(
    app_client: TestClient, auth: dict[str, str], attack: str
) -> None:
    response = app_client.get(f"{PHOTOS}/{attack}", headers=auth)

    assert response.status_code == 404
    # Rien du contenu visé ne doit transparaître : la réponse est notre enveloppe
    # d'erreur, jamais un fichier. Certains de ces chemins sont d'ailleurs normalisés
    # avant même d'atteindre notre code — défense en profondeur, mais on vérifie le
    # résultat plutôt que le chemin emprunté.
    # Deux codes possibles et tous deux justes : `not_found` quand le routage a
    # normalisé le chemin avant nous, `storage_not_found` quand notre garde l'a refusé.
    # Ce qui compte est le statut et l'absence de fuite.
    assert response.json()["code"] in {"not_found", "storage_not_found"}
    assert "root:" not in response.text
    assert "weight_kg" not in response.text


@pytest.mark.parametrize(
    "attack",
    [
        "2026/07/26/20260726-120000-deadbeef.php",
        "2026/07/26/20260726-120000-deadbeef.csv",
        "2026/07/26/20260726-120000-deadbeef",
        "2026/7/26/20260726-120000-deadbeef.jpg",
        "2026/07/26/n-importe-quoi.jpg",
        "20260726-120000-deadbeef.jpg",
    ],
)
def test_a_path_that_is_not_our_shape_is_refused(
    app_client: TestClient, auth: dict[str, str], attack: str
) -> None:
    """La stratégie n'est pas de nettoyer ce qu'on reçoit mais de refuser tout ce qui ne
    correspond pas exactement à la forme que nous produisons."""
    assert app_client.get(f"{PHOTOS}/{attack}", headers=auth).status_code == 404


def test_the_photo_endpoint_needs_a_token(app_client: TestClient) -> None:
    """`AUTH-05` : les photos sont des données personnelles comme les autres."""
    response = app_client.get(f"{PHOTOS}/2026/07/26/20260726-120000-deadbeef.jpg")

    assert response.status_code == 401


def test_a_well_formed_path_resolves_under_the_photo_folder() -> None:
    resolved = storage_path("2026/07/26/20260726-120000-deadbeef.jpg")

    assert resolved == "nutrition/photos/2026/07/26/20260726-120000-deadbeef.jpg"


@pytest.mark.parametrize("attack", ["../x.jpg", "/2026/07/26/a.jpg", "2026/07/26/../../x.jpg", ""])
def test_the_resolver_refuses_before_touching_storage(attack: str) -> None:
    with pytest.raises(StorageNotFoundError):
        storage_path(attack)


# ── Le contenu décide, pas le nom ─────────────────────


@pytest.mark.parametrize(("data", "extension"), [(JPEG, "jpg"), (PNG, "png"), (WEBP, "webp")])
def test_the_extension_comes_from_the_content(data: bytes, extension: str) -> None:
    assert detect_extension(data) == extension


@pytest.mark.parametrize(
    "data",
    [
        b"<?php system($_GET['c']); ?>",
        b"GIF89a",  # format non accepté
        b"date,weight_kg\n2026-07-26,68.4\n",
        b"\x00" * 32,
    ],
)
def test_anything_that_is_not_an_image_is_refused(data: bytes) -> None:
    """Servir des octets arbitraires sous un type d'image offrirait une surface
    d'attaque au navigateur."""
    with pytest.raises(PhotoError):
        detect_extension(data)


def test_a_declared_content_type_is_never_believed(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Un client peut annoncer `image/jpeg` en envoyant du script."""
    response = app_client.post(
        "/api/nutrition",
        data={"meal_type": "déjeuner"},
        files={"photo": ("innocent.jpg", b"<?php echo 1; ?>", "image/jpeg")},
        headers=auth,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(PhotoError, match="vide"):
        build_path(b"", datetime.now(tz=ZoneInfo("Europe/Paris")))


def test_an_oversized_photo_is_refused() -> None:
    with pytest.raises(PhotoError, match="trop lourde"):
        build_path(JPEG + b"\x00" * (13 * 1024 * 1024), datetime.now(tz=ZoneInfo("Europe/Paris")))


# ── Rangement (`NUT-02`) ──────────────────────────────


def test_the_photo_is_filed_by_date() -> None:
    """Arborescence datée, consultable hors de l'app."""
    when = datetime(2026, 7, 26, 13, 5, 42, tzinfo=ZoneInfo("Europe/Paris"))

    path = build_path(JPEG, when)

    assert path.startswith("2026/07/26/20260726-130542-")
    assert path.endswith(".jpg")


def test_two_photos_in_the_same_second_do_not_collide() -> None:
    """Sans aléa, la seconde écraserait la première."""
    when = datetime(2026, 7, 26, 13, 5, 42, tzinfo=ZoneInfo("Europe/Paris"))

    assert build_path(JPEG, when) != build_path(JPEG, when)


# ── Service (`NUT-08`) ────────────────────────────────


def test_an_uploaded_photo_can_be_read_back(
    app_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    created = app_client.post(
        "/api/nutrition",
        data={"meal_type": "déjeuner", "comment": "poulet riz"},
        files={"photo": ("repas.jpg", JPEG, "image/jpeg")},
        headers=auth,
    ).json()

    response = app_client.get(f"{PHOTOS}/{created['photo']}", headers=auth)

    assert response.status_code == 200
    assert response.content == JPEG
    assert response.headers["content-type"] == "image/jpeg"
    assert "nutrition/photos/2026" in " ".join(dav.files)


def test_the_response_is_cacheable_and_not_sniffable(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    """Chemins uniques → réponses cachables durablement (`NUT-08`)."""
    created = app_client.post(
        "/api/nutrition",
        data={"meal_type": "déjeuner"},
        files={"photo": ("repas.png", PNG, "image/png")},
        headers=auth,
    ).json()

    headers = app_client.get(f"{PHOTOS}/{created['photo']}", headers=auth).headers

    assert "immutable" in headers["cache-control"]
    assert headers["x-content-type-options"] == "nosniff"


def test_a_well_formed_path_that_does_not_exist_is_a_plain_404(
    app_client: TestClient, auth: dict[str, str]
) -> None:
    response = app_client.get(f"{PHOTOS}/2026/07/26/20260726-120000-deadbeef.jpg", headers=auth)

    assert response.status_code == 404
