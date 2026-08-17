# Metric — orchestration du dépôt.
# Une seule porte d'entrée pour les deux moitiés du projet.

PY := backend/.venv/bin/python
UVICORN := backend/.venv/bin/uvicorn

.DEFAULT_GOAL := help
.PHONY: help setup setup-api setup-web console dev dev-lan dev-api dev-web preview \
        check check-api check-web test test-api test-web eval fmt fmt-check build fonts \
        check-storage hash-password vapid-keys clean

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# ── Installation ───────────────────────────────────
setup: setup-api setup-web ## Installe tout (venv backend, npm frontend, polices)

setup-api:
	python3 -m venv backend/.venv
	$(PY) -m pip install -q -U pip
	$(PY) -m pip install -q -e "./backend[dev]"

setup-web:
	cd frontend && npm install --no-audit --no-fund
	cd frontend && npm run fonts

# ── Développement ──────────────────────────────────
console: ## Console de supervision : start/stop/status/logs, build, tunnel HTTPS, push
	@python3 scripts/metric.py $(filter-out $@,$(MAKECMDGOALS))

dev: ## Lance API + frontend ensemble (au premier plan, Ctrl-C arrête tout)
	@bash scripts/dev.sh

dev-lan: ## Comme « dev », mais le frontend est joignable depuis un téléphone du réseau
	@METRIC_LAN=1 bash scripts/dev.sh

dev-api: ## Lance l'API seule sur :8000
	cd backend && ../$(UVICORN) app.main:app --reload --port 8000

dev-web: ## Lance le frontend seul sur :5173
	cd frontend && npm run dev

# Le service worker n'existe QUE dans le build (`lib/pwa.ts` ne l'enregistre qu'en
# production). Éprouver la PWA, l'installation et les rappels passe donc par ici — et non
# par « dev », où le worker servirait des fichiers périmés pendant qu'on code.
preview: build ## Sert le build de production sur :4173 (le seul endroit où vit le service worker)
	cd frontend && npm run preview -- --port 4173 --strictPort

# ── Vérifications (ce que rejoue la CI) ────────────
check: check-api check-web ## Lint + types + tests, des deux côtés

check-api:
	cd backend && .venv/bin/python -m ruff check .
	cd backend && .venv/bin/python -m ruff format --check .
	cd backend && .venv/bin/python -m mypy app tests
	cd backend && .venv/bin/python -m pytest

check-web:
	cd frontend && npm run fmt:check
	cd frontend && npm run lint
	cd frontend && npm run types
	cd frontend && npm run test

test: test-api test-web ## Tests seuls

test-api:
	cd backend && .venv/bin/python -m pytest

test-web:
	cd frontend && npm run test

# ── Qualité des réponses (hors « check ») ──────────
#
# **Délibérément hors de « check ».** Ce jeu appelle un modèle payant : il coûte, il dépend
# du réseau, et il n'est pas déterministe — trois raisons pour lesquelles il n'a rien à
# faire dans une batterie qui doit être verte avant chaque commit. Le
# « testpaths = ["tests"] » du pyproject le garde hors de la collecte pytest.
#
# Il se lance à la main, avant et après tout changement de modèle ou de consigne :
#
#   make eval
#   make eval ARGS="--model anthropic/claude-opus-5 --reflexion --sortie apres.json"
#   make eval ARGS="--comparer apres.json"
eval: ## Joue le jeu d'évaluation de l'assistant (APPELS PAYANTS — voir docs/assistant-coach.md)
	cd backend && .venv/bin/python -m evals.runner $(ARGS)

# ── Divers ─────────────────────────────────────────
fmt: ## Formate le code
	cd backend && .venv/bin/python -m ruff format .
	cd backend && .venv/bin/python -m ruff check --fix .
	cd frontend && npm run fmt

fmt-check: ## Vérifie le formatage sans modifier
	cd backend && .venv/bin/python -m ruff format --check .
	cd frontend && npm run fmt:check

build: ## Build de production du frontend
	cd frontend && npm run build

fonts: ## Retélécharge les polices locales
	cd frontend && npm run fonts

check-storage: ## Diagnostique la configuration Nextcloud (STO-11)
	cd backend && .venv/bin/python -m app.scripts.check_storage

hash-password: ## Génère le hash Argon2id à coller dans .env (AUTH-08)
	cd backend && .venv/bin/python -m app.scripts.hash_password

vapid-keys: ## Génère la paire de clés Web Push à coller dans .env (NOT-01)
	cd backend && .venv/bin/python -m app.scripts.vapid_keys

clean: ## Supprime les artefacts de build et les caches
	rm -rf frontend/dist frontend/node_modules/.vite
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache
