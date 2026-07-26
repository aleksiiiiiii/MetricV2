# Metric

Le journal instrumenté d'une vie. Suivi sportif personnel — corps, activité, nutrition,
hydratation, suppléments, planning, assiduité — mono-utilisateur, français, métrique.

Les données vivent en **CSV sur Nextcloud**, lisibles dans un tableur même sans l'app.
Il n'y a pas de base de données.

## Documents de référence

| Fichier | Contenu |
|---|---|
| [backlogV2.md](backlogV2.md) | Backlog fonctionnel complet (13 sections) |
| [heat_backlog.md](heat_backlog.md) | Spec `HEAT` v2 — moteur d'assiduité multi-pistes |
| [GuidelinesUI.html](GuidelinesUI.html) | Charte graphique, tokens et composants |
| [ROADMAP.md](ROADMAP.md) | Lots de livraison, versioning, décisions arrêtées |

`heat_backlog.md` **remplace** la partie `HEAT` de la section 12 de `backlogV2.md`.
En cas de contradiction, c'est lui qui fait autorité.

## Stack

- **Backend** — Python 3.14 · FastAPI · Pydantic v2 · stockage WebDAV/CSV
- **Frontend** — React 19 · Vite · TypeScript strict · TanStack Query
- **IA** — OpenRouter (modèles gratuits), optionnelle : sans clé, tout reste en saisie manuelle

## Démarrage

```bash
make setup     # venv backend + npm install frontend + polices locales
cp .env.example .env    # puis renseigner Nextcloud et le secret JWT
make dev       # API sur :8000, frontend sur :5173 (proxy /api → :8000)
```

Le frontend démarre sans backend configuré : seuls les écrans de données échouent,
proprement.

## Commandes

| Commande | Effet |
|---|---|
| `make dev` | Lance backend et frontend ensemble |
| `make dev-api` / `make dev-web` | Lance l'un ou l'autre |
| `make check` | Lint + types + tests, des deux côtés (ce que vérifie la CI) |
| `make test` | Tests seuls |
| `make fmt` | Formatage |
| `make build` | Build de production du frontend |

## État

Voir [ROADMAP.md](ROADMAP.md#5-suivi). Version courante : `v0.1.0` (lot L00 — fondations).
