# Prompt — script de mise à jour (`OPS-02` / `L17-02`)

À coller dans une session neuve. Le contexte utile est dedans ; ce document n'est pas une
spécification à lire en plus, c'est le brief lui-même.

---

Lis `docs/etat-du-projet.md` en premier — document d'entrée, à jour. Puis le §5 pour la
façon dont le projet se lance, et `scripts/metric.py`, la console de supervision : le
script de mise à jour s'y adosse au lieu de piloter les serveurs lui-même.

Puis écris le script de mise à jour du déploiement. Le flux : sauvegarder ce qui est
local, récupérer la dernière version depuis GitHub, remplacer l'application, réinstaller
les dépendances, rebâtir le front, relancer, vérifier — et savoir revenir en arrière.

**La cible est un serveur Linux, avec systemd, derrière Nginx Proxy Manager.** Ce n'est pas
la machine de développement : le script doit tourner là-bas, sans `make dev` et sans la
console interactive. Rien n'est conteneurisé.

**Onze décisions sont déjà prises. Ne les rouvre pas.**

---

## 1. CE QU'IL FAUT SAUVEGARDER TIENT EN UN FICHIER, ET C'EST LE PLUS DANGEREUX DU PROJET

Vérifié : tout ce qui est local et irremplaçable est dans **`.env`**. Le reste se
reconstruit (`.venv`, `node_modules`, `frontend/dist`, `.metric`) ou vit sur Nextcloud
(tous les CSV, toutes les photos). Les polices sont **versionnées dans le dépôt** — pas de
`npm run fonts` à rejouer, pas de dépendance réseau de plus.

Ne conclus pas que la sauvegarde est donc facultative. `.env` porte quatre secrets dont la
perte est **irréversible et silencieuse** :

| Clé | Ce que sa perte détruit |
|---|---|
| `VAPID_PRIVATE_KEY` | **tous** les abonnements push, définitivement — un abonnement est lié à la clé publique qui l'a créé, et les appareils déjà enregistrés continueraient d'exister côté service push pendant que chaque envoi serait refusé, sans rien pour le signaler |
| `ICAL_SECRET` | l'abonnement Apple Calendar, qu'il faut recréer à la main sur chaque appareil |
| `AUTH_PASSWORD_HASH` | la connexion — plus personne n'entre |
| `NEXTCLOUD_PASSWORD` | l'accès à un an de données |

Sauvegarde donc `.env`, plus `data-local/` s'il existe, plus tout fichier non suivi par git
et non ignoré qui traînerait à la racine — un `.env.production` posé à la main, par exemple.
`git status --porcelain --ignored` sait le dire ; ne devine pas la liste, calcule-la.

**Et vérifie la sauvegarde avant de détruire quoi que ce soit** : relis le fichier écrit,
compare son empreinte à l'original, refuse d'aller plus loin si ça ne correspond pas. Une
sauvegarde qu'on n'a pas relue n'est pas une sauvegarde.

## 2. ON NE SUPPRIME PAS LE DOSSIER EN PLACE — ON BASCULE UN LIEN

C'est le seul endroit où je m'écarte du flux décrit, et la raison est la même que celle qui
gouverne tout le projet : **il n'y a aucune annulation nulle part**. Vider le dossier puis
extraire par-dessus laisse, si l'extraction échoue au milieu — réseau coupé, archive
tronquée, disque plein —, une application ni ancienne ni nouvelle, et rien pour revenir.

Structure retenue :

```
metric/
├── releases/
│   ├── 2026-08-13T14-22-05-a1b2c3d/     ← extraite, préparée, testée
│   └── 2026-08-10T09-11-40-9f8e7d/      ← la précédente, gardée
├── current -> releases/2026-08-13T…      ← le lien qu'on bascule
└── shared/
    └── .env                              ← hors des releases, jamais recopié
```

La bascule est **le déplacement d'un lien**, donc atomique et instantanée. Le retour
arrière aussi. `.env` vit dans `shared/` et chaque release y pointe par un lien : il n'est
jamais dans ce qu'on remplace, donc jamais dans ce qu'on peut perdre.

**Ce que ça coûte, et il faut le dire** : le chemin de l'application devient
`…/metric/current`. Nginx Proxy Manager, une unité systemd ou un lanceur qui pointerait
vers l'ancien chemin doivent être ajustés **une fois**. Prévois une commande
`migrate-layout` qui fabrique cette structure à partir d'une installation à plat existante,
sinon la première mise à jour demande un geste manuel non documenté.

