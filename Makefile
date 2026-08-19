# Metric — repository orchestration.
# A single entry point for both halves of the project: the FastAPI backend and the
# React frontend. Every command below works from the repository root, and none of them
# assumes the other half is already running.

PY := backend/.venv/bin/python
UVICORN := backend/.venv/bin/uvicorn

.DEFAULT_GOAL := help
.PHONY: help setup setup-api setup-web console dev dev-lan dev-api dev-web preview \
        check check-api check-web test test-api test-web eval fmt fmt-check build fonts \
        check-storage hash-password vapid-keys update clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ── Installation ───────────────────────────────────
setup: setup-api setup-web ## Install everything: backend virtualenv and frontend packages

setup-api:
	python3 -m venv backend/.venv
	$(PY) -m pip install -q -U pip
	$(PY) -m pip install -q -e "./backend[dev]"

# No "npm run fonts" here, on purpose. Both the .woff2 files AND fonts.css are committed,
# so replaying the download adds nothing, introduces a network dependency at the most
# fragile moment of an install — and regenerates fonts.css in a shape prettier rejects,
# which made "make check" fail on every fresh installation. Found by deploying for real,
# never by the test suite: it runs against a checkout where the file is already correct.
setup-web:
	cd frontend && npm install --no-audit --no-fund

# ── Development ────────────────────────────────────
console: ## Supervision console: start/stop/status/logs, build, HTTPS tunnel, push
	@python3 scripts/metric.py $(filter-out $@,$(MAKECMDGOALS))

dev: ## Run the API and the frontend together (foreground, Ctrl-C stops both)
	@bash scripts/dev.sh

dev-lan: ## Same as dev, but the frontend is reachable from a phone on the local network
	@METRIC_LAN=1 bash scripts/dev.sh

dev-api: ## Run the API on its own, on :8000
	cd backend && ../$(UVICORN) app.main:app --reload --port 8000

dev-web: ## Run the frontend on its own, on :5173
	cd frontend && npm run dev

# The service worker exists ONLY in a production build — `lib/pwa.ts` registers it in
# production and nowhere else. Exercising the PWA, its installation and the reminders
# therefore goes through here, and not through "dev", where the worker would serve stale
# files while you are still editing them.
preview: build ## Serve the production build on :4173 (the only place the service worker exists)
	cd frontend && npm run preview -- --port 4173 --strictPort

# ── Verification (what CI replays) ─────────────────
#
# "check" is the gate: it must be green before every commit, without exception. It is
# split in two so that either half can be run alone while working on that side, but the
# combined target is the one that decides.
check: check-api check-web ## Lint, type-check and test, on both sides

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

test: test-api test-web ## Run the tests only, skipping lint and type-checking

test-api:
	cd backend && .venv/bin/python -m pytest

test-web:
	cd frontend && npm run test

# ── Answer quality (deliberately outside "check") ──
#
# **Deliberately outside "check".** This set calls a paid model: it costs money, it
# depends on the network, and it is not deterministic — three reasons why it has no place
# in a suite that must be green before every commit. The `testpaths = ["tests"]` setting
# in pyproject.toml keeps it out of pytest collection as well.
#
# Run it by hand, before and after any change of model or of instructions. The flags below
# belong to the evaluation runner and are French on purpose — they are its real argument
# names, not prose:
#
#   make eval
#   make eval ARGS="--model anthropic/claude-opus-5 --reflexion --sortie apres.json"
#   make eval ARGS="--comparer apres.json"
eval: ## Run the assistant evaluation set (PAID API CALLS — see docs/assistant-coach.md)
	cd backend && .venv/bin/python -m evals.runner $(ARGS)

# ── Miscellaneous ──────────────────────────────────
fmt: ## Format the code in place, on both sides
	cd backend && .venv/bin/python -m ruff format .
	cd backend && .venv/bin/python -m ruff check --fix .
	cd frontend && npm run fmt

fmt-check: ## Report formatting problems without modifying anything
	cd backend && .venv/bin/python -m ruff format --check .
	cd frontend && npm run fmt:check

build: ## Production build of the frontend (bundle and service worker)
	cd frontend && npm run build

# Only needed when changing a family or a weight. The generated fonts.css is committed,
# and this target runs prettier over it so that the tree stays clean afterwards.
fonts: ## Re-download the local font files and regenerate fonts.css
	cd frontend && npm run fonts

check-storage: ## Diagnose the Nextcloud configuration: connection, write, ETag (STO-11)
	cd backend && .venv/bin/python -m app.scripts.check_storage

hash-password: ## Generate the Argon2id hash to paste into .env (AUTH-08)
	cd backend && .venv/bin/python -m app.scripts.hash_password

vapid-keys: ## Generate the Web Push key pair to paste into .env (NOT-01)
	cd backend && .venv/bin/python -m app.scripts.vapid_keys

# ── Deployment ─────────────────────────────────────
#
# Runs ON THE SERVER, not here. With no argument it performs "check": it reports which
# revision is deployed and which one is available upstream, and touches nothing — an
# update script someone runs out of curiosity must not update anything.
#
#   make update                        report only, changes nothing
#   make update ARGS="run --dry-run"   print every step without executing it
#   make update ARGS=run               back up, download, build, switch, restart, verify
#   make update ARGS=rollback          return to the previous release
update: ## Update the server deployment (default: report only, touches nothing)
	@python3 scripts/update.py $(ARGS)

clean: ## Remove build artefacts and caches
	rm -rf frontend/dist frontend/node_modules/.vite
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache
