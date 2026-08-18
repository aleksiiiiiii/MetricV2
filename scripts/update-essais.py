#!/usr/bin/env python3
"""Éprouve `scripts/update.py` — les essais que `make check` ne peut pas porter.

    python3 scripts/update-essais.py

Hors de `make check` délibérément : ces essais montent de fausses racines d'installation,
téléchargent, suppriment des dossiers et basculent des liens. Ils n'ont rien à faire dans
une batterie qui doit être verte avant chaque commit — et `pyproject.toml` limite de toute
façon la collecte pytest à `backend/tests`.

Ce qu'ils prouvent, et qu'aucun test unitaire du dépôt ne touche :

* une archive **coupée en plein milieu** ne produit pas de release à moitié posée, et
  « current » ne bouge pas — c'est le seul essai qui prouve que la bascule par lien sert
  à quelque chose ;
* un Python trop vieux est refusé **avant** que la sauvegarde ne soit écrite ;
* une sauvegarde dont la relecture diverge **arrête tout** ;
* la santé qui ne revient pas déclenche un **retour arrière automatique** ;
* l'élagage ne supprime jamais « current » ni la précédente ;
* `--dry-run` ne touche à rien.

Ils tournent sur des racines jetables dans un dossier temporaire, jamais sur une
installation réelle. Aucun ne touche à Nextcloud.
"""

import gzip
import importlib.util
import io
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

RACINE_DEPOT = Path(__file__).resolve().parent.parent
SCRATCH = Path(tempfile.mkdtemp(prefix="metric-update-essais-"))

spec = importlib.util.spec_from_file_location("update", RACINE_DEPOT / "scripts/update.py")
up = importlib.util.module_from_spec(spec)
spec.loader.exec_module(up)

#: Les fonctions que les essais remplacent par des bouchons. Chaque essai repart des
#: vraies : sans ça, un bouchon posé par l'essai 4 fait passer l'essai 7 pour de mauvaises
#: raisons — c'est arrivé en écrivant ce fichier, et ça n'a pas donné une erreur mais
#: trois succès mensongers.
REMPLACABLES = (
    "verifier_prealables",
    "sauvegarder",
    "resoudre_sha",
    "telecharger",
    "preparer",
    "redemarrer",
    "sante",
    "verifier_sante",
)
ORIGINAUX = {nom: getattr(up, nom) for nom in REMPLACABLES}


def restaurer():
    for nom, fonction in ORIGINAUX.items():
        setattr(up, nom, fonction)
    up.SIMULATION = False
    up.PYTHON_MINIMAL = (3, 12)


resultats = []


def verdict(nom, condition, detail=""):
    resultats.append((nom, condition))
    marque = "  OK   " if condition else "  RATÉ "
    print(marque + nom + ((" — " + detail) if detail else ""))


def monter(nom):
    base = SCRATCH / nom
    if base.exists():
        shutil.rmtree(base)
    for dossier in ("releases", "shared", "backups"):
        (base / dossier).mkdir(parents=True)
    (base / "shared/.env").write_text(
        "APP_ENV=production\nVAPID_PRIVATE_KEY=x\nICAL_SECRET=y\n"
        "AUTH_PASSWORD_HASH=$argon2id$v=19$m=65536,t=3,p=4$sel$hash\nNEXTCLOUD_PASSWORD=z\n"
    )
    os.chmod(base / "shared/.env", 0o600)
    return up.Config(base, "metric", True, up.DEPOT)


def fausse_release(config, nom, sha="0000000"):
    release = config.releases / nom
    (release / "frontend/dist").mkdir(parents=True)
    (release / "Makefile").write_text("all:\n")
    (release / "frontend/dist/index.html").write_text("<html></html>")
    (release / "RELEASE").write_text("ref=main\nsha={}\nhorodatage=x\n".format(sha))
    return release

restaurer()
print("\n=== 1. L'archive cassée au milieu ===")
c = monter("essai-archive")
avant = fausse_release(c, "2026-08-01T00-00-00-aaaaaaa"); up.basculer(c, avant)
bonne = gzip.compress(b"")  # on fabrique une vraie archive puis on la coupe
tampon = io.BytesIO()
with tarfile.open(fileobj=tampon, mode="w:gz") as t:
    info = tarfile.TarInfo("MetricV2-main/Makefile"); charge = b"all:\n" * 5000
    info.size = len(charge); t.addfile(info, io.BytesIO(charge))
