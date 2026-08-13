#!/usr/bin/env python3
"""Console de développement de Metric.

    make console

Pilote les deux serveurs — l'API et le frontend — sans quitter le terminal :
démarrage, arrêt, redémarrage, état, journaux. Écrite en Python de la bibliothèque
standard uniquement : elle doit fonctionner avant même que le venv du backend existe,
puisque c'est elle qui sert à diagnostiquer une installation qui ne démarre pas.

Trois choix expliquent la structure :

* **Les processus sont détachés** (`start_new_session`). Un Ctrl-C dans la console ne
  doit pas tuer les serveurs, et fermer la console encore moins. C'est l'inverse de
  `scripts/dev.sh`, qui lie volontairement les deux.
* **Le port est choisi, pas subi.** Les ports 5173 et 5174 traînent souvent occupés par
  d'autres projets ; la console prend le premier libre et s'en souvient. Le proxy de
  Vite suit via `METRIC_API_PORT`.
* **L'état vit sur disque** (`.metric/state.json`). Fermer et rouvrir la console
  retrouve les serveurs lancés à la session précédente.

── Quatre services, et pourquoi deux ne démarrent pas tout seuls ─────────────

`api` et `web` sont ce qu'il faut pour coder, et « start » les lance tous les deux.

`preview` et `tunnel` servent une autre question — **est-ce que ça marche sur un vrai
téléphone** — et ils ne s'allument que si on le demande :

* `preview` sert le **build de production**. C'est le seul endroit où le service worker
  existe (`lib/pwa.ts` ne l'enregistre qu'en production), donc le seul où la PWA et les
  rappels s'éprouvent. Il peut servir un build vieux d'une semaine : l'allumer sans le
  vouloir induirait en erreur.
* `tunnel` expose ce build **en HTTPS**, ce qu'un service worker et Web Push exigent —
  `localhost` est un contexte sécurisé, `192.168.1.x` non. Il ouvre l'application sur
  l'Internet public le temps d'une vérification : ça se demande.

C'est ce couple qui remplace la pile conteneurisée pour ce lot. Il ne la remplace **pas**
en production : le HTTPS durable viendra d'un reverse-proxy — Nginx Proxy Manager — et
« proxy » dit ce que l'application lui demande en échange.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / ".metric"
STATE_FILE = RUN_DIR / "state.json"

# ── Couleurs, reprises de la charte ───────────────────
# Approximations ANSI 24 bits des quatre signaux : cyan ardoise, sauge, argile, mauve.
SIGNAL = "\033[38;2;127;168;180m"
EFFORT = "\033[38;2;138;163;123m"
LOAD = "\033[38;2;195;155;110m"
RECOVER = "\033[38;2;169;116;138m"
INK_LOW = "\033[38;2;92;104;116m"
BOLD = "\033[1m"
RESET = "\033[0m"

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def paint(text: str, color: str) -> str:
    return f"{color}{text}{RESET}" if USE_COLOR else text


def say(text: str = "") -> None:
    print(text)


def ok(text: str) -> None:
    say(f"  {paint('✓', EFFORT)} {text}")


def warn(text: str) -> None:
    say(f"  {paint('!', LOAD)} {text}")


def fail(text: str) -> None:
    say(f"  {paint('✗', RECOVER)} {text}")


def dim(text: str) -> str:
    return paint(text, INK_LOW)


# ── Services ──────────────────────────────────────────


@dataclass(frozen=True)
class Service:
    key: str
    label: str
    cwd: Path
    #: `{port}` est remplacé au lancement. Zéro pour un service sans port à lui.
    default_port: int
    command: tuple[str, ...]
    #: Chemin interrogé pour savoir si le service répond vraiment. Vide quand il n'y a
    #: rien à interroger — un tunnel n'expose pas de santé locale.
    health_path: str
    #: Vite n'écoute que sur ::1 ; l'API sur 127.0.0.1.
    host: str
    #: Service qui doit tourner avant celui-ci, et dont il prend le port.
    needs: str = ""
    #: Motif qui repère l'adresse publique dans le journal du service (le tunnel).
    url_pattern: str = ""

    @property
    def log_file(self) -> Path:
        return RUN_DIR / f"{self.key}.log"

    @property
    def own_port(self) -> bool:
        return self.default_port > 0

    def build_command(self, port: int) -> list[str]:
        return [part.format(port=port) for part in self.command]


API = Service(
    key="api",
    label="API",
    cwd=ROOT / "backend",
    default_port=8000,
    command=(".venv/bin/uvicorn", "app.main:app", "--reload", "--port", "{port}"),
    health_path="/api/health",
    host="127.0.0.1",
)

WEB = Service(
    key="web",
    label="Frontend",
    cwd=ROOT / "frontend",
    default_port=5173,
    command=("npm", "run", "dev", "--silent", "--", "--port", "{port}", "--strictPort"),
    health_path="/",
    host="localhost",
)

#: Le build de production, servi tel qu'il partira.
#:
#: C'est le **seul endroit où le service worker existe** : `lib/pwa.ts` ne l'enregistre
#: qu'en production, sinon il s'interposerait sur `/assets` et servirait des fichiers
#: périmés pendant qu'on code. Éprouver la PWA, l'installation et les rappels demande donc
#: de passer par ici, jamais par `web`.
PREVIEW = Service(
    key="preview",
    label="Production",
    cwd=ROOT / "frontend",
    default_port=4173,
    command=("npm", "run", "preview", "--silent", "--", "--port", "{port}", "--strictPort"),
    health_path="/",
    host="localhost",
)

#: Le tunnel HTTPS, et c'est la pièce qui remplace Docker dans ce flux.
#:
#: Un service worker et Web Push exigent un **contexte sécurisé** : `localhost` en est un,
#: `192.168.1.x` non. Sur un vrai iPhone, il n'y a donc pas d'autre chemin que le HTTPS —
#: et le monter à la main demanderait un certificat, un reverse-proxy et un nom, c'est-à-
#: dire `L17-01` tout entier.
#:
#: Un tunnel éphémère rend le même service pour une vérification, sans rien déployer :
#: aucun port ouvert sur le réseau, aucune configuration à défaire ensuite, et il meurt
#: avec le processus. **Ce n'est pas un déploiement**, et il n'a pas à le devenir.
TUNNEL = Service(
    key="tunnel",
    label="Tunnel HTTPS",
    cwd=ROOT,
    default_port=0,
    command=("cloudflared", "tunnel", "--url", "http://localhost:{port}"),
    health_path="",
    host="localhost",
    needs="preview",
    url_pattern=r"https://[a-z0-9-]+\.trycloudflare\.com",
)

SERVICES = {s.key: s for s in (API, WEB, PREVIEW, TUNNEL)}

#: Ce que « start » sans argument démarre : le nécessaire pour coder.
#:
#: `preview` et `tunnel` en sont **volontairement absents** : le premier sert un build qui
#: peut dater de la semaine dernière, le second expose l'application sur l'Internet
#: public. Ni l'un ni l'autre ne doit s'allumer parce qu'on a tapé « start ».
DEFAULT_SERVICES = (API, WEB)


# ── État persistant ───────────────────────────────────


def read_state() -> dict[str, dict[str, int]]:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(state: dict[str, dict[str, int]]) -> None:
    RUN_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # existe, appartient à quelqu'un d'autre
    return True


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return True
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe6:
        probe6.settimeout(0.2)
        return probe6.connect_ex(("::1", port)) == 0


def free_port(preferred: int) -> int:
    """Premier port libre à partir du préféré.

    Les ports de développement traînent souvent occupés par un autre projet : subir
    l'échec et demander à l'utilisateur de trouver un port lui-même serait le laisser
    faire le travail de la console.
    """
    for candidate in range(preferred, preferred + 40):
        if not port_busy(candidate):
            return candidate
    raise RuntimeError(f"aucun port libre entre {preferred} et {preferred + 40}")


def running(service: Service) -> tuple[int, int] | None:
    """`(pid, port)` si le service tourne, sinon `None`. Purge les entrées mortes."""
    state = read_state()
    entry = state.get(service.key)
    if not entry:
        return None

    pid, port = entry.get("pid", 0), entry.get("port", 0)
    if pid and alive(pid):
        return pid, port

    state.pop(service.key, None)
    write_state(state)
    return None


def url_of(service: Service, port: int) -> str:
    if not service.own_port:
        return public_url(service) or "(adresse en attente)"
    return f"http://{service.host}:{port}"


def public_url(service: Service) -> str:
    """Adresse publique annoncée par un service dans son propre journal.

    Un tunnel éphémère choisit son nom de domaine au démarrage et n'a aucun moyen de nous
    le dire autrement : il l'écrit sur sa sortie. Le lire ici évite d'avoir à ouvrir le
    journal soi-même pour trouver l'URL à taper sur le téléphone.
    """
    if not service.url_pattern or not service.log_file.exists():
        return ""
    found = re.findall(service.url_pattern, service.log_file.read_text(errors="replace"))
    return found[-1] if found else ""


def responds(service: Service, port: int, timeout: float = 1.0) -> bool:
    # Un service sans santé à interroger — le tunnel — est jugé sur le fait qu'il a
    # annoncé son adresse. C'est la seule chose observable, et c'est la bonne : un tunnel
    # qui n'a pas d'URL ne sert à rien même s'il tourne.
    if not service.health_path:
        return bool(public_url(service))
    try:
        with urllib.request.urlopen(  # noqa: S310 - hôte local, construit par nous
            f"http://{service.host}:{port}{service.health_path}", timeout=timeout
        ) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


# ── Actions ───────────────────────────────────────────


def prerequisites(service: Service) -> str | None:
    """Message d'erreur si le service ne peut pas démarrer, sinon `None`."""
    if service is API and not (ROOT / "backend/.venv/bin/uvicorn").exists():
        return "environnement backend absent — lance « make setup »"
    if service in (WEB, PREVIEW) and not (ROOT / "frontend/node_modules").is_dir():
        return "dépendances frontend absentes — lance « make setup »"
    if service in (WEB, PREVIEW) and shutil.which("npm") is None:
        return "npm introuvable dans le PATH"
    if service is PREVIEW and not (ROOT / "frontend/dist/index.html").exists():
        return "aucun build — lance « build » d'abord"
    if service is TUNNEL and shutil.which("cloudflared") is None:
        return "cloudflared introuvable — « brew install cloudflared »"
    if service.needs and not running(SERVICES[service.needs]):
        return f"« {service.needs} » doit tourner d'abord"
    return None


