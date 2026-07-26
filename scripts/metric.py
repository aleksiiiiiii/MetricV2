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
"""

from __future__ import annotations

import json
import os
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
    default_port: int
    #: `{port}` est remplacé au lancement.
    command: tuple[str, ...]
    #: Chemin interrogé pour savoir si le service répond vraiment.
    health_path: str
    #: Vite n'écoute que sur ::1 ; l'API sur 127.0.0.1.
    host: str

    @property
    def log_file(self) -> Path:
        return RUN_DIR / f"{self.key}.log"

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

SERVICES = {API.key: API, WEB.key: WEB}


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
    return f"http://{service.host}:{port}"


def responds(service: Service, port: int, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(  # noqa: S310 - hôte local, construit par nous
            url_of(service, port) + service.health_path, timeout=timeout
        ) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


# ── Actions ───────────────────────────────────────────


def prerequisites(service: Service) -> str | None:
    """Message d'erreur si le service ne peut pas démarrer, sinon `None`."""
    if service is API and not (ROOT / "backend/.venv/bin/uvicorn").exists():
        return "environnement backend absent — lance « make setup »"
    if service is WEB and not (ROOT / "frontend/node_modules").is_dir():
        return "dépendances frontend absentes — lance « make setup »"
    if service is WEB and shutil.which("npm") is None:
        return "npm introuvable dans le PATH"
    return None


def start(service: Service, *, quiet: bool = False) -> bool:
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

    port = free_port(service.default_port)
    if port != service.default_port:
        warn(f"{service.label} : port {service.default_port} occupé, bascule sur {port}")

    RUN_DIR.mkdir(exist_ok=True)
    log = service.log_file.open("wb")

    environment = dict(os.environ)
    if service is WEB:
        # Le proxy de Vite doit suivre le port réellement pris par l'API.
        api = running(API)
        environment["METRIC_API_PORT"] = str(api[1] if api else API.default_port)

    process = subprocess.Popen(  # noqa: S603 - commande construite par nous
        service.build_command(port),
        cwd=service.cwd,
        stdout=log,
        stderr=subprocess.STDOUT,
        env=environment,
        # Session détachée : un Ctrl-C dans la console ne doit pas tuer les serveurs.
        start_new_session=True,
    )

    state = read_state()
    state[service.key] = {"pid": process.pid, "port": port}
    write_state(state)

    say(f"  {dim('…')} {service.label} démarre sur le port {port}")
    for _ in range(150):  # 30 s au plus
        if process.poll() is not None:
            fail(f"{service.label} s'est arrêté immédiatement — « logs {service.key} »")
            state.pop(service.key, None)
            write_state(state)
            return False
        if responds(service, port):
            ok(f"{service.label} · {paint(url_of(service, port), SIGNAL)}")
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
    for service in SERVICES.values():
        current = running(service)
        if not current:
            occupant = "" if not port_busy(service.default_port) else dim(
                f"  (port {service.default_port} occupé par un autre processus)"
            )
            say(f"  {paint('○', INK_LOW)} {service.label:<10} arrêté{occupant}")
            continue

        pid, port = current
        healthy = responds(service, port, timeout=0.5)
        mark = paint("●", EFFORT) if healthy else paint("●", LOAD)
        state_text = "en ligne" if healthy else "démarre…"
        say(
            f"  {mark} {service.label:<10} {state_text:<10} "
            f"{paint(url_of(service, port), SIGNAL)}  {dim(f'PID {pid}')}"
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


def show_env() -> None:
    """Quelles clés sont renseignées — jamais leur valeur."""
    env_file = ROOT / ".env"
    say()
    if not env_file.exists():
        fail(".env absent — copie .env.example et renseigne-le")
        say()
        return

    values: dict[str, str] = {}
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip()

    groups = {
        "Stockage": ["NEXTCLOUD_URL", "NEXTCLOUD_USERNAME", "NEXTCLOUD_PASSWORD"],
        "Session": ["AUTH_USERNAME", "AUTH_PASSWORD_HASH", "JWT_SECRET"],
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
    start [api|web]      démarre (tout par défaut)
    stop  [api|web]      arrête
    restart [api|web]    redémarre
    status  ·  s         état, URL et configuration

  {paint('Journaux', INK_LOW)}
    logs [api|web|all] [-f] [-n N]
                         derniers messages ; -f suit en direct

  {paint('Outils', INK_LOW)}
    check                lint + types + tests des deux côtés
    test                 tests seuls
    hash                 génère le hash de mot de passe (AUTH-08)
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

    def targets() -> list[Service]:
        if not args or args[0] == "all":
            return list(SERVICES.values())
        if args[0] in SERVICES:
            return [SERVICES[args[0]]]
        fail(f"service inconnu : {args[0]} (api, web ou all)")
        return []

    match command:
        case "start":
            say()
            for service in targets():
                start(service)
            say()
        case "stop":
            say()
            for service in reversed(targets()):
                stop(service)
            say()
        case "restart" | "r":
            say()
            chosen = targets()
            for service in reversed(chosen):
                stop(service, quiet=True)
            for service in chosen:
                start(service)
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
        case "hash":
            run_make("hash-password")
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
    "start", "stop", "restart", "status", "logs", "check", "test",
    "hash", "storage", "env", "help", "quit",
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
        pool = COMMANDS if " " not in buffer else ["api", "web", "all", "-f", "-n"]
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