Garde **trois** releases. Au-delà, supprime les plus anciennes — mais jamais celle vers
laquelle `current` pointe, ni la précédente.

## 3. UNE ARCHIVE, PAS UN CLONE

`https://github.com/aleksiiiiiii/MetricV2` — tarball via `codeload`, pas `git clone`. Trois
raisons : le serveur n'a pas besoin de git, la production ne porte pas de `.git` (donc
aucun risque de `git pull` manuel qui divergerait), et une archive se vérifie avant d'être
posée.

**Le dépôt est probablement privé.** Lis un `GITHUB_TOKEN` optionnel dans `.env` et
envoie-le en `Authorization: Bearer`. Si le téléchargement rend `404` sans jeton, ne dis pas
« introuvable » — dis « dépôt privé ? renseigne `GITHUB_TOKEN` dans `.env` ». Un `404` de
GitHub sur un dépôt privé est indistinguable d'un dépôt qui n'existe pas, et c'est
exactement le genre de message qui fait chercher une heure.

**Les tags s'arrêtent à `v0.12.0`** alors que le projet est en `v0.17.0` : le versionnement
par tag n'a pas été tenu. Suis donc **une branche** par défaut — `main` —, avec `--ref` pour
viser un tag ou un commit précis. Ne construis rien qui suppose qu'un tag existe.

Écris dans la release un fichier `RELEASE` portant la référence, le SHA obtenu et l'horodatage.
C'est ce qui permet de répondre à « qu'est-ce qui tourne, là ? » sans ouvrir un fichier de code.

## 4. LES DÉPENDANCES SE RÉINSTALLENT, TOUJOURS

Non négociable, et le lot L15 vient d'en donner la démonstration : il a ajouté `pywebpush`
au `pyproject.toml`. Une mise à jour qui aurait recopié l'ancien `.venv` aurait démarré une
API qui **plante à l'import**, plusieurs secondes après un « mise à jour réussie ».

Dans la nouvelle release, dans cet ordre :

```
make setup      # venv backend + npm install — les deux, jamais l'un sans l'autre
make build      # ET c'est le seul endroit où le service worker est produit (L15-02)
```

`make build` n'est pas une commodité : `frontend/dist` est ignoré par git, donc absent de
l'archive. Sans lui il n'y a **pas d'application**, seulement des sources.

Prévois `--skip-check` mais **fais tourner `make check` par défaut** dans la release
préparée, avant la bascule. Une release qui ne passe pas ses propres tests ne devient pas
`current` : c'est le dernier filet avant que l'utilisateur ne s'en aperçoive.

## 5. SUR LE SERVEUR, C'EST SYSTEMD QUI DÉTIENT L'API — PAS LA CONSOLE

**Linux.** `scripts/metric.py` lance des processus détachés et retient leurs PID dans
`.metric/state.json` : c'est ce qu'il faut pour développer, et c'est le mauvais régime pour
un serveur. Rien ne relance l'API après un redémarrage de la machine, rien ne la relève si
elle meurt, et les journaux vont dans un fichier au lieu du journal système.

Le script de mise à jour **fournit et installe une unité systemd**, `metric-api.service` :

- `Type=exec`, un `User=` dédié et non root, `WorkingDirectory=` sur `current/backend` ;
- `ExecStart=` sur `current/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000` ;
- `Restart=on-failure`, `RestartSec=5` ;
- `EnvironmentFile=` sur `shared/.env` ;
- `After=network-online.target`.

Le redémarrage devient `systemctl restart metric-api`, et la vérification
`systemctl is-active`. **L'ordonnanceur des rappels (`NOT-02`) vit dans le `lifespan` de
l'API** : `TimeoutStopSec` doit lui laisser le temps de s'arrêter proprement plutôt que de
le tuer au milieu d'un envoi — dix secondes suffisent largement.

> **Le `WorkingDirectory` passe par `current/`, donc par le lien.** systemd résout le lien
> **au démarrage** : après une bascule, tant qu'on n'a pas redémarré l'unité, elle tourne
> encore sur l'ancienne release. C'est le comportement voulu — c'est ce qui rend la bascule
> et le redémarrage deux étapes distinctes — mais c'est aussi le piège classique de cette
> structure. Ne l'oublie pas dans l'ordre des opérations.

Le script doit donc **détecter son régime** : si l'unité existe, il passe par `systemctl` ;
sinon il retombe sur `scripts/metric.py` et le dit. Une seule commande pour l'utilisateur,
deux chemins selon la machine.

