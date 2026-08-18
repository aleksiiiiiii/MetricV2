# Déploiement et exploitation (`OPS-02` / `L17-02`)

Comment installer Metric sur un serveur Linux, le mettre à jour, le sauvegarder et le
restaurer — **sans mémoire du contexte**. C'est la promesse de `OPS-02` : redéployer de
zéro en ne lisant que ce dossier.

**La cible** : une machine Linux, systemd, derrière **Nginx Proxy Manager**. Rien n'est
conteneurisé — `docker-compose.yml` est écrit et non exécuté depuis le lot L00, et NPM rend
la question sans objet.

> **Ce document décrit une procédure qui n'a pas encore été exécutée en entier.** Elle est
> écrite depuis le code, vérifiée ligne à ligne contre lui, et chaque piège cité vient d'un
> incident réel ou d'une contrainte lue dans le source. Ce qui reste à éprouver est nommé
> au §9.

---

## 1. Ce que la machine doit avoir

| | Pourquoi |
|---|---|
| **Python ≥ 3.12** | exigé par `backend/pyproject.toml` |
| **Node récent** | Vite 8 et TypeScript 6 |
| `make`, `curl`, `tar` | l'installation et les mises à jour |
| Un utilisateur dédié, **non root** | il portera le service et les secrets |

> **Debian 12 livre Python 3.11.** `make setup` y échoue **après** avoir créé un venv à
> moitié, ce qui laisse une installation ni faite ni défaite. Vérifie la version avant
> toute chose :
>
> ```bash
> python3 --version    # doit être ≥ 3.12
> ```

## 2. La structure des dossiers

Pose-la **dès le premier jour** — `make update ARGS=migrate-layout` la monte, y compris
depuis une installation à plat existante, qu'il **déplace** sans la copier. La monter plus
tard demanderait un arrêt de service, et c'est elle qui rend les mises à jour réversibles.

```
/opt/metric/
├── releases/
│   ├── 2026-08-13-a1b2c3d/      ← une version, complète et autonome
│   └── 2026-08-10-9f8e7d0/      ← la précédente, gardée pour le retour arrière
├── current -> releases/2026-08-13-a1b2c3d
└── shared/
    └── .env                      ← les secrets, hors des releases
```

Trois propriétés, et chacune répond à un risque :

- **`current` est un lien.** Basculer une version est le déplacement d'un lien : atomique,
  instantané, et réversible par le geste inverse. Vider un dossier puis extraire par-dessus
  laisserait, si l'extraction échoue au milieu, une application ni ancienne ni nouvelle —
  et le projet n'a **aucune annulation nulle part**.
- **`.env` vit dans `shared/`.** Il n'est jamais dans ce qu'on remplace, donc jamais dans ce
  qu'on peut perdre. Chaque release y pointe par un lien.
- **On garde trois releases.** Assez pour reculer de deux crans, pas assez pour remplir le
  disque.

## 3. Première installation

### 3.1 — Le code

```bash
sudo mkdir -p /opt/metric/{releases,shared}
sudo chown -R metric:metric /opt/metric
sudo -u metric -s

cd /opt/metric
RELEASE="releases/$(date +%Y-%m-%d)-initial"
mkdir -p "$RELEASE"
curl -fsSL https://github.com/aleksiiiiiii/MetricV2/archive/refs/heads/main.tar.gz \
  | tar xz --strip-components=1 -C "$RELEASE"
```

> **Dépôt privé ?** Ajoute `-H "Authorization: Bearer $GITHUB_TOKEN"`. Un dépôt privé rend
> un `404` sans jeton, indistinguable d'un dépôt qui n'existe pas — c'est le message qui
> fait chercher une heure.

### 3.2 — Les secrets

Trois se génèrent, et **aucun ne se retrouve s'il est perdu** :

```bash
cd "$RELEASE"
make hash-password                                            # AUTH_PASSWORD_HASH
make vapid-keys                                               # VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))" # JWT_SECRET, puis ICAL_SECRET
```

