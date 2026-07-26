# Metric — orchestration du dépôt.
# Une seule porte d'entrée pour les deux moitiés du projet.

PY := backend/.venv/bin/python
UVICORN := backend/.venv/bin/uvicorn

.DEFAULT_GOAL := help
.PHONY: help setup setup-api setup-web console dev dev-api dev-web check check-api check-web \
        test test-api test-web fmt fmt-check build fonts check-storage hash-password clean

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
console: ## Console interactive : start / stop / logs / status
	@python3 scripts/metric.py $(filter-out $@,$(MAKECMDGOALS))

dev: ## Lance API + frontend ensemble (au premier plan, Ctrl-C arrête tout)
	@bash scripts/dev.sh

dev-api: ## Lance l'API seule sur :8000
	cd backend && ../$(UVICORN) app.main:app --reload --port 8000

dev-web: ## Lance le frontend seul sur :5173
	cd frontend && npm run dev

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

clean: ## Supprime les artefacts de build et les caches
	rm -rf frontend/dist frontend/node_modules/.vite
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache
