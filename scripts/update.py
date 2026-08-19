#!/usr/bin/env python3
"""Mise à jour du déploiement de Metric.

    make update              # « check » : ce qui tourne, ce qui est disponible. Rien n'est touché.
    make update ARGS=run
    make update ARGS="run --dry-run"
    make update ARGS=rollback

Le script tourne **sur le serveur**, pas sur la machine de développement. Cible : Linux,
systemd, derrière Nginx Proxy Manager, rien de conteneurisé.

── Trois contraintes expliquent tout ce qui suit ─────────────

* **Il doit tourner quand l'application est cassée**, puisque c'est exactement le moment où
  on le lance. Donc Python de la bibliothèque standard uniquement, et surtout **aucun
  besoin du venv** — qu'il est précisément chargé de reconstruire.

* **Sa syntaxe reste compatible 3.9**, alors que l'application exige 3.12. Ce n'est pas une
  négligence : le contrôle « ta version de Python est trop vieille » doit pouvoir
  *s'afficher* sur la machine qui a la version trop vieille. Un script qui refuse de se
  compiler sur Debian 12 rendrait une erreur de syntaxe là où on attend une phrase.

* **On ne remplace jamais en place, on bascule un lien.** Il n'y a aucune annulation nulle
  part dans ce projet. Vider un dossier puis extraire par-dessus laisse, si l'extraction
  échoue au milieu — réseau coupé, archive tronquée, disque plein —, une application ni
  ancienne ni nouvelle, et rien pour revenir.

── Ce qu'il ne fait pas, et c'est délibéré ───────────────────

* **Il ne touche pas à Nextcloud.** Les données y vivent et y survivent à tout ce qu'il
  fait. Il n'y a aucune migration de schéma à jouer : `STO-04` remappe les en-têtes CSV à
  la lecture et préserve une colonne inconnue. Le format se rattrape seul au premier accès.
* **Il ne configure pas NPM** — ni certificat, ni vhost. Il doit seulement ne pas casser ce
  que NPM pointe, d'où le chemin stable `<racine>/current`.
* **Il n'a pas besoin de root.** L'unité systemd est *écrite* dans `shared/`, et les deux
  commandes pour l'installer sont affichées. Un script de mise à jour qui réclame sudo
  finit par être lancé en root pour de mauvaises raisons.

── Sur l'unité systemd : pas d'`EnvironmentFile=` ────────────

`docs/prompt-mise-a-jour.md` §5 le demandait ; `docs/deploiement.md` §3.2 l'interdit, et
c'est lui qu'on suit. L'application lit déjà `.env` elle-même (`pydantic-settings`,
`backend/app/config.py`). Passer par systemd ajouterait un **second analyseur** du même
fichier, avec ses propres règles de guillemets — et `AUTH_PASSWORD_HASH` commence par
`$argon2id$v=19$m=…`, c'est-à-dire précisément le genre de valeur sur laquelle deux
analyseurs se mettent à diverger. Chaque release porte donc un lien vers `shared/.env`.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

DEPOT = "aleksiiiiiii/MetricV2"
REF_PAR_DEFAUT = "main"
UNITE = "metric-api"
PORT_API = 8000

#: Assez pour reculer de deux crans, pas assez pour remplir le disque.
RELEASES_GARDEES = 3

#: Au-delà, on considère que l'API ne revient pas et on rebascule.
DELAI_SANTE = 30

#: Trois releases, deux « node_modules » et deux « .venv » pèsent. En dessous de ça, on
#: refuse d'entamer une extraction plutôt que de la voir échouer au milieu.
PLACE_MINIMALE_MO = 2048

PYTHON_MINIMAL = (3, 12)
NODE_MINIMAL = 20

# ── Couleurs, reprises de « scripts/metric.py » ───────
# Deux scripts du même dépôt qui parlent deux langues visuelles, c'est un de trop.
SIGNAL = "\033[38;2;127;168;180m"
EFFORT = "\033[38;2;138;163;123m"
LOAD = "\033[38;2;195;155;110m"
RECOVER = "\033[38;2;169;116;138m"
INK_LOW = "\033[38;2;92;104;116m"
BOLD = "\033[1m"
RESET = "\033[0m"

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def paint(text, color):
    return "{}{}{}".format(color, text, RESET) if USE_COLOR else text


def say(text=""):
    print(text)


def ok(text):
    say("  {} {}".format(paint("✓", EFFORT), text))


def warn(text):
    say("  {} {}".format(paint("!", LOAD), text))


def fail(text):
    say("  {} {}".format(paint("✗", RECOVER), text))


def dim(text):
    return paint(text, INK_LOW)


#: Nombre d'étapes de la commande en cours. Zéro quand la commande n'en compte pas —
#: « check » et « releases » ne sont pas des procédures, les numéroter mentirait sur ce
#: qu'elles font.
ETAPES_TOTAL = 0
_etape_courante = 0


def etape(text, numerote=True):
    global _etape_courante
    prefixe = ""
    if numerote and ETAPES_TOTAL and _etape_courante < ETAPES_TOTAL:
        _etape_courante += 1
        prefixe = "[{}/{}] ".format(_etape_courante, ETAPES_TOTAL)
    say()
    say("  {}".format(paint(prefixe + text, BOLD + SIGNAL)))


def champ(nom, valeur):
    """Une ligne clé/valeur alignée, pour les récapitulatifs."""
    say("      {}  {}".format(dim(nom.ljust(9)), valeur))


class Arret(Exception):
    """Interruption annoncée.

    Un message vide veut dire que l'explication a déjà été affichée, en détail, à
    l'endroit où le problème a été constaté : la répéter en une ligne au moment de sortir
    la rendrait plus pauvre, pas plus visible.
    """


# ── Le mode simulation ────────────────────────────────
#
# Ce n'est pas une option de confort : c'est ce qui permet de lire le plan avant de
# l'exécuter sur la seule installation qui porte de vraies données de santé.

SIMULATION = False


def simule(description):
    """Affiche l'action et rend vrai si elle ne doit pas être exécutée."""
    if SIMULATION:
        say("  {} {}".format(paint("·", INK_LOW), dim(description)))
        return True
    return False


