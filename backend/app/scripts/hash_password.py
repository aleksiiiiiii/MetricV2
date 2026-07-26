"""Génération du hash de mot de passe (`AUTH-08`).

    make hash-password

Le mot de passe est demandé sans écho et ne touche jamais le disque : ni fichier
temporaire, ni argument de ligne de commande — un argument apparaîtrait dans
l'historique du shell et dans la liste des processus.

Seul le hash est affiché, à coller dans `AUTH_PASSWORD_HASH`. Il embarque son sel, donc
deux exécutions sur le même mot de passe donnent deux chaînes différentes : c'est normal,
les deux sont valides.
"""

from __future__ import annotations

import getpass
import secrets
import sys

from app.core.security import hash_password

MIN_LENGTH = 12


def run() -> int:
    print("\nGénération du hash Argon2id pour Metric\n")

    try:
        password = getpass.getpass("  Mot de passe          : ")
        confirmation = getpass.getpass("  Confirmation          : ")
    except (KeyboardInterrupt, EOFError):
        print("\n  Abandon.\n")
        return 130

    if not secrets.compare_digest(password, confirmation):
        print("\n  Les deux saisies diffèrent. Rien n'a été généré.\n", file=sys.stderr)
        return 1

    if len(password) < MIN_LENGTH:
        print(
            f"\n  Mot de passe trop court : {MIN_LENGTH} caractères minimum.\n"
            "  C'est le seul rempart devant toutes tes données.\n",
            file=sys.stderr,
        )
        return 1

    print("\n  Hachage en cours (Argon2 est lent par conception)…\n")
    digest = hash_password(password)

    print("  À coller dans le fichier .env à la racine du dépôt :\n")
    print(f"AUTH_PASSWORD_HASH={digest}\n")
    print("  Pense aussi à renseigner JWT_SECRET :\n")
    print(f"JWT_SECRET={secrets.token_urlsafe(48)}\n")
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
