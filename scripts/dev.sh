#!/usr/bin/env bash
# Lance l'API et le frontend ensemble, et les arrête ensemble.
#
# Le piège classique du `cmd_a & cmd_b` : Ctrl-C ne tue que le processus de premier
# plan et laisse uvicorn tourner en fond, port 8000 occupé au prochain démarrage.
# Le trap ci-dessous s'en charge.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x backend/.venv/bin/uvicorn ]]; then
  echo "Environnement backend absent. Lancer d'abord : make setup" >&2
  exit 1
fi

if [[ ! -d frontend/node_modules ]]; then
  echo "Dépendances frontend absentes. Lancer d'abord : make setup" >&2
  exit 1
fi

pids=()

cleanup() {
  trap - INT TERM EXIT
  for pid in "${pids[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "→ API     http://127.0.0.1:8000/api/health"
echo "→ Doc API http://127.0.0.1:8000/api/docs"
# L'URL du frontend est annoncée par Vite lui-même : si 5173 est déjà pris, il bascule
# sur le port suivant, et une URL codée en dur ici serait fausse.

# `METRIC_LAN=1` expose le frontend sur le réseau local, pour ouvrir l'application depuis
# un téléphone (`L17-07` : le mobile est la cible d'usage principale, et l'émulation ne
# reproduit ni le pouce ni le clavier système).
#
# **Seul Vite est exposé.** Son proxy relaie `/api` depuis la machine de développement
# vers `127.0.0.1:8000` : l'API — donc les identifiants Nextcloud et le secret JWT —
# reste injoignable depuis le réseau. Ne pas ajouter `--host` à uvicorn « par symétrie ».
#
# Une chaîne et non un tableau : sous `set -u`, bash 3.2 — celui que macOS livre — traite
# l'expansion d'un tableau **vide** comme une variable non définie et s'arrête. Le cas
# nominal, `make dev`, serait tombé. Vide, la chaîne ne produit aucun mot ; sinon elle en
# produit un seul, et sa valeur est un littéral que ce script contrôle.
web_host=""
if [[ -n "${METRIC_LAN:-}" ]]; then
  web_host="--host"
  echo
  echo "⚠  Frontend exposé sur le réseau local, en clair (http://, pas https://)."
  echo "   À n'utiliser que sur un réseau de confiance. macOS peut demander à"
  echo "   autoriser « node » à accepter les connexions entrantes : accepter."
fi
echo

(cd backend && exec .venv/bin/uvicorn app.main:app --reload --port 8000) &
pids+=($!)

# shellcheck disable=SC2086 -- découpage en mots voulu : vide = aucun argument.
(cd frontend && exec npm run dev --silent -- $web_host) &
pids+=($!)

# Rend la main dès que l'un des deux s'arrête, pour ne pas laisser une moitié tourner.
#
# `wait -n` ferait exactement cela en une ligne, mais il n'existe qu'à partir de bash 4.3
# et macOS livre toujours la 3.2 en 2026 — la 4.0 est sous GPLv3, qu'Apple ne distribue
# pas. Un script de développement doit tourner sur le shell que la machine a, pas sur
# celui qu'on aimerait qu'elle ait : on surveille donc les deux processus à la main.
while true; do
  for pid in "${pids[@]}"; do
    # `kill -0` ne tue rien : il teste seulement que le processus répond encore.
    kill -0 "$pid" 2>/dev/null || exit 0
  done
  sleep 1
done