def executer(commande, cwd=None, verifie=True):
    """Lance une commande, sortie en direct. Rend le code de retour."""
    if simule("$ " + " ".join(str(part) for part in commande)):
        return 0
    try:
        resultat = subprocess.run(commande, cwd=str(cwd) if cwd else None)
    except OSError as erreur:
        # Une commande absente du PATH — « sudo » sur une machine qui n'en a pas — rendait
        # une trace Python au milieu d'un déploiement. C'est le pire moment pour ça.
        raise Arret("{} not found on this machine ({})".format(commande[0], erreur))
    if verifie and resultat.returncode != 0:
        raise Arret("{} failed with exit code {}".format(" ".join(commande), resultat.returncode))
    return resultat.returncode


def capturer(commande, cwd=None):
    """Lance une commande en silence. Rend (code, sortie) — jamais d'exception."""
    try:
        resultat = subprocess.run(
            commande,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError:
        return 127, ""
    return resultat.returncode, resultat.stdout.decode("utf-8", "replace").strip()


# ── La configuration d'installation ───────────────────
#
# Trois valeurs ne se devinent pas et ne se demandent pas à chaque exécution :
# « migrate-layout » les demande une fois et les écrit dans shared/deploy.conf.


class Config(object):
    def __init__(self, racine, utilisateur, npm_local, depot):
        self.racine = racine
        self.utilisateur = utilisateur
        self.npm_local = npm_local
        self.depot = depot

    @property
    def releases(self):
        return self.racine / "releases"

    @property
    def shared(self):
        return self.racine / "shared"

    @property
    def backups(self):
        return self.racine / "backups"

    @property
    def current(self):
        return self.racine / "current"

    @property
    def env(self):
        return self.shared / ".env"

    @property
    def fichier_conf(self):
        return self.shared / "deploy.conf"


def deviner_racine(demandee):
    """La racine d'installation, ou None si on ne peut pas l'affirmer.

    Deviner une racine d'installation, c'est risquer d'écrire à côté de ce qui tourne :
    en cas de doute, cette fonction rend None et l'appelant s'arrête.
    """
    if demandee:
        return Path(demandee).expanduser().resolve()
    depuis_env = os.environ.get("METRIC_RACINE")
    if depuis_env:
        return Path(depuis_env).expanduser().resolve()

    # Le script vit dans une release : <racine>/releases/<nom>/scripts/update.py
    ici = Path(__file__).resolve()
    parents = ici.parents
    if len(parents) > 3 and parents[2].name == "releases":
        return parents[3]
    return None


def charger_config(racine_demandee, obligatoire=True):
    racine = deviner_racine(racine_demandee)
    if racine is None:
        if not obligatoire:
            return None
        fail("Installation root unknown")
        say(dim("      Pass --racine /opt/metric, or run this script from <root>/current/"))
        raise Arret("")

    fichier = racine / "shared" / "deploy.conf"
    if not fichier.exists():
        if not obligatoire:
            return Config(racine, "", True, DEPOT)
        fail("{} is missing".format(fichier))
        say(dim("      Layout was never initialised. Run: make update ARGS=migrate-layout"))
        raise Arret("")

    valeurs = {}
    for brut in fichier.read_text(encoding="utf-8").splitlines():
        ligne = brut.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        nom, _, valeur = ligne.partition("=")
        valeurs[nom.strip()] = valeur.strip()

    return Config(
        racine=racine,
        utilisateur=valeurs.get("utilisateur", ""),
        npm_local=valeurs.get("npm_local", "oui").lower() in ("oui", "true", "1"),
        depot=valeurs.get("depot", DEPOT),
    )


def lire_env(config):
    """Contenu de shared/.env, sous forme de dictionnaire. Vide s'il n'existe pas."""
    if not config.env.exists():
        return {}
    valeurs = {}
    try:
        contenu = config.env.read_text(encoding="utf-8")
    except OSError:
        return {}
    for brut in contenu.splitlines():
        ligne = brut.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        nom, _, valeur = ligne.partition("=")
        valeurs[nom.strip()] = valeur.strip()
    return valeurs


# ── 5bis. Les préalables, vérifiés avant de toucher à quoi que ce soit ──


def verifier_prealables(config):
    """Refuse tôt, et clairement. Les trois contrôles ont chacun mordu quelqu'un."""
    etape("Preflight checks")
    problemes = []

    # Debian 12 livre Python 3.11. « make setup » y échoue APRÈS avoir créé un venv à
    # moitié — une installation ni faite ni défaite. D'où le contrôle ici, et pas plus loin.
    version = sys.version_info[:2]
    if version < PYTHON_MINIMAL:
        fail("Python {}.{} found, {}.{} or newer required".format(
            version[0], version[1], PYTHON_MINIMAL[0], PYTHON_MINIMAL[1]))
        say(dim("      Debian/Ubuntu: sudo apt install python3.12 python3.12-venv"))
        problemes.append("python")
    else:
        ok("Python {}.{}".format(version[0], version[1]))

    # Vite 8 et TypeScript 6 ne tournent pas sur le Node d'une distribution ancienne.
    if shutil.which("npm") is None or shutil.which("node") is None:
        fail("node and npm not found on PATH")
        problemes.append("node")
    else:
        code, sortie = capturer(["node", "--version"])
        majeure = 0
        if code == 0 and sortie.startswith("v"):
            try:
                majeure = int(sortie[1:].split(".")[0])
            except ValueError:
                majeure = 0
        if majeure and majeure < NODE_MINIMAL:
            fail("Node {} found, {} or newer required (Vite 8, TypeScript 6)".format(
                sortie, NODE_MINIMAL))
            problemes.append("node")
        else:
            ok("Node {}".format(sortie or "present"))

    if shutil.which("make") is None:
        fail("make not found — setup and build both rely on it")
        problemes.append("make")

    # Un disque plein au milieu d'une extraction est exactement le scénario contre lequel
    # la bascule par lien existe. Autant ne pas y arriver.
    try:
        libre_mo = shutil.disk_usage(str(config.racine)).free // (1024 * 1024)
    except OSError:
        libre_mo = None
    if libre_mo is None:
        warn("Free disk space could not be determined")
    elif libre_mo < PLACE_MINIMALE_MO:
        fail("{} MB free, at least {} MB required".format(libre_mo, PLACE_MINIMALE_MO))
        problemes.append("disque")
    else:
        ok("{} MB free".format(libre_mo))

    # Un chown manqué donne une API qui démarre et refuse toute connexion — ce qui
    # ressemble trait pour trait à un mot de passe faux, et fait chercher au mauvais endroit.
    if not config.env.exists():
        fail("{} is missing — secrets cannot be regenerated".format(config.env))
        problemes.append("env")
    else:
        mode = config.env.stat().st_mode & 0o777
        if mode != 0o600:
            warn(".env permissions are {:o}, expected 600".format(mode))
            say(dim("      Fix with: chmod 600 {}".format(config.env)))
        else:
            ok(".env permissions 600")
        if not os.access(str(config.env), os.R_OK):
            fail(".env is not readable by the current user")
            problemes.append("env")

    if problemes:
        raise Arret("Preflight failed: " + ", ".join(sorted(set(problemes))))


# ── 1. La sauvegarde, vérifiée avant que quoi que ce soit ne bouge ──


def empreinte(chemin):
    digest = hashlib.sha256()
    with open(str(chemin), "rb") as flux:
        for bloc in iter(lambda: flux.read(65536), b""):
            digest.update(bloc)
    return digest.hexdigest()


def sauvegarder(config):
    """Archive shared/, puis RELIT l'archive et compare les empreintes.

    Tout ce qui est local et irremplaçable vit dans shared/ — c'est la définition même de
    ce dossier. Le reste se reconstruit (.venv, node_modules, dist) ou vit sur Nextcloud.

    Une sauvegarde qu'on n'a pas relue n'est pas une sauvegarde : d'où la relecture, qui
    n'est pas une précaution de style mais la condition pour aller plus loin.
    """
    etape("Backup")
    horodatage = time.strftime("%Y-%m-%dT%H-%M-%S")
    archive = config.backups / "shared-{}.tar.gz".format(horodatage)

    originaux = sorted(p for p in config.shared.rglob("*") if p.is_file())
    if not originaux:
        raise Arret("shared/ is empty — nothing to back up, which is not normal")

    if simule("archive {} file(s) from shared/ to {}".format(len(originaux), archive)):
        return archive

    config.backups.mkdir(parents=True, exist_ok=True)
    attendues = {}
    with tarfile.open(str(archive), "w:gz") as flux:
        for fichier in originaux:
            relatif = fichier.relative_to(config.shared).as_posix()
            attendues[relatif] = empreinte(fichier)
            flux.add(str(fichier), arcname=relatif)
    os.chmod(str(archive), 0o600)

    # La relecture. Elle porte sur le contenu, pas sur la taille du fichier : une archive
    # tronquée peut avoir l'air d'une archive.
    relues = {}
    with tarfile.open(str(archive), "r:gz") as flux:
        for membre in flux.getmembers():
            if not membre.isfile():
                continue
            extrait = flux.extractfile(membre)
            if extrait is None:
                continue
            digest = hashlib.sha256()
            for bloc in iter(lambda: extrait.read(65536), b""):
                digest.update(bloc)
            relues[membre.name] = digest.hexdigest()

    if relues != attendues:
        manquants = sorted(set(attendues) - set(relues))
        divergents = sorted(n for n in set(attendues) & set(relues) if attendues[n] != relues[n])
        fail("Backup does not match the original")
        for nom in manquants:
            say(dim("      missing from archive: " + nom))
        for nom in divergents:
            say(dim("      checksum mismatch:    " + nom))
        raise Arret("Backup could not be verified — nothing has been modified")

    ok("{} file(s) archived and read back".format(len(attendues)))
    say(dim("      " + str(archive)))

    # Les quatre secrets dont la perte est irréversible ET silencieuse.
    env = lire_env(config)
    for cle in ("VAPID_PRIVATE_KEY", "ICAL_SECRET", "AUTH_PASSWORD_HASH", "NEXTCLOUD_PASSWORD"):
        if not env.get(cle):
            warn("{} is empty in .env".format(cle))
    say(dim("      Keep a copy OFF this machine. These secrets are the only"))
    say(dim("      unrecoverable part of the deployment."))
    return archive


# ── 3. Une archive, pas un clone ──────────────────────


def requete(url, jeton=None, accept=None):
    entetes = {"User-Agent": "metric-update"}
    if jeton:
        entetes["Authorization"] = "Bearer " + jeton
    if accept:
        entetes["Accept"] = accept
    return urllib.request.Request(url, headers=entetes)


def message_404(depot):
    # Un 404 de GitHub sur un dépôt privé est indistinguable d'un dépôt qui n'existe pas.
    # C'est exactement le genre de message qui fait chercher une heure.
    fail("GitHub returned 404 for {}".format(depot))
    say(dim("      Private repository? Set GITHUB_TOKEN in shared/.env"))
    say(dim("      Otherwise check the repository name in shared/deploy.conf"))


def resoudre_sha(config, ref, jeton):
    """Le SHA visé par une ref. Sans lui, on ne saurait pas nommer la release."""
    url = "https://api.github.com/repos/{}/commits/{}".format(config.depot, ref)
    try:
        with urllib.request.urlopen(
            requete(url, jeton, "application/vnd.github+json"), timeout=20
        ) as reponse:
            charge = json.loads(reponse.read().decode("utf-8"))
        return charge.get("sha", "")
    except urllib.error.HTTPError as erreur:
        if erreur.code == 404:
            message_404(config.depot)
            raise Arret("")
        warn("Could not resolve SHA (HTTP {}); release will be named after the ref".format(
            erreur.code))
        return ""
    except (urllib.error.URLError, OSError, ValueError):
        warn("Could not resolve SHA (network); release will be named after the ref")
        return ""


def telecharger(config, ref, jeton, destination):
    """Télécharge l'archive, la vérifie EN ENTIER, puis seulement l'extrait.

    L'ordre est ce qui compte. Une archive tronquée qui s'extrait à moitié laisserait un
    dossier de release à moitié peuplé ; ici elle échoue avant qu'un seul fichier ne soit
    posé, et « releases/ » reste propre.
    """
    url = "https://codeload.github.com/{}/tar.gz/{}".format(config.depot, ref)
    say(dim("      " + url))
    if simule("download and extract to " + str(destination)):
        return

    try:
        with urllib.request.urlopen(requete(url, jeton), timeout=120) as reponse:
            brut = reponse.read()
    except urllib.error.HTTPError as erreur:
        if erreur.code == 404:
            message_404(config.depot)
            raise Arret("")
        raise Arret("Download failed (HTTP {})".format(erreur.code))
    except (urllib.error.URLError, OSError) as erreur:
        raise Arret("Download failed ({})".format(erreur))

    # Décompresser en mémoire vérifie le CRC gzip : une archive coupée échoue ICI.
    try:
        tar_brut = gzip.decompress(brut)
    except (OSError, EOFError, gzip.BadGzipFile):
        raise Arret("Archive is truncated or corrupt — nothing was extracted")

    ok("{} KB received, archive integrity verified".format(len(brut) // 1024))

    # Extraction dans un dossier temporaire, renommé seulement à la fin. Un « releases/ »
    # ne contient donc jamais de release à demi extraite.
    temporaire = destination.parent / (".tmp-" + destination.name)
    if temporaire.exists():
        shutil.rmtree(str(temporaire))
    temporaire.mkdir(parents=True)

    with tarfile.open(fileobj=io.BytesIO(tar_brut), mode="r:") as flux:
        membres = []
        for membre in flux.getmembers():
            # --strip-components=1 : GitHub préfixe tout par « MetricV2-<ref> ».
            morceaux = membre.name.split("/", 1)
            if len(morceaux) < 2 or not morceaux[1]:
                continue
            membre.name = morceaux[1]
            # Garde contre la traversée de chemin. Une archive vient du réseau.
            cible = (temporaire / membre.name).resolve()
            if not str(cible).startswith(str(temporaire.resolve()) + os.sep):
                raise Arret("Unsafe archive: {} escapes the target directory".format(membre.name))
            membres.append(membre)
        # « filter » n'existe qu'à partir de 3.12 ; la garde ci-dessus tient sans lui.
        if sys.version_info >= (3, 12):
            flux.extractall(str(temporaire), members=membres, filter="data")
        else:
            flux.extractall(str(temporaire), members=membres)

    if not (temporaire / "Makefile").exists():
        shutil.rmtree(str(temporaire))
        raise Arret("Unexpected archive: no Makefile at its root")

    temporaire.rename(destination)
    ok("Extracted to " + destination.name)


def ecrire_release(chemin, ref, sha):
    """Ce qui permet de répondre à « qu'est-ce qui tourne, là ? » sans ouvrir du code."""
    contenu = "ref={}\nsha={}\nhorodatage={}\n".format(
        ref, sha or "inconnu", time.strftime("%Y-%m-%dT%H:%M:%S%z")
    )
    if simule("write " + str(chemin / "RELEASE")):
        return
    (chemin / "RELEASE").write_text(contenu, encoding="utf-8")


def lire_release(chemin):
    fichier = chemin / "RELEASE"
    if not fichier.exists():
        return {}
    valeurs = {}
    try:
        for brut in fichier.read_text(encoding="utf-8").splitlines():
            if "=" in brut:
                nom, _, valeur = brut.partition("=")
                valeurs[nom.strip()] = valeur.strip()
    except OSError:
        return {}
    return valeurs


# ── 4. Les dépendances se réinstallent, toujours ──────


def preparer(config, release, sauter_check):
    """make setup, make build, make check — dans cet ordre, dans la release préparée."""
    etape("Build")

    # Le lien vers .env AVANT « make check » : la batterie backend lit la configuration.
    lien_env = release / ".env"
    if not simule("link {} -> {}".format(lien_env, config.env)):
        if lien_env.exists() or lien_env.is_symlink():
            lien_env.unlink()
        os.symlink(str(config.env), str(lien_env))
    ok(".env linked from shared/")

    # Non négociable. Le lot L15 en a donné la démonstration : il a ajouté « pywebpush »
    # au pyproject. Une mise à jour qui aurait recopié l'ancien venv aurait démarré une API
    # qui plante à l'import, quelques secondes après « mise à jour réussie ».
    say(dim("      make setup — backend venv and npm install, never one without the other"))
    executer(["make", "setup"], cwd=release)
    ok("Dependencies installed")

    # « frontend/dist » est ignoré par git, donc absent de l'archive : sans build il n'y a
    # pas d'application, seulement des sources. Et c'est le SEUL endroit où le service
    # worker est produit (L15-02).
    executer(["make", "build"], cwd=release)
    if not SIMULATION and not (release / "frontend/dist/index.html").exists():
        raise Arret("make build produced no index.html")
    ok("Production bundle built")

    if sauter_check:
        warn("make check skipped (--skip-check) — the last safety net is down")
        return
    # Une release qui ne passe pas ses propres tests ne devient pas « current ».
    executer(["make", "check"], cwd=release)
    ok("Test suite green")


# ── 2. La bascule, et son inverse ─────────────────────


def cible_actuelle(config):
    """Vers quoi « current » pointe, ou None."""
    if not config.current.is_symlink():
        return None
    try:
        return Path(os.readlink(str(config.current)))
    except OSError:
        return None


def basculer(config, release):
    """Déplace le lien « current ». Atomique — c'est toute la raison d'être du §2.

    « ln -sfn » supprime puis recrée : il existe un instant, court mais réel, où « current »
    n'existe pas. Un « os.replace » d'un lien temporaire sur l'ancien est un seul appel
    noyau, et NPM ne peut donc jamais lire un chemin absent.
    """
    if simule("switch current -> " + str(release)):
        return
    temporaire = config.racine / ".current.{}".format(os.getpid())
    if temporaire.exists() or temporaire.is_symlink():
        temporaire.unlink()
    os.symlink(str(release), str(temporaire))
    try:
        os.replace(str(temporaire), str(config.current))
    except IsADirectoryError:
        temporaire.unlink()
        raise Arret(
            "current is a real directory, not a symlink — run migrate-layout first"
        )


# ── 5. Sur le serveur, c'est systemd qui détient l'API ──


def commande_systemctl(*arguments):
    """`systemctl`, précédé de `sudo` seulement si c'est nécessaire **et** possible.

    Une machine où l'on est déjà root n'a souvent pas `sudo` installé — c'est le cas des
    Debian minimales et des conteneurs, où il ne sert à rien. Préfixer aveuglément par
    `sudo` y faisait échouer le redémarrage **après** la bascule, c'est-à-dire au seul
    moment où l'application est déjà sur la nouvelle release sans y avoir redémarré.

    Rend `None` quand ni l'un ni l'autre n'est possible : l'appelant le dit et s'arrête,
    plutôt que de laisser croire que le redémarrage a eu lieu.
    """
    base = ["systemctl", *arguments]
    if os.geteuid() == 0:
        return base
    if shutil.which("sudo"):
        return ["sudo", *base]
    return None


def systemd_present():
    if shutil.which("systemctl") is None:
        return False
    code, _ = capturer(["systemctl", "cat", UNITE])
    return code == 0


def redemarrer(config):
    etape("Restart")
    # Le WorkingDirectory de l'unité passe par « current », et systemd résout le lien AU
    # DÉMARRAGE. Sans ce redémarrage, l'unité tournerait encore sur l'ancienne release —
    # c'est le piège classique de cette structure, et la bascule seule ne suffit jamais.
    if systemd_present():
        commande = commande_systemctl("restart", UNITE)
        if commande is None:
            fail("Unit exists but neither root nor sudo is available to restart it")
            say(dim("      current ALREADY points at the new release; the API is still"))
            say(dim("      running the previous one until it restarts."))
            say(dim("      As root:  systemctl restart " + UNITE))
            say(dim("      Then:     curl -s http://127.0.0.1:{}/api/health".format(PORT_API)))
            raise Arret("")
        executer(commande)
        ok(" ".join(commande))
        return True

    warn("systemd unit {} not found — falling back".format(UNITE))
    say(dim("      make update ARGS=migrate-layout writes the unit and explains how to install it"))
    say(dim("      Meanwhile the console restarts the API: make console -- restart api"))
    if not simule("make console -- restart api"):
        code, sortie = capturer(["python3", "scripts/metric.py", "restart", "api"], cwd=config.current)
        if code != 0:
            warn("The console could not restart the API")
            if sortie:
                say(dim("      " + sortie.splitlines()[-1]))
            return False
    ok("API restarted by the console")
    return False


def sante(delai=DELAI_SANTE):
    """Interroge /api/health jusqu'à ce qu'elle réponde, ou jusqu'au délai.

    Rend (vivante, charge). « storage_configured » et « auth_configured » sont ce qui
    distingue une API qui répond d'une API qui sert.
    """
    if SIMULATION:
        say("  {} {}".format(paint("·", INK_LOW), dim("query /api/health")))
        return True, {}
    url = "http://127.0.0.1:{}/api/health".format(PORT_API)
    limite = time.time() + delai
    derniere = ""
    while time.time() < limite:
        try:
            with urllib.request.urlopen(url, timeout=3) as reponse:
                charge = json.loads(reponse.read().decode("utf-8"))
            return True, charge
        except (urllib.error.URLError, OSError, ValueError) as erreur:
            derniere = str(erreur)
            time.sleep(1)
    say(dim("      last error: " + derniere))
    return False, {}


def verifier_sante(config):
    etape("Health check")
    vivante, charge = sante()
    if not vivante:
        fail("/api/health did not respond within {}s".format(DELAI_SANTE))
        return False
    if SIMULATION:
        return True

    ok("version {} · {}".format(charge.get("version", "?"), charge.get("environment", "?")))
    complet = True
    for cle in ("storage_configured", "auth_configured"):
        if charge.get(cle):
            ok(cle)
        else:
            fail(cle + " est faux")
            complet = False
    if not complet:
        say(dim("      Run make check-storage in current/ to see which setting is missing"))
    return complet


# ── 11. Ce qui est détruit est annoncé avant, pas après ──


def releases_triees(config):
    if not config.releases.is_dir():
        return []
    return sorted(
        (p for p in config.releases.iterdir() if p.is_dir() and not p.name.startswith(".")),
        key=lambda p: p.name,
    )


def elaguer(config):
    """Garde trois releases. Jamais celle vers laquelle current pointe, ni la précédente."""
    toutes = releases_triees(config)
    if len(toutes) <= RELEASES_GARDEES:
        return
    actuelle = cible_actuelle(config)
    protegees = set()
    if actuelle is not None:
        protegees.add(actuelle.name)
    # La précédente, au sens chronologique, indépendamment de sa place dans la liste.
    for release in reversed(toutes):
        if release.name not in protegees:
            protegees.add(release.name)
            break

    candidates = [r for r in toutes if r.name not in protegees][: max(0, len(toutes) - RELEASES_GARDEES)]
    if not candidates:
        return

    etape("Cleanup", numerote=False)
    # Annoncé AVANT. Le projet demande deux appuis pour détruire une ligne de journal ;
    # un script qui efface un dossier sans le dire ne peut pas être plus léger que ça.
    for release in candidates:
        say(dim("      will be removed: {}".format(release.name)))
    for release in candidates:
        if not simule("rm -rf " + str(release)):
            shutil.rmtree(str(release), ignore_errors=True)
    ok("{} old release(s) removed, {} kept".format(
        len(candidates), len(toutes) - len(candidates)))


# ── Les commandes ─────────────────────────────────────


def commande_check(config, ref):
    """Le comportement par défaut. Ne touche à rien.

    Un script de mise à jour qu'on lance par curiosité ne doit pas mettre à jour.
    """
    etape("Currently deployed")
    actuelle = cible_actuelle(config)
    if actuelle is None:
        if config.current.is_dir():
            warn("current is a real directory — flat layout, run migrate-layout")
        else:
            fail("No active release")
    else:
        infos = lire_release(config.releases / actuelle.name)
        ok(actuelle.name)
        if infos:
            champ("ref", infos.get("ref", "?"))
            champ("revision", (infos.get("sha") or "?")[:7])
            champ("deployed", infos.get("horodatage", "?"))
        else:
            say(dim("      No RELEASE file — this release was deployed by hand"))

    if systemd_present():
        code, etat = capturer(["systemctl", "is-active", UNITE])
        (ok if etat == "active" else fail)("systemd: " + (etat or "unknown"))
    else:
        warn("systemd: unit {} not found".format(UNITE))

    vivante, charge = sante(delai=3)
    if vivante:
        ok("/api/health: version {} · {}".format(
            charge.get("version", "?"), charge.get("environment", "?")))
        for cle in ("storage_configured", "auth_configured"):
            (ok if charge.get(cle) else fail)(cle)
    else:
        fail("/api/health is not responding on :{}".format(PORT_API))

    etape("Available upstream")
    jeton = lire_env(config).get("GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    sha = resoudre_sha(config, ref, jeton)
    if sha:
        ok("{} → {}".format(ref, sha[:7]))
        infos = lire_release(config.releases / actuelle.name) if actuelle else {}
        pose = infos.get("sha", "")
        if pose and pose == sha:
            say(dim("      Already deployed — nothing to do"))
        elif pose:
            say(dim("      Deployed: {} — run make update ARGS=run to move to {}".format(
                pose[:7], sha[:7])))
        else:
            say(dim("      Run make update ARGS=run to install it"))

    say()
    return 0


def commande_releases(config):
    etape("Releases")
    toutes = releases_triees(config)
    if not toutes:
        fail("No release found in " + str(config.releases))
        say()
        return 1
    actuelle = cible_actuelle(config)
    nom_actuel = actuelle.name if actuelle is not None else ""
    # Les noms de release n'ont pas tous la même longueur — une migration en porte un plus
    # long qu'un horodatage. Aligner sur le plus large garde la colonne de droite lisible.
    largeur = max(len(release.name) for release in toutes)
    for release in toutes:
        infos = lire_release(release)
        marque = paint("●", EFFORT) if release.name == nom_actuel else dim("·")
        detail = ""
        if infos:
            detail = dim("  {}  {}".format(
                (infos.get("sha") or "?")[:7], infos.get("ref", "?")))
        say("  {} {}{}".format(marque, release.name.ljust(largeur), detail))
    say()
    say(dim("      ● = served by current. {} releases kept at most.".format(RELEASES_GARDEES)))
    say()
    return 0


def commande_rollback(config, nom):
    """Pour le cas où la panne se voit dix minutes plus tard."""
    etape("Rollback")
    toutes = releases_triees(config)
    actuelle = cible_actuelle(config)
    nom_actuel = actuelle.name if actuelle is not None else ""

    if nom:
        cible = config.releases / nom
        if not cible.is_dir():
            fail("Unknown release: " + nom)
            say(dim("      Run make update ARGS=releases to list them"))
            return 1
    else:
        precedentes = [r for r in toutes if r.name != nom_actuel]
        if not precedentes:
            fail("No previous release to roll back to")
            return 1
        cible = precedentes[-1]

    say(dim("      {} → {}".format(nom_actuel or "?", cible.name)))
    basculer(config, cible)
    ok("current now points at " + cible.name)
    redemarrer(config)
    if verifier_sante(config):
        ok("Rollback complete")
        say()
        return 0
    fail("The API is not responding on this release either")
    say(dim("      Run make update ARGS=releases, then roll back to an older one"))
    say()
    return 1


def commande_run(config, ref, sauter_check, forcer):
    global ETAPES_TOTAL, _etape_courante
    # Huit étapes, dans l'ordre : préalables, cible, sauvegarde, téléchargement, build,
    # bascule, redémarrage, santé. Le nettoyage et le récapitulatif ne sont pas numérotés :
    # ils ne peuvent pas échouer et n'engagent rien.
    ETAPES_TOTAL, _etape_courante = 8, 0
    debut = time.time()
    if SIMULATION:
        say()
        warn("DRY RUN — every step is printed, nothing is executed")

    verifier_prealables(config)

    etape("Target revision")
    jeton = lire_env(config).get("GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    sha = resoudre_sha(config, ref, jeton)
    actuelle = cible_actuelle(config)
    if sha and actuelle is not None and not forcer:
        pose = lire_release(config.releases / actuelle.name).get("sha", "")
        if pose == sha:
            ok("{} is already deployed ({})".format(sha[:7], actuelle.name))
            say(dim("      Pass --force to reinstall it anyway"))
            say()
            return 0
    ok("{} → {}".format(ref, sha[:7] if sha else "SHA inconnu"))

    sauvegarder(config)

    etape("Download")
    nom = "{}-{}".format(time.strftime("%Y-%m-%dT%H-%M-%S"), sha[:7] if sha else ref.replace("/", "-"))
    release = config.releases / nom
    config.releases.mkdir(parents=True, exist_ok=True)
    telecharger(config, ref, jeton, release)
    ecrire_release(release, ref, sha)

    try:
        preparer(config, release, sauter_check)
    except Arret:
        # La release préparée a échoué : elle n'est jamais devenue « current », donc
        # l'application qui tourne n'a pas bougé d'un pouce. C'est exactement ce que la
        # structure du §2 achète.
        fail("Release {} could not be prepared".format(nom))
        say(dim("      current has not moved — the running application is untouched"))
        say(dim("      The failed release is kept on disk for diagnosis:"))
        say(dim("      " + str(release)))
        say()
        raise

    etape("Switch")
    precedente = actuelle.name if actuelle is not None else ""
    basculer(config, release)
    ok("current → " + nom)
    if precedente:
        say(dim("      previous: " + precedente))

    redemarrer(config)

    if not verifier_sante(config) and not SIMULATION:
        # Un retour arrière automatique est ce qui distingue un script de mise à jour d'un
        # script d'espoir.
        fail("Health did not come back — rolling back automatically")
        if not precedente:
            fail("and there is no previous release to roll back to")
            say()
            return 1
        basculer(config, config.releases / precedente)
        redemarrer(config)
        vivante, _ = sante()
        if vivante:
            ok("Rolled back to " + precedente)
            say(dim("      Release {} is kept on disk for diagnosis".format(nom)))
        else:
            fail("The API is not responding on " + precedente + " either")
            say(dim("      Logs: journalctl -u {} -n 50".format(UNITE)))
        say()
        return 1

    elaguer(config)

    etape("Summary", numerote=False)
    ok("Update completed in {}s".format(int(time.time() - debut)))
    say()
    champ("release", nom)
    champ("revision", "{} ({})".format(sha[:7] if sha else "unknown", ref))
    if precedente:
        champ("previous", precedente)
    if config.npm_local:
        champ("frontend", "{}/frontend/dist".format(config.current))
    champ("rollback", "make update ARGS=rollback")
    say()
    # Ce que « make console -- proxy » dit déjà en détail, rappelé en une ligne.
    say(dim("      Reminder: NPM sits in front. CORS_ORIGINS must carry the public HTTPS"))
    say(dim("      address, and TRUST_PROXY_HEADERS must be true — otherwise five failed"))
    say(dim("      logins lock out everyone. Verify with: make console -- proxy"))
    say()
    return 0


# ── migrate-layout ────────────────────────────────────


UNITE_SYSTEMD = """[Unit]
Description=Metric — API
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User={utilisateur}
Group={utilisateur}
WorkingDirectory={racine}/current/backend

# Un seul worker, et ce n'est pas un réglage de performance. L'ordonnanceur des rappels
# (NOT-02) tourne DANS le processus de l'API : deux workers, c'est deux ordonnanceurs, donc
# la notification envoyée en double. « sent.csv » déduplique entre deux passes, pas entre
# deux processus qui lisent au même instant.
ExecStart={racine}/current/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port {port} --workers 1

Restart=on-failure
RestartSec=5

# L'ordonnanceur vit dans le « lifespan » : il doit s'arrêter proprement, pas se faire tuer
# au milieu d'un envoi.
TimeoutStopSec=10

StandardOutput=journal
StandardError=journal

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={racine}

[Install]
WantedBy=multi-user.target
"""


def demander(question, defaut):
    reponse = input("  {} {} ".format(paint("?", SIGNAL), question + dim(" [{}]".format(defaut))))
    return reponse.strip() or defaut


def commande_migrate_layout(racine_demandee):
    """Fabrique la structure du §2, y compris depuis une installation à plat."""
    etape("Deployment layout")
    racine = deviner_racine(racine_demandee)
    if racine is None:
        racine = Path(demander("Installation root?", "/opt/metric")).expanduser().resolve()

    config_existante = charger_config(str(racine), obligatoire=False)
    utilisateur = demander(
        "Service user?", config_existante.utilisateur or os.environ.get("USER", "metric")
    )
    npm = demander("Does NPM serve the frontend from this machine? (yes/no)", "yes")
    depot = demander("GitHub repository?", config_existante.depot or DEPOT)
    # « o » couvre « oui » autant que « yes » ne couvrirait pas « oui » : la question est
    # posée en anglais, la réponse peut venir d'un opérateur francophone.
    config = Config(racine, utilisateur, npm.lower()[:1] in ("o", "y", "1"), depot)

    say()
    champ("root", str(racine))
    champ("user", utilisateur)
    champ("npm local", "yes" if config.npm_local else "no")
    champ("repo", depot)

    for dossier in (config.releases, config.shared, config.backups):
        if not simule("mkdir -p " + str(dossier)):
            dossier.mkdir(parents=True, exist_ok=True)
    ok("releases/ shared/ backups/ ready")

    # Une installation à plat : backend/ et frontend/ directement sous la racine.
    a_plat = (racine / "backend").is_dir() and (racine / "frontend").is_dir()
    if a_plat:
        nom = time.strftime("%Y-%m-%dT%H-%M-%S") + "-migration"
        cible = config.releases / nom
        say()
        warn("Flat installation detected")
        say(dim("      It will be MOVED (not copied) into releases/" + nom))
        if not simule("move the flat installation to " + str(cible)):
            cible.mkdir(parents=True, exist_ok=True)
            for element in list(racine.iterdir()):
                if element.name in ("releases", "shared", "backups", "current"):
                    continue
                shutil.move(str(element), str(cible / element.name))
            env_deplace = cible / ".env"
            if env_deplace.exists() and not env_deplace.is_symlink():
                shutil.move(str(env_deplace), str(config.env))
                os.chmod(str(config.env), 0o600)
                os.symlink(str(config.env), str(env_deplace))
            basculer(config, cible)
        ok("Migrated, current → " + nom)

    if not config.env.exists():
        warn("shared/.env is missing — copy .env.example and fill it in")
        say(dim("      At minimum: APP_ENV=production, NEXTCLOUD_*, AUTH_*, JWT_SECRET,"))
        say(dim("      CORS_ORIGINS, TRUST_PROXY_HEADERS=true, VAPID_*, ICAL_SECRET"))

    if not simule("write " + str(config.fichier_conf)):
        config.fichier_conf.write_text(
            "# Écrit par « make update ARGS=migrate-layout ». Relu à chaque exécution.\n"
            "racine = {}\nutilisateur = {}\nnpm_local = {}\ndepot = {}\n".format(
                racine, utilisateur, "oui" if config.npm_local else "non", depot
            ),
            encoding="utf-8",
        )
    ok("shared/deploy.conf written")

    unite = config.shared / (UNITE + ".service")
    if not simule("write " + str(unite)):
        unite.write_text(
            UNITE_SYSTEMD.format(racine=racine, utilisateur=utilisateur, port=PORT_API),
            encoding="utf-8",
        )
    ok("shared/{}.service written".format(UNITE))
    say()
    say(dim("      Install it once, as root:"))
    say("      sudo cp {} /etc/systemd/system/".format(unite))
    say("      sudo systemctl daemon-reload && sudo systemctl enable --now " + UNITE)
    say()
    say(dim("      Then point NPM at {}/current/frontend/dist, and /api at 127.0.0.1:{}".format(
        racine, PORT_API)))
    if config.npm_local:
        say(dim("      NPM in a container? Mount {} — NOT {}/current: mounting the".format(
            racine, racine)))
        say(dim("      symlink freezes its target when the container starts."))
    say()
    return 0


def main():
    analyseur = argparse.ArgumentParser(
        prog="update", description="Metric — deployment update tool."
    )
    analyseur.add_argument(
        "commande",
        nargs="?",
        default="check",
        choices=["check", "run", "rollback", "releases", "migrate-layout"],
    )
    analyseur.add_argument("cible", nargs="?", default="", help="rollback: release name")
    analyseur.add_argument("--ref", default=REF_PAR_DEFAUT, help="branch, tag or commit SHA")
    analyseur.add_argument("--racine", default="", help="installation root")
    analyseur.add_argument(
        "--dry-run", action="store_true", dest="simulation", help="print every step, execute none"
    )
    analyseur.add_argument(
        "--skip-check",
        action="store_true",
        dest="sauter_check",
        help="skip the test suite before switching (not recommended)",
    )
    analyseur.add_argument(
        "--force", action="store_true", help="reinstall even if the revision is already deployed"
    )
    arguments = analyseur.parse_args()

    global SIMULATION
    SIMULATION = arguments.simulation

    say()
    say("  {} {}".format(paint("Metric", BOLD + SIGNAL), dim("· deployment update")))

    try:
        if arguments.commande == "migrate-layout":
            return commande_migrate_layout(arguments.racine)

        config = charger_config(arguments.racine)
        if arguments.commande == "check":
            return commande_check(config, arguments.ref)
        if arguments.commande == "releases":
            return commande_releases(config)
        if arguments.commande == "rollback":
            return commande_rollback(config, arguments.cible)
        return commande_run(config, arguments.ref, arguments.sauter_check, arguments.force)
    except Arret as erreur:
        say()
        if str(erreur):
            fail(str(erreur))
            say()
        return 1
    except KeyboardInterrupt:
        say()
        warn("Interrupted")
        say()
        return 130


if __name__ == "__main__":
    sys.exit(main())