Puis `/opt/metric/shared/.env`, à partir de `.env.example`, avec **au minimum** :

```ini
APP_ENV=production
NEXTCLOUD_URL=https://…
NEXTCLOUD_USERNAME=…
NEXTCLOUD_PASSWORD=…
AUTH_USERNAME=…
AUTH_PASSWORD_HASH=$argon2id$…
JWT_SECRET=…                              # ≥ 32 caractères, jamais celui de développement
CORS_ORIGINS=https://metric.tondomaine.fr # l'adresse HTTPS publique
TRUST_PROXY_HEADERS=true                  # NPM est devant
VAPID_PUBLIC_KEY=…
VAPID_PRIVATE_KEY=…
VAPID_SUBJECT=mailto:toi@tondomaine.fr
ICAL_SECRET=…                             # ≥ 32 caractères, sinon le flux n'est pas publié
```

```bash
chmod 600 /opt/metric/shared/.env
ln -sfn /opt/metric/shared/.env "$RELEASE/.env"
```

> **Le lien, et pas un `EnvironmentFile=` systemd.** L'application lit déjà `.env`
> elle-même (`pydantic-settings`, `backend/app/config.py`). Passer par systemd ajouterait
> un **second analyseur** du même fichier, avec ses propres règles de guillemets — et un
> hash Argon2 commence par `$argon2id$v=19$m=…`, c'est-à-dire précisément le genre de
> valeur sur laquelle deux analyseurs se mettent à diverger. Une seule implémentation.

> **`APP_ENV=production` est un garde-fou, pas une étiquette.** L'API **refuse de démarrer**
> si le secret JWT est resté celui de développement, s'il fait moins de 32 caractères, si le
> hash de mot de passe manque ou si Nextcloud n'est pas renseigné
> (`config.refuse_unsafe_production`). Échouer au déploiement plutôt qu'à la première
> requête : c'est le seul moment où l'on regarde les journaux de démarrage.

### 3.3 — Construire

```bash
cd "$RELEASE"
make setup    # venv backend + npm install
make build    # bundle + service worker
make check    # 1183 tests backend, 318 tests d'écran
```

> **`make build` n'est pas optionnel.** `frontend/dist` est ignoré par git, donc absent de
> l'archive : sans lui il n'y a pas d'application, seulement des sources. Et c'est le
> **seul endroit où le service worker est produit** — `lib/pwa.ts` ne l'enregistre qu'en
> production, `make dev` ne l'éprouve jamais.

### 3.4 — Basculer

```bash
ln -sfn "/opt/metric/$RELEASE" /opt/metric/current
```

## 4. L'unité systemd

`/etc/systemd/system/metric-api.service` :

```ini
[Unit]
Description=Metric — API
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=metric
Group=metric
WorkingDirectory=/opt/metric/current/backend

# Un seul worker. Voir la note ci-dessous — ce n'est pas un réglage de performance.
ExecStart=/opt/metric/current/backend/.venv/bin/uvicorn app.main:app \
          --host 127.0.0.1 --port 8000 --workers 1

Restart=on-failure
RestartSec=5

# L'ordonnanceur des rappels vit dans le `lifespan` (`NOT-02`) : il doit s'arrêter
# proprement, pas se faire tuer au milieu d'un envoi.
TimeoutStopSec=10

# Journaux dans le journal système, pas dans un fichier qui grossit sans surveillance.
StandardOutput=journal
StandardError=journal

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/metric

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now metric-api
systemctl status metric-api
```

> ### `--workers 1`, et ce n'est pas négociable
>
> L'ordonnanceur des rappels tourne **dans** le processus de l'API. Deux workers, c'est
> deux ordonnanceurs : au même créneau, tous deux lisent `notifications/sent.csv`, tous
> deux n'y trouvent rien, tous deux envoient. **L'utilisateur reçoit la notification en
> double**, et le journal n'en porte qu'une trace ambiguë.
>
> `sent.csv` déduplique entre deux *passes*, pas entre deux processus qui lisent au même
> instant. Si la charge l'exigeait un jour — elle ne l'exigera pas, c'est une application
> mono-utilisateur —, il faudrait sortir l'ordonnanceur de l'API, pas ajouter un worker.