def start(service: Service, *, quiet: bool = False, lan: bool = False) -> bool:
    existing = running(service)
    if existing:
        pid, port = existing
        if not quiet:
            warn(f"{service.label} tourne déjà — PID {pid}, {url_of(service, port)}")
        return True

    problem = prerequisites(service)
    if problem:
        fail(f"{service.label} : {problem}")
        return False

    if service.needs:
        # Le tunnel n'a pas de port à lui : il relaie celui du service qu'il expose.
        upstream = running(SERVICES[service.needs])
        assert upstream is not None  # garanti par `prerequisites`
        port = upstream[1]
    else:
        port = free_port(service.default_port)
        if port != service.default_port:
            warn(f"{service.label} : port {service.default_port} occupé, bascule sur {port}")

    command = service.build_command(port)
    if lan and service in (API, PREVIEW):
        # Écoute sur toutes les interfaces, pour qu'un reverse-proxy hébergé ailleurs —
        # Nginx Proxy Manager sur un NAS, par exemple — puisse joindre le service.
        command += ["--host", "0.0.0.0"]

    RUN_DIR.mkdir(exist_ok=True)
    log = service.log_file.open("wb")

    environment = dict(os.environ)
    if service in (WEB, PREVIEW):
        # Le proxy de Vite doit suivre le port réellement pris par l'API — en
        # développement comme en `preview`, qui relaie `/api` de la même façon.
        api = running(API)
        environment["METRIC_API_PORT"] = str(api[1] if api else API.default_port)

    process = subprocess.Popen(  # noqa: S603 - commande construite par nous
        command,
        cwd=service.cwd,
        stdout=log,
        stderr=subprocess.STDOUT,
        env=environment,
        # Session détachée : un Ctrl-C dans la console ne doit pas tuer les serveurs.
        start_new_session=True,
    )

    state = read_state()
    state[service.key] = {"pid": process.pid, "port": port, "lan": int(lan)}
    write_state(state)

    where = f"sur le port {port}" if service.own_port else f"vers le port {port}"
    say(f"  {dim('…')} {service.label} démarre {where}")
    # Un tunnel négocie son domaine auprès de Cloudflare : c'est plus lent qu'un serveur
    # local, et l'attente est normale.
    attempts = 300 if service is TUNNEL else 150
    for _ in range(attempts):
        if process.poll() is not None:
            fail(f"{service.label} s'est arrêté immédiatement — « logs {service.key} »")
            state.pop(service.key, None)
            write_state(state)
            return False
        if responds(service, port):
            ok(f"{service.label} · {paint(url_of(service, port), SIGNAL)}")
            if service is TUNNEL:
                say(f"    {dim('à ouvrir sur le téléphone, puis « Sur l’écran d’accueil »')}")
            if lan:
                warn("exposé sur le réseau — voir « proxy » pour ce que ça demande")
            return True
        time.sleep(0.2)

    warn(f"{service.label} : lancé (PID {process.pid}) mais ne répond pas encore")
    return True


