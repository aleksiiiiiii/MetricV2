"""Photos de repas : rangement et service sécurisé (`NUT-02`, `NUT-08`, `STO-07`).

C'est le seul endroit du projet où un chemin vient de l'extérieur. Un chemin construit
à partir d'une entrée utilisateur est le chemin le plus court vers une fuite de fichiers,
alors la stratégie ici n'est **pas** de nettoyer ce qu'on reçoit mais de refuser tout ce
qui ne correspond pas exactement à la forme attendue.

Trois gardes, dans cet ordre :

1. **Forme imposée** — `AAAA/MM/JJ/horodatage-aléa.ext`, vérifiée par expression
   régulière. Un `..`, un chemin absolu, un octet nul ou un caractère inattendu ne
   ressemblent pas à cette forme et sont rejetés avant toute manipulation.
2. **Confinement** — le chemin résolu doit rester sous le dossier des photos. Garde de
   ceinture : même si la première laissait passer quelque chose, rien ne sort.
3. **Type réel** — le contenu téléversé doit commencer par la signature d'une image
   connue. Servir des octets arbitraires sous un type d'image serait offrir une surface
   d'attaque au navigateur.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime

from app.core.exceptions import ValidationFailedError
from app.storage.errors import StorageNotFoundError
from app.storage.paths import MEAL_PHOTOS

#: Forme exacte d'un chemin de photo, telle que nous la produisons.
PHOTO_PATH = re.compile(
    r"^(?P<year>\d{4})/(?P<month>\d{2})/(?P<day>\d{2})/"
    r"(?P<name>\d{8}-\d{6}-[0-9a-f]{8})\.(?P<ext>jpe?g|png|webp|heic)$"
)

#: 12 Mo : une photo de repas prise au téléphone tient largement dedans, et au-delà on
#: paie un téléversement lent sur Nextcloud pour rien.
MAX_BYTES = 12 * 1024 * 1024

CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "heic": "image/heic",
}


class PhotoError(ValidationFailedError):
    """Téléversement refusé.

    Descend du catalogue d'erreurs : un fichier refusé est une saisie invalide, pas une
    panne. Le client reçoit donc `validation_error` et un message affichable.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


def detect_extension(data: bytes) -> str:
    """Extension déduite du **contenu**, pas du nom de fichier ni du type déclaré.

    Un client peut annoncer `image/jpeg` en envoyant n'importe quoi ; c'est la signature
    qui tranche.
    """
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    # HEIC : boîte `ftyp` à l'octet 4, marque `heic`/`heix`/`mif1`.
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"heim"):
        return "heic"
    raise PhotoError("Ce fichier n'est pas une image reconnue (JPEG, PNG, WebP ou HEIC).")


def build_path(data: bytes, when: datetime) -> str:
    """Chemin de rangement d'une nouvelle photo (`NUT-02`).

    `AAAA/MM/JJ/AAAAMMJJ-HHMMSS-aléa.ext`. L'aléa évite qu'une seconde partagée écrase
    la photo précédente ; l'horodatage garde le dossier lisible dans l'ordre.
    """
    if not data:
        raise PhotoError("Le fichier est vide.")
    if len(data) > MAX_BYTES:
        raise PhotoError(f"Photo trop lourde : {MAX_BYTES // (1024 * 1024)} Mo au maximum.")

    extension = detect_extension(data)
    stamp = when.strftime("%Y%m%d-%H%M%S")
    return f"{when:%Y/%m/%d}/{stamp}-{secrets.token_hex(4)}.{extension}"


def storage_path(relative: str) -> str:
    """Chemin de stockage complet d'une photo, après validation stricte.

    Lève `StorageNotFoundError` — et non une erreur de validation — sur un chemin mal
    formé : du point de vue de l'appelant, une adresse qui ne désigne pas une de nos
    photos n'existe pas. Distinguer « mal formé » de « absent » renseignerait sur
    l'arborescence.
    """
    if not PHOTO_PATH.match(relative):
        raise StorageNotFoundError("Cette photo n'existe pas.")

    full = f"{MEAL_PHOTOS}/{relative}"

    # Garde de ceinture : la forme imposée rend déjà la sortie impossible, mais une
    # vérification de confinement coûte une ligne et survit à un assouplissement futur
    # de l'expression régulière.
    if ".." in full.split("/") or not full.startswith(f"{MEAL_PHOTOS}/"):
        raise StorageNotFoundError("Cette photo n'existe pas.")
    return full


def content_type(relative: str) -> str:
    return CONTENT_TYPES[relative.rsplit(".", 1)[-1].lower()]