> **`WorkingDirectory` passe par `current/`, donc par le lien, et systemd le résout au
> démarrage.** Après une bascule, l'unité tourne **encore sur l'ancienne release** tant
> qu'on ne l'a pas redémarrée. C'est voulu — ça sépare la bascule du redémarrage — mais
> c'est le piège classique de cette structure.

## 5. Nginx Proxy Manager

Deux destinations, un seul domaine :

| Chemin | Vers |
|---|---|
| `/api` | `127.0.0.1:8000` |
| tout le reste | les fichiers statiques de `/opt/metric/current/frontend/dist` |

**L'API reste sur `127.0.0.1`.** Elle porte les identifiants Nextcloud et le secret JWT ;
seul le proxy la joint. Ne lui donne pas `--host 0.0.0.0`.

> **Si NPM tourne en conteneur**, monte `/opt/metric` — **pas** `/opt/metric/current`. Un
> montage sur le lien fige la cible au démarrage du conteneur, et la première bascule
> servirait encore l'ancienne version sans que rien ne le dise.

### Quatre réglages sans lesquels ça a l'air de marcher

```nginx
# 1. L'application est une SPA. Sans ce repli, ouvrir /reglages fonctionne depuis la
#    navigation et rend un 404 AU RECHARGEMENT — le défaut qu'on ne voit qu'en actualisant
#    une page qui n'est pas la racine.
location / {
    try_files $uri /index.html;
}

# 2. Le service worker se revérifie à chaque navigation. Un cache long le figerait, et
#    aucune mise à jour n'atteindrait plus les appareils déjà passés.
location = /sw.js {
    add_header Cache-Control "no-cache";
}

# 3. Les fichiers empreintés, eux, ne se périment jamais.
location /assets/ {
    add_header Cache-Control "public, max-age=31536000, immutable";
}

# 4. /api n'est JAMAIS mis en cache. Une réponse mémorisée par le proxy est exactement ce
#    que le service worker s'interdit (`L15-02`) : un chiffre d'hier sur une page
#    d'apparence normale, sans rien à l'écran pour s'en apercevoir.
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_cache off;
}

# 5. Une photo de repas ne tient pas dans le plafond par défaut. NPM hérite du
#    `client_max_body_size 1m` de nginx : au-delà, il refuse **lui-même**, l'API ne voit
#    jamais la requête, et le refus n'a ni code ni français. Symptôme relevé en usage :
#    « Estimer les macros » rendait un 413 nu et l'écran un échec sans phrase.
#
#    16 Mo, la même valeur que la garde de l'API (`app/core/limits.py`). Les deux ne se
#    remplacent pas : celle-ci refuse au bord, celle de l'API refuse ce qui la joint
#    directement — et elle, au moins, répond dans la forme du catalogue d'erreurs.
client_max_body_size 16m;
```

**Le TLS est la condition de tout le lot L15** : un service worker et Web Push exigent un
contexte sécurisé, et iOS n'accepte Web Push qu'une fois l'application ajoutée à l'écran
d'accueil. C'est NPM qui le fournit.

## 6. Vérifier après un déploiement

```bash
cd /opt/metric/current && make check-storage    # Nextcloud : connexion, écriture, ETag
curl -s https://metric.tondomaine.fr/api/health
```

`storage_configured` et `auth_configured` doivent valoir `true`.

Puis, **et c'est ce que le déploiement débloque** : le §0bis de
[`verifications-manuelles.md`](verifications-manuelles.md) — installer depuis Safari iOS,
recevoir un rappel application fermée, et vérifier qu'aucun chiffre ne s'affiche en mode
avion. C'est la moitié de DoD du lot L15, et elle ne se teste que derrière un vrai HTTPS.

## 7. Mettre à jour

