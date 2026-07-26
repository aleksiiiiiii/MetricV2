# Journal des modifications

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Versionnement : une version mineure par lot de la [feuille de route](ROADMAP.md).

## [0.1.0] — 2026-07-26

Lot **L00 — Fondations, outillage, tokens UI**. Le dépôt démarre, se teste et parle
déjà la langue visuelle de Metric. Aucune fonctionnalité métier.

### Ajouté

- Dépôt initialisé : `.gitignore`, `.editorconfig`, `README`, réglages VS Code pointant
  sur le venv du backend.
- **Backend** — squelette FastAPI (Python 3.14) : configuration centralisée par
  environnement (`API-02`), route de santé publique `/api/health` (`API-04`), OpenAPI
  sur `/api/docs` (`API-05`), CORS paramétrable (`API-03`). `ruff`, `mypy --strict` et
  `pytest` configurés. 5 tests.
- **Frontend** — Vite 8 + React 19 + TypeScript 6 strict, TanStack Query et React
  Router installés, ESLint + Prettier, Vitest + Testing Library. 5 tests.
- **Tokens UI** extraits de `GuidelinesUI.html` vers `styles/tokens.css`, complétés par
  les composantes RVB des signaux — ce qui permet de dériver les 4 niveaux d'intensité
  d'une heatmap depuis une seule couleur d'accent par piste.
- **Polices servies localement** : Space Grotesk et JetBrains Mono téléchargées par
  `npm run fonts` et versionnées (14 fichiers woff2, 308 ko). Plus aucune dépendance au
  CDN Google — prérequis du fonctionnement hors-ligne (`L15`).
- `base.css` : reset, typographie, primitives de mise en page, règle graduée,
  `prefers-reduced-motion`, chiffres à chasse fixe.
- Page `/_kitchen-sink` : référence visuelle des tokens, test de dérive de la charte.
- Écran d'accueil provisoire sondant `/api/health` : prouve le proxy et illustre la
  dégradation propre quand Nextcloud ou l'IA ne sont pas configurés (`IA-07`).
- `Makefile` (`setup`, `dev`, `check`, `test`, `fmt`, `build`, `fonts`) et
  `scripts/dev.sh` qui lance les deux serveurs et les arrête ensemble.
- `.env.example` documenté et complet.
- CI GitHub Actions : formatage, lint, types, tests des deux côtés, plus build.
- `docker-compose.yml` de développement — écrit, non exécuté (Docker absent de la
  machine ; validation au `L17-01`).

### Décidé

- Les **11 points de spécification** relevés entre `backlogV2.md` et `heat_backlog.md`
  sont arrêtés et consignés au [§3 de la feuille de route](ROADMAP.md#3-points-de-spécification-à-trancher).
- `httpx2` remplace `httpx` dans tout le projet : starlette 1.x déprécie `httpx` pour
  son `TestClient`, et le client WebDAV du lot L01 doit parler la même bibliothèque que
  les tests.
- TypeScript **6.0** et non 7 : `typescript-eslint` exige `<6.1.0`. Le lint prime sur
  la dernière majeure.
- Aucune bibliothèque de graphiques ni kit UI : la charte fournit déjà courbes, barres,
  anneau, heatmap et graphique croisé en SVG.
