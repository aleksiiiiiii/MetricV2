# Metric

Le journal instrumenté d'une vie. Suivi sportif personnel — corps, activité, nutrition,
hydratation, suppléments, planning, assiduité — mono-utilisateur, français, métrique.

Les données vivent en **CSV sur Nextcloud**, lisibles dans un tableur même sans l'app.
Il n'y a pas de base de données.

## Documents de référence

| Fichier | Contenu |
|---|---|
| [docs/backlogV2.md](docs/backlogV2.md) | Backlog fonctionnel complet (13 sections) |
| [docs/heat_backlog.md](docs/heat_backlog.md) | Spec `HEAT` v2 — moteur d'assiduité multi-pistes |
| [docs/GuidelinesUI.html](docs/GuidelinesUI.html) | Charte graphique, tokens et composants |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Lots de livraison, versioning, décisions arrêtées |
| [docs/etat-du-projet.md](docs/etat-du-projet.md) | **Reprise à froid** — invariants, état, prochaine étape |
| [docs/patron-domaine.md](docs/patron-domaine.md) | Patron à recopier pour ajouter un domaine |
| [docs/front.md](docs/front.md) | **Carte du front** — les onze pages, les cinq couches, par où passer pour modifier |
| [docs/verifications-manuelles.md](docs/verifications-manuelles.md) | Ce que `make check` ne peut pas voir |

`heat_backlog.md` **remplace** la partie `HEAT` de la section 12 de `backlogV2.md`.
En cas de contradiction, c'est lui qui fait autorité.

## Stack

- **Backend** — Python 3.14 · FastAPI · Pydantic v2 · stockage WebDAV/CSV
- **Frontend** — React 19 · Vite · TypeScript strict · TanStack Query
- **IA** — OpenRouter (modèles gratuits), optionnelle : sans clé, tout reste en saisie manuelle

## Démarrage

```bash
make setup              # venv backend + npm install frontend + polices locales
cp .env.example .env    # puis : make console → « hash » et « env »
make console            # console interactive
```

Le frontend démarre sans backend configuré : seuls les écrans de données échouent,
proprement.

## Console

`make console` ouvre une console qui pilote les deux serveurs. Elle choisit un port
libre si le port habituel est pris, et le proxy du frontend suit automatiquement.

```
metric ❯ start            démarre l'API et le frontend
metric ❯ status           état, URL, et quelles clés de .env sont renseignées
metric ❯ logs api -f      suit les journaux en direct
metric ❯ restart web      redémarre un seul service
metric ❯ hash             génère le hash de mot de passe (AUTH-08)
metric ❯ env              ce qui est renseigné dans .env, sans jamais les valeurs
metric ❯ help             toutes les commandes
```

Les serveurs sont détachés : quitter la console ne les arrête pas, et les retrouver
suffit à rouvrir la console. Une commande passée en argument s'exécute et rend la
main — `make console status`.

## Commandes

| Commande | Effet |
|---|---|
| `make console` | Console interactive (chemin recommandé) |
| `make dev` | Lance les deux au premier plan, Ctrl-C arrête tout |
| `make dev-api` / `make dev-web` | Lance l'un ou l'autre |
| `make check` | Lint + types + tests, des deux côtés (ce que vérifie la CI) |
| `make test` | Tests seuls |
| `make hash-password` | Hash Argon2id à coller dans `.env` |
| `make check-storage` | Diagnostique la configuration Nextcloud |
| `make fmt` | Formatage |
| `make build` | Build de production du frontend |

## État

Voir [docs/etat-du-projet.md](docs/etat-du-projet.md). Version courante : `v0.8.0` —
jalon I terminé, jalon II à un lot de la fin.