def stop(service: Service, *, quiet: bool = False) -> bool:
    current = running(service)
    if not current:
        if not quiet:
            say(f"  {dim('·')} {service.label} est déjà arrêté")
        return True

    pid, _ = current
    try:
        # Le groupe entier : uvicorn --reload et npm lancent des enfants qui
        # survivraient à un signal envoyé au seul parent.
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    for _ in range(50):
        if not alive(pid):
            break
        time.sleep(0.1)
    else:
        warn(f"{service.label} ne répond pas au signal, arrêt forcé")
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    state = read_state()
    state.pop(service.key, None)
    write_state(state)
    ok(f"{service.label} arrêté")
    return True


def status() -> None:
    say()
    state = read_state()
    for service in SERVICES.values():
        current = running(service)
        if not current:
            occupant = ""
            if service.own_port and port_busy(service.default_port):
                occupant = dim(f"  (port {service.default_port} occupé par un autre processus)")
            say(f"  {paint('○', INK_LOW)} {service.label:<12} arrêté{occupant}")
            continue

        pid, port = current
        healthy = responds(service, port, timeout=0.5)
        mark = paint("●", EFFORT) if healthy else paint("●", LOAD)
        state_text = "en ligne" if healthy else "démarre…"
        exposed = dim(" · réseau") if state.get(service.key, {}).get("lan") else ""
        say(
            f"  {mark} {service.label:<12} {state_text:<10} "
            f"{paint(url_of(service, port), SIGNAL)}{exposed}  {dim(f'PID {pid}')}"
        )

    api = running(API)
    if api and responds(API, api[1], timeout=0.5):
        say()
        say(f"  {dim('doc API')}  {paint(url_of(API, api[1]) + '/api/docs', SIGNAL)}")
        try:
            with urllib.request.urlopen(  # noqa: S310 - hôte local
                url_of(API, api[1]) + "/api/health", timeout=1
            ) as response:
                health = json.load(response)
            flags = [
                ("Nextcloud", health.get("storage_configured")),
                ("auth", health.get("auth_configured")),
                ("IA", health.get("ai_enabled")),
            ]
            rendered = "  ".join(
                paint(f"{name} ✓", EFFORT) if value else paint(f"{name} ✗", LOAD)
                for name, value in flags
            )
            say(f"  {dim('config ')}  {rendered}")
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            pass
    say()