Après le redémarrage, interroge `/api/health` et vérifie que `storage_configured` et
`auth_configured` sont vrais. **Si la santé ne répond pas dans les trente secondes,
rebascule le lien sur la release précédente, redémarre, et dis-le.** Un retour arrière
automatique est ce qui distingue un script de mise à jour d'un script d'espoir.

Prévois `rollback` en commande à part entière, pour le cas où la panne se voit dix minutes
plus tard.

## 5bis. CE QUE LA MACHINE DOIT AVOIR, VÉRIFIÉ AVANT DE TOUCHER À QUOI QUE CE SOIT

Trois contrôles préalables, et le premier a mordu du monde :

- **Python ≥ 3.12.** `pyproject.toml` l'exige. Debian 12 livre **3.11** : `make setup` y
  échoue après avoir déjà créé un venv à moitié. Vérifie la version *avant* la sauvegarde,
  pas au milieu de l'installation, et nomme le paquet à installer si elle manque.
- **Node récent.** Vite 8 et TypeScript 6 ne tournent pas sur le Node d'une distribution
  ancienne. Même règle : vérifier avant, refuser clairement.
- **De la place.** Trois releases, deux `node_modules` et deux `.venv` pèsent. Un disque
  plein au milieu d'une extraction est exactement le scénario contre lequel la décision 2
  existe — autant ne pas y arriver.

Et **les droits** : `shared/.env` en `0600`, propriété de l'utilisateur du service. Un
`chown` manqué donne une API qui démarre et refuse toute connexion — ce qui ressemble
trait pour trait à un mot de passe faux, et fait chercher au mauvais endroit.

## 6. NE TOUCHE JAMAIS À NEXTCLOUD

Le script ne lit, n'écrit et ne sauvegarde **rien** sur Nextcloud. Les données y vivent, et
elles y survivent à tout ce que fait ce script — c'est l'intérêt du choix de stockage.

Il n'y a **aucune migration de schéma à jouer**, et ce n'est pas un oubli : `STO-04` migre
les en-têtes CSV à la lecture, par remappage de noms, et une colonne inconnue de
l'application est préservée. Le format se rattrape tout seul au premier accès. Si tu te
surprends à écrire une étape « migrer les données », relis ce paragraphe.

Le filet, côté données, est le versionnement Nextcloud (`STO-10`). Mentionne-le dans la
documentation ; ne l'automatise pas.

## 7. LE SCRIPT DOIT TOURNER QUAND L'APPLICATION EST CASSÉE

C'est précisément le moment où on le lance. Donc : **Python 3 de la bibliothèque standard
uniquement**, aucune dépendance, aucun besoin du `.venv` — qu'il est censé reconstruire.
`scripts/metric.py` est écrit sous cette contrainte pour la même raison et te sert de
modèle : lis-le avant d'écrire.

Reprends ses couleurs, ses `ok` / `warn` / `fail`, et son français. Deux scripts du même
dépôt qui parlent deux langues visuelles, c'est un de trop.

## 8. UNE COMMANDE `make`, ET LA CONSOLE LA CONNAÎT

`make update`, qui relaie `scripts/update.py`. Et une entrée dans `make console` — la
console est la porte d'entrée du projet depuis le L15, elle doit savoir dire quelle version
tourne et proposer la mise à jour.

