"""Préparation des images avant envoi (`IA-06`)."""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from app.domains.ai.images import MAX_SIDE, ImageUnreadableError, prepare_data_url


def png(width: int, height: int, colour: str = "red") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def decoded(data_url: str) -> Image.Image:
    """Relit l'image telle qu'un modèle la recevrait."""
    assert data_url.startswith("data:image/jpeg;base64,")
    raw = base64.b64decode(data_url.removeprefix("data:image/jpeg;base64,"))
    return Image.open(io.BytesIO(raw))


def test_a_large_screenshot_is_reduced_to_the_long_side() -> None:
    """Une capture d'iPhone 14 : 1179 × 2556. Le côté long descend à 1024."""
    image = decoded(prepare_data_url(png(1179, 2556)))

    assert max(image.size) == MAX_SIDE
    # Les proportions sont conservées : une capture étirée serait illisible pour un modèle.
    assert image.size == (472, 1024)


def test_a_small_image_is_never_enlarged() -> None:
    """Interpoler ajouterait des pixels inventés à une image qu'on demande de lire."""
    image = decoded(prepare_data_url(png(320, 240)))

    assert image.size == (320, 240)


def test_the_result_is_jpeg_whatever_came_in() -> None:
    image = decoded(prepare_data_url(png(200, 200)))

    assert image.format == "JPEG"


def test_a_transparent_png_survives_the_conversion() -> None:
    """JPEG n'a pas de canal alpha : sans conversion explicite, l'enregistrement échoue."""
    buffer = io.BytesIO()
    Image.new("RGBA", (120, 120), (255, 0, 0, 0)).save(buffer, format="PNG")

    assert decoded(prepare_data_url(buffer.getvalue())).format == "JPEG"


def test_reduction_makes_the_payload_much_lighter() -> None:
    """C'est la raison d'être de `IA-06` : le coût et la latence d'un appel."""
    original = png(1600, 1600, "blue")
    prepared = prepare_data_url(original)

    assert len(prepared) < len(original)


def test_an_empty_file_is_refused_with_a_readable_message() -> None:
    with pytest.raises(ImageUnreadableError) as caught:
        prepare_data_url(b"")

    assert "vide" in str(caught.value)


def test_a_file_that_is_not_an_image_is_refused() -> None:
    """Le message nomme les formats acceptés : un refus doit dire quoi faire ensuite."""
    with pytest.raises(ImageUnreadableError) as caught:
        prepare_data_url(b"ceci n'est pas une image" * 10)

    assert "JPEG" in str(caught.value)


def test_a_truncated_image_is_refused_rather_than_half_sent() -> None:
    complete = png(400, 400)

    with pytest.raises(ImageUnreadableError):
        prepare_data_url(complete[: len(complete) // 3])


def test_an_oversized_upload_is_refused_before_decoding() -> None:
    """Refusé sur la taille du fichier, sans allouer la surface qu'il annonce."""
    with pytest.raises(ImageUnreadableError) as caught:
        prepare_data_url(b"\x00" * (13 * 1024 * 1024))

    assert "Mo" in str(caught.value)
