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
echo

(cd backend && exec .venv/bin/uvicorn app.main:app --reload --port 8000) &
pids+=($!)

(cd frontend && exec npm run dev --silent) &
pids+=($!)

# Rend la main dès que l'un des deux s'arrête, pour ne pas laisser une moitié tourner.
wait -n