Sous-commandes attendues : `check` *(quelle version tourne, laquelle est disponible, rien
n'est touché)*, `run`, `rollback`, `releases`, `migrate-layout`.

**`check` doit être le comportement par défaut sans argument.** Un script de mise à jour
qu'on lance par curiosité ne doit pas mettre à jour.

## 9. LE MODE SIMULATION N'EST PAS UNE OPTION DE CONFORT

`--dry-run` qui affiche chaque étape sans rien exécuter. C'est ce qui permet de lire le
plan avant de l'exécuter sur la seule installation qui porte de vraies données de santé.

## 10. NGINX PROXY MANAGER EST DEVANT, ET LE SCRIPT NE LE TOUCHE PAS

Le HTTPS vient de NPM, en amont. Le script ne configure aucun certificat, aucun vhost,
aucun conteneur. Ce qu'il doit, c'est **ne pas casser ce que NPM pointe** — d'où le chemin
stable de la décision 2.

**Le front est un dossier de fichiers statiques**, pas un serveur. Après `make build`, tout
est dans `current/frontend/dist`. Deux montages possibles, et le premier est le bon :

1. **NPM sert `current/frontend/dist` directement.** Zéro processus Node en production,
   donc une chose de moins à surveiller et à relancer. Si NPM tourne en conteneur, le
   dossier doit lui être **monté en volume** — et le montage doit suivre le lien, donc
   monter la racine `metric/`, pas `metric/current`.
2. Une seconde unité systemd qui fait tourner `vite preview`. Plus simple à câbler, un
   processus Node de plus à tenir. À ne prendre que si le montage de volume coince.

**Trois réglages nginx sans lesquels ça a l'air de marcher, et ne marche pas :**

- **`try_files $uri /index.html`.** L'application est une SPA : sans repli, ouvrir
  `/reglages` fonctionne depuis la navigation et rend un **404 au rechargement**. C'est le
  défaut qu'on ne voit qu'en actualisant une page qui n'est pas la racine.
- **`/sw.js` sans cache long.** Le navigateur revérifie le service worker à chaque
  navigation ; un `max-age` d'un an posé par nginx gèlerait la version installée, et une
  mise à jour ne se verrait **jamais** sur les appareils déjà passés. `/assets/*`, à
  l'inverse, porte des noms empreintés et peut être mis en cache pour toujours.
- **`/api` jamais en cache.** Une réponse mémorisée par le proxy est exactement ce que le
  service worker s'interdit (`L15-02`) : un chiffre d'hier sur une page d'apparence
  normale. Le proxy ne doit pas défaire ce que l'application prend soin de ne pas faire.

Rappelle après une mise à jour réussie, en une ligne, ce que `make console` → `proxy` dit
déjà en détail : `TRUST_PROXY_HEADERS` et `CORS_ORIGINS`, qui doit porter l'adresse HTTPS
publique.

## 11. CE QUI EST DÉTRUIT EST ANNONCÉ AVANT, PAS APRÈS

Toute suppression — releases anciennes, `.venv` remplacé — s'affiche **avant** d'être faite,
avec ce qu'elle emporte. Le projet demande deux appuis pour détruire une ligne de journal ;
un script qui efface un dossier sans le dire ne peut pas être plus léger que ça.

---

## Ce que le dépôt te donne déjà, et qui sert tel quel

- **`scripts/metric.py`** — arrêt et démarrage propres des quatre services, état sur
  disque dans `.metric/state.json`, santé de l'API. Ne réécris pas ça.
- **`make setup` / `make build` / `make check`** — les trois étapes de préparation d'une
  release existent déjà et sont testées.
- **`/api/health`** — annonce `storage_configured`, `auth_configured`, `ai_enabled` et la
  version. C'est ta vérification d'après-bascule, elle est déjà là.
- **`.gitignore`** — la liste faisant autorité de ce qui est local. Calcule la sauvegarde à
  partir de lui, ne la recopie pas à la main : la recopier, c'est promettre de la tenir à
  jour, et ça tient jusqu'au premier oubli.

## Deux choses à ne pas faire

- **Ne conteneurise rien.** `docker-compose.yml` est écrit et non exécuté depuis le lot
  L00 ; ce n'est pas le chemin retenu, et NPM rend la question sans objet.
- **Ne touche pas aux DoD ouvertes** des lots L12 à L15, ni au §7 de
  `docs/verifications-manuelles.md`.

## Ce qui reste à paramétrer, et qui ne se devine pas

Trois valeurs dépendent de l'installation. Ne les code pas en dur et ne les demande pas à
chaque exécution : **le premier `migrate-layout` les demande une fois** et les écrit dans
`shared/deploy.conf`, que les exécutions suivantes relisent.

| Valeur | Pourquoi elle ne se devine pas |
|---|---|
| Racine d'installation | `/opt/metric`, `/srv/metric` ou un dossier utilisateur : c'est ce que NPM pointe |
| Utilisateur du service | celui du `User=` de l'unité et du propriétaire de `shared/.env` |
| NPM sur la même machine ? | décide si le front se sert par volume monté ou par un second service |

Si `deploy.conf` manque à l'exécution de `run`, **arrête-toi et renvoie vers
`migrate-layout`**. Deviner une racine d'installation, c'est risquer d'écrire à côté de ce
qui tourne.

## Pour finir

Écris un plan avant de coder, comme le demande `CLAUDE.md`. Puis `make check` vert, et
**éprouve le script pour de vrai** — sur une copie, jamais sur l'installation qui porte les
vraies données :

1. une mise à jour complète, du `check` à la santé retrouvée ;
2. un `rollback` après coup ;
3. une mise à jour dont tu **casses volontairement l'archive au milieu** — c'est le seul
   essai qui prouve que la décision 2 sert à quelque chose ;
4. une mise à jour sur une machine où `python3` vaut 3.11, pour voir le refus arriver
   **avant** que quoi que ce soit ait bougé.

Les quatre, pas le premier seulement.