def show_logs(key: str, lines: int, follow: bool) -> None:
    targets = list(SERVICES.values()) if key == "all" else [SERVICES[key]]

    for service in targets:
        if not service.log_file.exists():
            say(f"  {dim(f'aucun journal pour {service.label}')}")
            continue

        say()
        say(f"  {paint(f'── {service.label} ' + '─' * 46, INK_LOW)}")
        content = service.log_file.read_text(errors="replace").splitlines()
        for line in content[-lines:]:
            say(f"  {line}")

    if not follow:
        say()
        return

    say()
    say(dim("  suivi en direct — Ctrl-C pour revenir à la console"))
    handles = [(s, s.log_file.open()) for s in targets if s.log_file.exists()]
    for _, handle in handles:
        handle.seek(0, os.SEEK_END)
    try:
        while True:
            idle = True
            for service, handle in handles:
                for line in handle:
                    prefix = f"{service.key:>4} " if len(handles) > 1 else ""
                    say(f"  {dim(prefix)}{line.rstrip()}")
                    idle = False
            if idle:
                time.sleep(0.25)
    except KeyboardInterrupt:
        say()
    finally:
        for _, handle in handles:
            handle.close()


def run_make(target: str) -> None:
    """Relaie une cible du Makefile, sortie en direct."""
    say()
    subprocess.run(["make", target], cwd=ROOT, check=False)  # noqa: S603, S607
    say()