```bash
cd /opt/metric/current
make update                        # ne touche à rien : dit ce qui tourne et ce qui est dispo
make update ARGS="run --dry-run"   # le plan, étape par étape, sans rien exécuter
make update ARGS=run               # la mise à jour
make update ARGS=rollback          # le retour arrière
```

`scripts/update.py` tient la procédure ci-dessous, dans le même ordre, et ajoute ce qu'une
suite de commandes tapées à la main ne peut pas offrir : une sauvegarde **relue** avant que
quoi que ce soit ne bouge, une archive vérifiée **entière** avant d'être extraite, et un
**retour arrière automatique** si `/api/health` ne revient pas dans les trente secondes.
Sans dépendance et sans le `.venv` — qu'il est précisément chargé de reconstruire.

La première exécution sur une installation existante passe par
`make update ARGS=migrate-layout`, qui monte la structure du §2, écrit l'unité systemd du
§4 et retient les trois valeurs qui ne se devinent pas dans `shared/deploy.conf` : la
racine, l'utilisateur du service, et si NPM sert le front depuis cette machine.

### La même chose à la main

Utile pour comprendre ce que le script fait, ou le jour où il est lui-même en cause —
**et l'ordre est ce qui rend la procédure réversible** :

```bash
cd /opt/metric
cp shared/.env /opt/metric/backups/.env.$(date +%F-%H%M)   # et RELIS-LE avant de continuer

RELEASE="releases/$(date +%Y-%m-%d)-$(git ls-remote … | cut -c1-7)"
mkdir -p "$RELEASE"
curl -fsSL …/main.tar.gz | tar xz --strip-components=1 -C "$RELEASE"
ln -sfn /opt/metric/shared/.env "$RELEASE/.env"

cd "$RELEASE" && make setup && make build && make check     # AVANT la bascule

ln -sfn "/opt/metric/$RELEASE" /opt/metric/current
sudo systemctl restart metric-api
curl -s https://metric.tondomaine.fr/api/health
```

**`make setup` à chaque fois.** Le lot L15 en a donné la démonstration : il a ajouté
`pywebpush` aux dépendances. Une mise à jour qui aurait recopié l'ancien `.venv` aurait
démarré une API qui **plante à l'import**, quelques secondes après « mise à jour réussie ».

**Il n'y a aucune migration de données à jouer**, et ce n'est pas un oubli : `STO-04` migre
les en-têtes CSV à la lecture, par remappage de noms, et une colonne inconnue de
l'application est préservée. Le format se rattrape seul au premier accès.

### Revenir en arrière

```bash
ln -sfn /opt/metric/releases/<la-précédente> /opt/metric/current
sudo systemctl restart metric-api
```

Deux commandes, quelques secondes. C'est toute la raison d'être de la structure du §2.

## 8. Sauvegarder et restaurer

**Les données ne sont pas ici.** Tous les CSV et toutes les photos vivent sur Nextcloud
(`STO-01`), qui porte son propre versionnement (`STO-10`). Le serveur n'en détient aucune
copie, et c'est l'intérêt du choix de stockage : perdre la machine ne perd pas un an de
suivi.

**Ce qui est local et irremplaçable tient dans `shared/.env`.** Quatre secrets, dont la
perte est irréversible et *silencieuse* :

| Clé | Ce que sa perte détruit |
|---|---|
| `VAPID_PRIVATE_KEY` | **tous** les abonnements push, définitivement. Les appareils resteraient enregistrés côté service push pendant que chaque envoi serait refusé — sans rien pour le signaler. Il faut alors vider `notifications/subscriptions.csv` et réabonner chaque appareil |
| `ICAL_SECRET` | l'abonnement Apple Calendar, à recréer à la main sur chaque appareil |
| `AUTH_PASSWORD_HASH` | la connexion — plus personne n'entre |
| `NEXTCLOUD_PASSWORD` | l'accès aux données |

Sauvegarde `shared/.env` **ailleurs que sur la machine**, et relis la copie. Une sauvegarde
qu'on n'a pas relue n'est pas une sauvegarde.

## 9. Ce qui casse, et à quoi ça ressemble

