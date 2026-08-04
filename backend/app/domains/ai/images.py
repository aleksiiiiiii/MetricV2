"""Préparation des images envoyées à un modèle vision (`IA-06`).

Une capture d'iPhone fait 1179 × 2556 et deux à trois mégaoctets. Envoyée telle quelle,
elle coûte des jetons proportionnellement à sa surface, met plusieurs secondes à monter, et
certains modèles gratuits la refusent purement et simplement. Réduite à 1024 px de côté et
convertie en JPEG, elle reste parfaitement lisible pour un modèle — les chiffres d'un
écran Apple Fitness font des dizaines de pixels de haut — et pèse dix fois moins.

Trois choix méritent d'être nommés :

* **Le côté long à 1024 px**, jamais agrandi. Une capture déjà petite n'a rien à gagner à
  être interpolée : on ajouterait des pixels inventés à une image qu'on demande à un
  modèle de lire.
* **L'orientation EXIF est appliquée**, puis oubliée. Une photo prise en tenant le
  téléphone de travers porte sa rotation en métadonnée ; un modèle qui reçoit les pixels
  bruts lit l'assiette de côté.
* **JPEG et non PNG**, même pour une capture d'écran. Le PNG d'une capture est plus fidèle
  mais trois à cinq fois plus lourd, et la fidélité au pixel ne sert à rien ici.

**Ce module ne devine pas non plus.** Une image illisible — format non pris en charge,
fichier tronqué — lève une erreur explicite plutôt que de partir en JPEG vide.
"""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.exceptions import ValidationFailedError

#: Côté long après réduction. Au-delà, on paie des jetons sans gagner en lisibilité.
MAX_SIDE = 1024

#: Qualité JPEG. 82 est le seuil au-dessus duquel l'œil ne distingue plus rien sur une
#: photo de repas, et en dessous duquel les chiffres fins d'une capture commencent à baver.
JPEG_QUALITY = 82

#: Plafond de téléversement pour une image destinée à l'IA. Plus généreux que la limite
#: d'une photo de repas serait inutile : au-delà, c'est une image qui n'est pas une capture.
MAX_BYTES = 12 * 1024 * 1024

#: Formats que Pillow ouvre sans greffon. Le HEIC d'un iPhone n'en fait **pas** partie —
#: il demanderait `pillow-heif` et sa chaîne de compilation native. Le refuser avec une
#: phrase claire coûte moins qu'une dépendance binaire, et `IA-07` l'autorise : l'assistance
#: manque, la saisie manuelle reste entière.
READABLE = "JPEG, PNG ou WebP"


class ImageUnreadableError(ValidationFailedError):
    """Image que l'on ne sait pas ouvrir.

    Descend du catalogue d'erreurs : c'est un fichier qui ne convient pas, pas une panne.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


def prepare_data_url(data: bytes) -> str:
    """Réduit, convertit et encode une image en `data:` URL (`IA-06`)."""
    if not data:
        raise ImageUnreadableError("Le fichier est vide.")
    if len(data) > MAX_BYTES:
        raise ImageUnreadableError(
            f"Image trop lourde : {MAX_BYTES // (1024 * 1024)} Mo au maximum."
        )

    try:
        with Image.open(io.BytesIO(data)) as opened:
            # L'orientation est appliquée avant toute mesure : sur une photo pivotée,
            # largeur et hauteur sont échangées, et réduire d'abord tronquerait le mauvais
            # côté.
            upright = ImageOps.exif_transpose(opened) or opened
            image = upright.convert("RGB")
            # `thumbnail` ne fait que réduire : une image plus petite que la cible est
            # laissée telle quelle, ce qui est exactement la règle voulue.
            image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    except UnidentifiedImageError as exc:
        raise ImageUnreadableError(
            f"Ce fichier n'est pas une image que l'on sait lire ({READABLE}). "
            "Une capture d'écran convient toujours."
        ) from exc
    except (OSError, ValueError) as exc:
        # Fichier tronqué, ou image dont la taille annoncée dépasse ce que Pillow accepte
        # d'allouer. Dans les deux cas l'utilisateur peut refaire sa capture.
        raise ImageUnreadableError("Cette image est illisible ou incomplète.") from exc

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"
