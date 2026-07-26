"""Vérification du stockage (`STO-11`).

Écrit puis relit une ligne de test sur Nextcloud, et nettoie derrière lui. Diagnostiquer
la configuration WebDAV **avant** de lancer l'API évite de confondre « mes identifiants
sont faux » et « mon code est cassé ».

    make check-storage
    # ou
    cd backend && .venv/bin/python -m app.scripts.check_storage
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from time import perf_counter

from app.config import get_settings
from app.storage import paths
from app.storage.errors import StorageError
from app.storage.webdav import WebDavClient

OK = "\033[32m✓\033[0m"
KO = "\033[31m✗\033[0m"
DIM = "\033[2m"
RESET = "\033[0m"

#: Chemin du point d'accès WebDAV de Nextcloud. `NEXTCLOUD_URL` doit le contenir :
#: pointer sur la racine du site donne un 404 sur la moindre opération, et le message
#: brut du serveur — « ressource introuvable » — n'aide en rien à comprendre pourquoi.
DAV_ENDPOINT = "/remote.php/dav/files/"


def diagnose_url(url: str, username: str) -> str | None:
    """Aide ciblée si l'URL n'a pas la forme d'un point d'accès WebDAV."""
    if DAV_ENDPOINT in url:
        return None
    base = url.rstrip("/")
    who = username or "<utilisateur>"
    return (
        "NEXTCLOUD_URL pointe sur la racine du site, pas sur le point d'accès WebDAV.\n"
        f"    Remplace-la par :\n\n    NEXTCLOUD_URL={base}{DAV_ENDPOINT}{who}\n"
    )


def step(label: str, detail: str = "", *, ok: bool = True) -> None:
    suffix = f" {DIM}{detail}{RESET}" if detail else ""
    print(f"  {OK if ok else KO} {label}{suffix}")


async def run() -> int:
    settings = get_settings()

    print("\nVérification du stockage Metric\n")

    if not settings.storage_configured:
        step("Configuration", "NEXTCLOUD_URL ou NEXTCLOUD_USERNAME est vide", ok=False)
        print(
            "\n  Renseigne le fichier .env à la racine du dépôt :\n"
            "    NEXTCLOUD_URL=https://…/remote.php/dav/files/<utilisateur>\n"
            "    NEXTCLOUD_USERNAME=<utilisateur>\n"
            "    NEXTCLOUD_PASSWORD=<mot de passe d'application>\n"
        )
        return 2

    step("Configuration", f"{settings.nextcloud_url} → /{settings.nextcloud_root}")

    hint = diagnose_url(settings.nextcloud_url, settings.nextcloud_username)
    if hint:
        step("Forme de l'URL", "point d'accès WebDAV absent", ok=False)
        print(f"\n  {hint}")
        return 2

    client = WebDavClient(
        base_url=settings.nextcloud_url,
        username=settings.nextcloud_username,
        password=settings.nextcloud_password,
        root=settings.nextcloud_root,
    )

    marker = datetime.now(tz=settings.tz).isoformat()
    payload = f"checked_at,note\n{marker},ligne de test Metric\n".encode()

    started = perf_counter()
    try:
        # 1. Connexion et authentification.
        await client.ensure_collection("")
        step("Connexion et identifiants", "dossier racine accessible")

        # 2. Écriture.
        etag = await client.put(paths.HEALTHCHECK, payload)
        step("Écriture", f"{len(payload)} octets" + (f", ETag {etag}" if etag else ""))

        # 3. Relecture.
        fetched = await client.get(paths.HEALTHCHECK)
        if fetched.content != payload:
            step("Relecture", "le contenu relu diffère de ce qui a été écrit", ok=False)
            return 1
        step("Relecture", "contenu identique")

        # 4. Lecture conditionnelle : sans elle, le cache ne peut pas détecter une
        #    modification faite depuis un autre appareil (décision D8).
        if fetched.etag:
            again = await client.get(paths.HEALTHCHECK, etag=fetched.etag)
            if again.not_modified:
                step("Lecture conditionnelle", "304 honoré, le cache pourra revalider")
            else:
                step(
                    "Lecture conditionnelle",
                    "le serveur ignore If-None-Match : chaque revalidation "
                    "retransférera le fichier",
                    ok=False,
                )
        else:
            step(
                "Lecture conditionnelle",
                "aucun ETag renvoyé : la garde anti-conflit sera dégradée",
                ok=False,
            )

        # 5. Nettoyage.
        await client.delete(paths.HEALTHCHECK, missing_ok=True)
        step("Nettoyage", "ligne de test supprimée")

    except StorageError as exc:
        step(type(exc).__name__, str(exc), ok=False)
        print(f"\n  {exc.message}\n")
        hint = diagnose_url(settings.nextcloud_url, settings.nextcloud_username)
        if hint:
            print(f"  {hint}")
        return 1
    finally:
        await client.aclose()

    elapsed = (perf_counter() - started) * 1000
    print(f"\n  Stockage opérationnel. {len(payload)} octets aller-retour en {elapsed:.0f} ms.\n")
    return 0


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