Les symptômes ne ressemblent jamais à leur cause. Cette table est le vrai contenu de ce
document.

| Symptôme | Cause |
|---|---|
| L'API refuse de démarrer, message explicite au boot | `APP_ENV=production` fait son travail : secret de développement, JWT trop court, hash absent ou Nextcloud non renseigné |
| `/reglages` marche en navigation, **404 au rechargement** | `try_files` manquant côté nginx |
| Une correction déployée ne se voit pas sur le téléphone | `/sw.js` mis en cache par le proxy — le service worker installé est figé |
| Les écrans chargent indéfiniment, sans erreur | `CORS_ORIGINS` ne porte pas l'adresse HTTPS publique |
| Cinq échecs de connexion bloquent **tout le monde** | `TRUST_PROXY_HEADERS=false` derrière le proxy : l'anti-brute-force voit l'adresse de NPM |
| Une notification arrive **en double** | plus d'un worker uvicorn — donc plus d'un ordonnanceur |
| Aucun rappel n'arrive | trois conditions, à trois endroits : `make console` → `push` les affiche ensemble |
| Un écran affiche des chiffres alors que l'API est coupée | **le plus grave** : le proxy ou le worker met `/api` en cache. Voir `sw/strategy.ts` |
| L'API démarre et refuse toute connexion | `shared/.env` illisible par l'utilisateur du service — ressemble trait pour trait à un mot de passe faux |
| Le tableau de bord tombe en `502` | une cellule abîmée dans un fichier de configuration. Les familles *planning* s'en replient, les fichiers de **mesure** non : `docs/etat-du-projet.md` §2 |

## 10. Ce qui n'est pas encore fait

Nommé plutôt que passé sous silence :

- **Cette procédure n'a jamais été exécutée en entier.** Elle est écrite depuis le code et
  vérifiée contre lui ; elle n'a pas encore installé un serveur.
- **Le script de mise à jour n'a jamais tourné sur le serveur.** `scripts/update.py`
  existe et est éprouvé : `python3 scripts/update-essais.py` joue trente essais — l'archive
  coupée en plein milieu, le refus sur un Python trop vieux *avant* que la sauvegarde ne
  soit écrite, la relecture de sauvegarde qui diverge, le retour arrière automatique,
  l'élagage qui épargne `current`, et `--dry-run` qui ne touche à rien. Une mise à jour
  réelle a aussi été jouée de bout en bout depuis GitHub : téléchargement, `make setup`,
  `make build`, `make check`.

  Ce qu'il reste à voir en vrai, et qui ne s'émule pas : le chemin `systemctl` — ici c'est
  toujours le repli par la console qui a été emprunté —, les droits sur un `shared/.env`
  appartenant à un autre utilisateur que celui qui lance, et `migrate-layout` sur une
  installation à plat qui **tourne** plutôt que sur une reconstitution.

- **Ce que cette mise à jour réelle a trouvé, et qui bloquait tout déploiement neuf** :
  `make setup` appelait `npm run fonts`, qui régénérait `src/styles/fonts.css` avec un
  `unicode-range` sur une seule ligne — que `prettier --check` refuse. `make check`
  échouait donc sur un fichier que personne n'avait édité, dans **toute** installation
  fraîche, y compris celle du §3.3. Les `.woff2` et le CSS étant tous versionnés, l'appel
  a été retiré de `make setup` ; `make fonts` reste, et repasse maintenant prettier sur ce
  qu'il produit. Aucun test ne pouvait voir ce défaut : la batterie tourne sur un dépôt où
  le fichier est déjà au bon format.
- **L'unité systemd du §4 n'a pas tourné.** Elle est écrite depuis le code, pas depuis un
  `systemctl status` réussi.
- **Aucune sauvegarde automatique de `shared/.env`.** C'est aujourd'hui un geste manuel, et
  c'est le seul point de perte irréversible du déploiement.
- **`L17-03`, la revue de sécurité** — en-têtes, CSP, limitation de débit — n'est pas faite.
  Ce document installe ; il ne durcit pas.