complete = tampon.getvalue()
tronquee = complete[: len(complete) // 2]          # coupée en plein milieu

class FausseReponse:
    def __init__(self, data): self.data = data
    def read(self): return self.data
    def __enter__(self): return self
    def __exit__(self, *a): return False

up.urllib.request.urlopen = lambda *a, **k: FausseReponse(tronquee)
cible = c.releases / "2026-08-02T00-00-00-bbbbbbb"
try:
    up.telecharger(c, "main", None, cible); leve = False
except up.Arret as e: leve = True; msg = str(e)
verdict("l'archive tronquée est refusée", leve, msg if leve else "aucune exception")
verdict("aucune release à demi extraite", not cible.exists() and not (c.releases / (".tmp-" + cible.name)).exists())
verdict("« current » n'a pas bougé", up.cible_actuelle(c).name == avant.name)
verdict("l'application en place est intacte", (avant / "frontend/dist/index.html").exists())

restaurer()
print("\n=== 2. Python trop vieux : le refus arrive AVANT que rien ne bouge ===")
c = monter("essai-python")
fausse_release(c, "2026-08-01T00-00-00-aaaaaaa")
up.PYTHON_MINIMAL = (3, 99)                        # simule un Debian 12 (3.11)
try:
    up.verifier_prealables(c); leve = False
except up.Arret: leve = True
up.PYTHON_MINIMAL = (3, 12)
verdict("les préalables refusent", leve)
verdict("aucune sauvegarde écrite", not any(c.backups.iterdir()))
verdict("aucune release téléchargée", len(list(c.releases.iterdir())) == 1)

restaurer()
print("\n=== 3. La sauvegarde est relue, et un écart l'arrête ===")
c = monter("essai-sauvegarde")
archive = up.sauvegarder(c)
verdict("archive écrite", archive.exists())
verdict("archive en 600", (archive.stat().st_mode & 0o777) == 0o600)
with tarfile.open(archive, "r:gz") as t: noms = t.getnames()
verdict(".env est dedans", ".env" in noms, str(noms))
vraie_ouverture = tarfile.open
def ouverture_menteuse(*a, **k):
    flux = vraie_ouverture(*a, **k)
    if k.get("mode", "").startswith("r") or (len(a) > 1 and str(a[1]).startswith("r")):
        vrai_extract = flux.extractfile
        flux.extractfile = lambda m: io.BytesIO(b"contenu different")
    return flux
tarfile.open = ouverture_menteuse
try:
    up.sauvegarder(c); leve = False
except up.Arret: leve = True
tarfile.open = vraie_ouverture
verdict("une relecture qui diverge arrête tout", leve)

restaurer()
print("\n=== 4. Retour arrière ===")
c = monter("essai-rollback")
r1 = fausse_release(c, "2026-08-01T00-00-00-aaaaaaa", "aaaaaaa")
r2 = fausse_release(c, "2026-08-02T00-00-00-bbbbbbb", "bbbbbbb")
up.basculer(c, r2)
verdict("current sur la neuve", up.cible_actuelle(c).name == r2.name)
up.redemarrer = lambda config: True
up.verifier_sante = lambda config: True
code = up.commande_rollback(c, "")
verdict("rollback rend 0", code == 0)
verdict("current est revenu sur la précédente", up.cible_actuelle(c).name == r1.name)

restaurer()
print("\n=== 5. Élagage : jamais current, jamais la précédente ===")
c = monter("essai-elagage")
noms = ["2026-08-0{}T00-00-00-{}".format(i, "c" * 7) for i in range(1, 7)]
for n in noms: fausse_release(c, n)
up.basculer(c, c.releases / noms[3])               # current = la 4e, pas la dernière
up.elaguer(c)
restantes = sorted(p.name for p in c.releases.iterdir())
verdict("trois releases gardées", len(restantes) == 3, str(restantes))
verdict("current survit", noms[3] in restantes)
verdict("la plus récente survit", noms[5] in restantes)
verdict("current pointe toujours quelque part", (c.racine / "current").resolve().is_dir())

restaurer()
print("\n=== 6. La bascule est un remplacement atomique ===")
c = monter("essai-atomique")
r1 = fausse_release(c, "2026-08-01T00-00-00-aaaaaaa")
r2 = fausse_release(c, "2026-08-02T00-00-00-bbbbbbb")
up.basculer(c, r1); up.basculer(c, r2)
verdict("current est un lien", (c.racine / "current").is_symlink())
verdict("current mène à la bonne release", up.cible_actuelle(c).name == r2.name)
verdict("aucun lien temporaire oublié", not list(c.racine.glob(".current.*")))
(c.racine / "current").unlink(); (c.racine / "current").mkdir()
try:
    up.basculer(c, r1); leve = False
except up.Arret as e: leve = True; msg = str(e)
verdict("un « current » en vrai dossier est refusé, pas écrasé", leve, msg if leve else "")


restaurer()
print("\n=== 7. La santé ne revient pas : retour arrière AUTOMATIQUE ===")
c = monter("essai-sante")
ancienne = fausse_release(c, "2026-08-01T00-00-00-aaaaaaa", "a" * 40)
up.basculer(c, ancienne)
neuve_nom = {}
up.verifier_prealables = lambda config: None
up.sauvegarder = lambda config: Path("/dev/null")
up.resoudre_sha = lambda config, ref, jeton: "b" * 40
def faux_telechargement(config, ref, jeton, destination):
    neuve_nom["n"] = destination.name
    (destination / "frontend/dist").mkdir(parents=True)
    (destination / "Makefile").write_text("all:\n")
    (destination / "frontend/dist/index.html").write_text("<html>")
up.telecharger = faux_telechargement
up.preparer = lambda config, release, sauter: None
redemarrages = []
up.redemarrer = lambda config: redemarrages.append(1) or True
up.sante = lambda delai=30: (False, {})            # l'API ne revient JAMAIS
code = up.commande_run(c, "main", True, False)
verdict("run rend un code d'échec", code == 1)
verdict("current est revenu sur l'ancienne", up.cible_actuelle(c).name == ancienne.name)
verdict("la release fautive reste sur le disque", (c.releases / neuve_nom["n"]).is_dir())
verdict("l'API a bien été redémarrée deux fois", len(redemarrages) == 2, str(len(redemarrages)))

restaurer()
print("\n=== 8. --dry-run ne touche à rien ===")
c = monter("essai-simulation")
ancienne = fausse_release(c, "2026-08-01T00-00-00-aaaaaaa", "a" * 40)
up.basculer(c, ancienne)
empreinte_avant = sorted(p.name for p in c.releases.iterdir())
up.SIMULATION = True
up.verifier_prealables = lambda config: None
up.resoudre_sha = lambda config, ref, jeton: "b" * 40
import importlib
spec2 = importlib.util.spec_from_file_location("update2", RACINE_DEPOT / "scripts/update.py")
up2 = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(up2)
up2.SIMULATION = True
up2.resoudre_sha = lambda config, ref, jeton: "b" * 40
c2 = up2.Config(c.racine, "metric", True, up2.DEPOT)
code = up2.commande_run(c2, "main", False, False)
verdict("la simulation rend 0", code == 0)
verdict("aucune release créée", sorted(p.name for p in c.releases.iterdir()) == empreinte_avant)
verdict("aucune sauvegarde écrite", not any(c.backups.iterdir()))
verdict("current n'a pas bougé", up2.cible_actuelle(c2).name == ancienne.name)


restaurer()
print("\n=== 9. Ni root ni sudo : le refus est lisible, pas une trace Python ===")
c = monter("essai-sans-sudo")
ancienne = fausse_release(c, "2026-08-01T00-00-00-aaaaaaa", "a" * 40)
up.basculer(c, ancienne)

vrai_which, vrai_geteuid = shutil.which, os.geteuid
shutil.which = lambda nom: None if nom == "sudo" else vrai_which(nom)
os.geteuid = lambda: 1000                      # ni root, ni sudo — la Debian minimale
up.systemd_present = lambda: True
verdict("commande_systemctl rend None", up.commande_systemctl("restart", "x") is None)
try:
    up.redemarrer(c)
    leve = False
except up.Arret:
    leve = True
except Exception as erreur:                    # noqa: BLE001 - c'est précisément le point
    leve = False
    verdict("aucune exception non rattrapée", False, type(erreur).__name__)
verdict("redemarrer s'arrête proprement", leve)

os.geteuid = lambda: 0                         # root : plus de sudo, et ça doit marcher
verdict("en root, pas de sudo dans la commande",
        up.commande_systemctl("restart", "x") == ["systemctl", "restart", "x"])
os.geteuid = lambda: 1000
shutil.which = lambda nom: "/usr/bin/sudo" if nom == "sudo" else vrai_which(nom)
verdict("non-root avec sudo, sudo est préfixé",
        up.commande_systemctl("restart", "x") == ["sudo", "systemctl", "restart", "x"])

# Une commande absente devient un arrêt annoncé, pas un FileNotFoundError.
shutil.which, os.geteuid = vrai_which, vrai_geteuid
try:
    up.executer(["cette-commande-nexiste-pas-du-tout"])
    leve = False
except up.Arret:
    leve = True
verdict("une commande introuvable devient un Arret", leve)

rates = [nom for nom, reussi in resultats if not reussi]
print()
print("=" * 62)
print("  {} essais, {} ratés".format(len(resultats), len(rates)))
for nom in rates:
    print("  RATÉ : " + nom)
shutil.rmtree(SCRATCH, ignore_errors=True)
sys.exit(1 if rates else 0)
