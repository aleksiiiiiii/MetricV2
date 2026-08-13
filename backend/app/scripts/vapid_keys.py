"""Génération de la paire de clés VAPID (`NOT-01`).

    make vapid-keys

Web Push identifie le serveur d'application par une paire de clés ECDSA sur la courbe
P-256 (RFC 8292). La publique part au navigateur — elle est **destinée** à être vue, c'est
elle qu'un appareil enregistre en s'abonnant ; la privée signe chaque envoi et ne doit
sortir d'ici que pour aller dans `.env`.

Rien n'est écrit sur le disque : les deux valeurs sont affichées, à coller. Un fichier
temporaire de clé privée est exactement le genre de chose qu'on oublie de supprimer.

**Changer de paire désabonne tout le monde.** Un abonnement est lié à la clé publique qui
l'a créé : les appareils déjà enregistrés continueraient d'exister côté service push, et
tous les envois seraient refusés. Générer une nouvelle paire demande donc de vider
`notifications/subscriptions.csv` et de se réabonner — le script le rappelle.
"""

from __future__ import annotations

import base64
import sys

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02


def _b64(raw: bytes) -> str:
    """base64url sans remplissage — la forme que Web Push attend partout."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def run() -> int:
    vapid = Vapid02()
    vapid.generate_keys()

    if vapid.public_key is None or vapid.private_key is None:  # pragma: no cover - défensif
        print("  La génération n'a rien produit.", file=sys.stderr)
        return 1

    public = _b64(
        vapid.public_key.public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
    )
    private = _b64(vapid.private_key.private_numbers().private_value.to_bytes(32, "big"))

    print("\nPaire de clés VAPID pour Metric\n")
    print("  À coller dans .env :\n")
    print(f"  VAPID_PUBLIC_KEY={public}")
    print(f"  VAPID_PRIVATE_KEY={private}")
    print("  VAPID_SUBJECT=mailto:ton@adresse.fr")
    print(
        "\n  La clé publique part au navigateur : elle est faite pour être vue."
        "\n  La privée signe les envois — elle ne sort pas de .env.\n"
        "\n  Attention : changer de paire invalide les abonnements existants."
        "\n  Il faudra vider notifications/subscriptions.csv et se réabonner.\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