def issue_token() -> str | None:
    """Un jeton de session, émis localement pour interroger l'API.

    Le même geste que celui de `CLAUDE.md` : on ne se connecte pas, on **signe** un jeton
    avec le secret que le serveur utilise déjà. C'est ce qui permet à la console de lire
    l'état sans demander de mot de passe ni en garder un.
    """
    script = (
        "from app.config import get_settings;"
        "from app.core.security import TokenIssuer;"
        "s = get_settings();"
        "print(TokenIssuer(s).issue(s.auth_username).access_token)"
    )
    try:
        result = subprocess.run(  # noqa: S603 - commande construite par nous
            [str(ROOT / "backend/.venv/bin/python"), "-c", script],
            cwd=ROOT / "backend",
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def show_push() -> None:
    """État des rappels : clés, appareils abonnés, créneaux (`NOT-01` → `NOT-03`).

    C'est la seule vue qui dise si les rappels **partiront vraiment** : trois choses
    doivent être vraies en même temps, et chacune se règle ailleurs — une paire de clés
    dans `.env`, au moins un appareil abonné depuis lui-même, et un créneau réglé dans
    `/reglages`. Les regarder séparément est ce qui fait chercher longtemps.
    """
    say()
    api = running(API)
    if not api or not responds(API, api[1], timeout=1):
        fail("l'API ne répond pas — « start api »")
        say()
        return

    token = issue_token()
    if not token:
        fail("jeton impossible à émettre — AUTH_USERNAME et JWT_SECRET sont-ils réglés ?")
        say()
        return

    request = urllib.request.Request(  # noqa: S310 - hôte local
        f"{url_of(API, api[1])}/api/notifications",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            view = json.load(response)
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as error:
        fail(f"lecture impossible : {error}")
        say()
        return

    push = view.get("push", {})
    configured = bool(push.get("configured"))
    mark = paint("✓", EFFORT) if configured else paint("✗", LOAD)
    say(f"  {mark} clés VAPID          {dim('configurées' if configured else 'absentes — « vapid »')}")

    devices = view.get("devices", [])
    mark = paint("✓", EFFORT) if devices else paint("✗", LOAD)
    say(f"  {mark} appareils abonnés   {dim(str(len(devices)) + ' — abonnement depuis /reglages')}")
    for device in devices:
        since = device.get("created") or "date inconnue"
        say(f"      {dim('·')} {device.get('label', 'Appareil')}  {dim('…' + device.get('hint', ''))}  {dim(since)}")

    reminders = view.get("reminders", {})
    labels = {
        "supplements": "Suppléments",
        "hydration": "Hydratation",
        "meals": "Repas",
        "workout": "Séance",
    }
    active = [k for k, v in reminders.items() if v]
    mark = paint("✓", EFFORT) if active else paint("✗", LOAD)
    say(f"  {mark} créneaux réglés     {dim(str(len(active)) + ' sur 4')}")
    for key, label in labels.items():
        slot = reminders.get(key)
        value = paint(slot, SIGNAL) if slot else dim("éteint")
        say(f"      {dim('·')} {label:<12} {value}")

    say()
    if not configured:
        warn("aucun rappel ne partira : il manque la paire de clés")
    elif not devices:
        warn("aucun rappel ne partira : aucun appareil n'est abonné")
    elif not active:
        warn("aucun rappel ne partira : aucun créneau n'est réglé")
    else:
        ok("les trois conditions sont réunies")
        say(dim("    l'ordonnanceur vit dans l'API : le redémarrer le relance"))
    say()


def show_proxy() -> None:
    """Ce qu'un reverse-proxy — Nginx Proxy Manager — demande côté application.

    Rien de ce qui suit n'est de la configuration de proxy : c'est ce que **l'application**
    doit savoir une fois qu'elle est derrière lui. Les trois points ont chacun un symptôme
    précis quand on les oublie, et aucun ne ressemble à sa cause.
    """
    values = read_env()
    say()
    say(f"  {paint('Derrière Nginx Proxy Manager', INK_LOW)}")
    say()
    say(f"  {dim('1.')} Deux hôtes à déclarer, tous deux vers cette machine :")
    say(f"       {dim('/')}      → {paint('Production', SIGNAL)} (le build, port 4173)")
    say(f"       {dim('/api')}   → {paint('API', SIGNAL)} (uvicorn, port 8000)")
    say(dim("       « start --lan » fait écouter les deux sur toutes les interfaces ;"))
    say(dim("       sans lui ils restent sur 127.0.0.1 et le proxy ne les voit pas."))
    say()

    trust = values.get("TRUST_PROXY_HEADERS", "").lower() in {"1", "true", "yes"}
    mark = paint("✓", EFFORT) if trust else paint("!", LOAD)
    say(f"  {dim('2.')} {mark} TRUST_PROXY_HEADERS")
    say(
        dim(
            "       Sans lui, l'anti-brute-force voit l'adresse du proxy et non celle de"
            "\n       l'appelant : cinq échecs bloquent alors tout le monde (`AUTH-04`)."
            "\n       Avec lui et sans proxy devant, l'en-tête est forgeable — d'où le défaut à faux."
        )
    )
    say()

    origins = values.get("CORS_ORIGINS", "")
    say(f"  {dim('3.')} CORS_ORIGINS  {dim(origins or '(vide)')}")
    say(
        dim(
            "       Doit porter l'adresse HTTPS publique. Le symptôme d'un oubli est un"
            "\n       écran qui charge indéfiniment, sans erreur visible."
        )
    )
    say()
    say(f"  {paint('Et ce que le proxy doit faire, lui', INK_LOW)}")
    say(dim("    · terminer le TLS — c'est la condition du service worker et de Web Push ;"))
    say(dim("    · transmettre X-Forwarded-For et X-Forwarded-Proto ;"))
    say(dim("    · ne pas mettre /api en cache. Une réponse mémorisée par le proxy est"))
    say(dim("      exactement ce que le service worker s'interdit : un chiffre d'hier."))
    say()


def read_env() -> dict[str, str]:
    """Contenu de `.env`, sous forme de dictionnaire. Vide s'il n'existe pas."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return {}
    values: dict[str, str] = {}
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip()
    return values


def show_env() -> None:
    """Quelles clés sont renseignées — jamais leur valeur."""
    say()
    if not (ROOT / ".env").exists():
        fail(".env absent — copie .env.example et renseigne-le")
        say()
        return

    values = read_env()

    groups = {
        "Stockage": ["NEXTCLOUD_URL", "NEXTCLOUD_USERNAME", "NEXTCLOUD_PASSWORD"],
        "Session": ["AUTH_USERNAME", "AUTH_PASSWORD_HASH", "JWT_SECRET"],
        "Rappels": ["VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT"],
        "Optionnel": ["OPENROUTER_API_KEY", "ICAL_SECRET"],
    }
    for group, names in groups.items():
        say(f"  {paint(group, INK_LOW)}")
        for name in names:
            filled = bool(values.get(name))
            mark = paint("✓", EFFORT) if filled else paint("✗", LOAD)
            detail = dim(f"{len(values[name])} caractères") if filled else dim("vide")
            say(f"    {mark} {name:<22} {detail}")
    say()

    missing = [n for n in groups["Session"] if not values.get(n)]
    if missing:
        warn("connexion impossible tant que ces clés sont vides — « hash »")
        say()


HELP = f"""
  {paint('Serveurs', INK_LOW)}
    start [api|web|preview|tunnel] [--lan]
                         démarre ; sans argument, api + web
    stop  [·]            arrête
    restart  ·  r        redémarre
    status  ·  s         état, URL et configuration

  {paint('Sur un vrai téléphone', INK_LOW)}
    build                build de production (le service worker n'existe QUE là)
    start preview        sert ce build sur :4173
    start tunnel         l'expose en HTTPS — la condition de la PWA et du push

  {paint('Journaux', INK_LOW)}
    logs [service|all] [-f] [-n N]
                         derniers messages ; -f suit en direct

  {paint('Outils', INK_LOW)}
    check                lint + types + tests des deux côtés
    test                 tests seuls
    push                 rappels : clés, appareils abonnés, créneaux (NOT-01→03)
    proxy                ce que Nginx Proxy Manager demande à l'application
    hash                 génère le hash de mot de passe (AUTH-08)
    vapid                génère la paire de clés Web Push (NOT-01)
    storage              diagnostique Nextcloud (STO-11)
    env                  quelles clés de .env sont renseignées

  {paint('Console', INK_LOW)}
    help  ·  h  ·  ?     cette aide
    quit  ·  q           quitter (les serveurs continuent de tourner)
"""


def dispatch(line: str) -> bool:
    """Exécute une commande. Rend `False` pour quitter la console."""
    parts = line.split()
    if not parts:
        return True

    command, args = parts[0].lower(), parts[1:]
    lan = "--lan" in args
    named = [a for a in args if not a.startswith("-")]

    def targets(*, default_all: bool) -> list[Service]:
        """Services visés. `start` sans argument ne démarre que le nécessaire ;
        `stop` sans argument arrête **tout**, y compris le tunnel."""
        if not named:
            return list(SERVICES.values()) if default_all else list(DEFAULT_SERVICES)
        if named[0] == "all":
            return list(SERVICES.values())
        if named[0] in SERVICES:
            return [SERVICES[named[0]]]
        fail(f"service inconnu : {named[0]} ({', '.join(SERVICES)} ou all)")
        return []

    match command:
        case "start":
            say()
            for service in targets(default_all=False):
                start(service, lan=lan)
            say()
        case "stop":
            say()
            # Ordre inverse des dépendances : le tunnel avant ce qu'il expose.
            for service in reversed(targets(default_all=True)):
                stop(service)
            say()
        case "restart" | "r":
            say()
            chosen = targets(default_all=False)
            for service in reversed(chosen):
                stop(service, quiet=True)
            for service in chosen:
                start(service, lan=lan)
            say()
        case "status" | "s" | "st":
            status()
        case "logs" | "l":
            key = args[0] if args and args[0] in {*SERVICES, "all"} else "all"
            follow = "-f" in args
            count = 40
            if "-n" in args:
                index = args.index("-n")
                if index + 1 < len(args) and args[index + 1].isdigit():
                    count = int(args[index + 1])
            show_logs(key, count, follow)
        case "check":
            run_make("check")
        case "test":
            run_make("test")
        case "build":
            run_make("build")
            # Le service `preview` sert le contenu de `dist/` : s'il tournait, il sert
            # encore l'ancien. Le dire vaut mieux que de laisser chercher pourquoi la
            # correction ne se voit pas.
            if running(PREVIEW):
                warn("« Production » sert encore le build précédent — « restart preview »")
                say()
        case "push":
            show_push()
        case "proxy":
            show_proxy()
        case "hash":
            run_make("hash-password")
        case "vapid":
            run_make("vapid-keys")
        case "storage":
            run_make("check-storage")
        case "env":
            show_env()
        case "help" | "h" | "?":
            say(HELP)
        case "quit" | "q" | "exit":
            return False
        case _:
            fail(f"commande inconnue : {command} — « help »")

    return True


COMMANDS = [
    "start", "stop", "restart", "status", "logs", "build", "check", "test",
    "push", "proxy", "hash", "vapid", "storage", "env", "help", "quit",
]


def setup_readline() -> None:
    """Historique et complétion, si le terminal les permet."""
    try:
        import readline
    except ImportError:  # pragma: no cover - Windows sans pyreadline
        return

    history = RUN_DIR / "history"
    RUN_DIR.mkdir(exist_ok=True)
    try:
        readline.read_history_file(history)
    except OSError:
        pass
    import atexit

    atexit.register(lambda: readline.write_history_file(history))

    def complete(text: str, index: int) -> str | None:
        buffer = readline.get_line_buffer().lstrip()
        pool = COMMANDS if " " not in buffer else [*SERVICES, "all", "--lan", "-f", "-n"]
        matches = [word for word in pool if word.startswith(text)]
        return matches[index] if index < len(matches) else None

    readline.set_completer(complete)
    readline.parse_and_bind("tab: complete")


def main() -> int:
    setup_readline()

    say()
    say(f"  {paint(BOLD + 'Metric', SIGNAL)} {dim('· console de développement')}")
    say(dim("  « help » pour les commandes, « start » pour lancer les deux serveurs"))

    # Un argument en ligne de commande s'exécute et rend la main : « make console -- status ».
    if len(sys.argv) > 1:
        dispatch(" ".join(sys.argv[1:]))
        return 0

    status()

    while True:
        try:
            line = input(f"{paint('metric', SIGNAL)}{dim(' ❯ ')}" if USE_COLOR else "metric > ")
        except (EOFError, KeyboardInterrupt):
            say()
            return 0
        if not dispatch(line):
            return 0


if __name__ == "__main__":
    sys.exit(main())
