# Metric — instructions de travail

Application personnelle de suivi : corps, activité, nutrition, routine, planning, objectif,
assiduité, assistant IA. **FastAPI + CSV sur Nextcloud** d'un côté, **React + TypeScript**
de l'autre. Un seul utilisateur, ses vraies données de santé, et **aucune annulation nulle
part** — ce dernier point explique la moitié des règles qui suivent.

Tout le code est en anglais : les identifiants, les commentaires, les noms de fichiers.
Les **messages d'erreur** et les **commits** restent en français — ils s'adressent à
l'utilisateur et au relecteur, pas au compilateur. Le §2 et le §6 en portent la règle
détaillée.

---

## 1. Où lire quoi

Ne pas tout lire. Ouvrir ce qui correspond à la tâche.

| Tâche | Le document |
|---|---|
| Toucher au front — écrans, styles, composants | [`docs/front.md`](docs/front.md) |
| Ajouter ou reprendre un domaine backend | [`docs/patron-domaine.md`](docs/patron-domaine.md) |
| Comprendre un invariant, une décision passée | §2 de [`docs/etat-du-projet.md`](docs/etat-du-projet.md) |
| Vérifier un écran à la main | [`docs/verifications-manuelles.md`](docs/verifications-manuelles.md) |
| L'assistant qui écrit dans les données | [`docs/assistant-agent.md`](docs/assistant-agent.md) |
| L'ergonomie de `/activite` | [`docs/activite-ux.md`](docs/activite-ux.md) |
| Le pont vers Cadence Tabata — les liens de séance | [`docs/cadence.md`](docs/cadence.md) |
| Le `413` à l'ajout de captures — diagnostic et correctif | [`docs/bug-413-captures.md`](docs/bug-413-captures.md) |
| Les rappels push, de l'heure fixe à l'écart | [`docs/notifications-v2.md`](docs/notifications-v2.md) |
| Les charges d'une séance Cadence, et la spec v2 du lien | [`docs/charges.md`](docs/charges.md) |
| Les 1324 noms d'exercices de Cadence, par groupe — à donner à un modèle | [`docs/catalogue-cadence.md`](docs/catalogue-cadence.md) |
| La refonte de l'activité — tout par Cadence, la course à part | [`docs/refonte-activite.md`](docs/refonte-activite.md) |

[`docs/GuidelinesUI.html`](docs/GuidelinesUI.html) reste la **référence exclusive** de la
charte visuelle.

**Écrire un plan avant de coder** dès que le lot dépasse un correctif. Les documents
ci-dessus sont tous des plans écrits avant. Un plan dit ce qui change, pourquoi, et ce que
ça coûte — pas seulement quoi faire.

---

## 2. Les invariants — ce qu'une refonte ne doit pas casser

Sept règles. Elles ne portent pas sur l'apparence — tout est ouvert de ce côté — mais sur
ce que l'interface a le droit de **dire**. Chacune a coûté un incident.

**Aucun calcul métier côté client.** Moyennes, écarts, ratios, cadences, sommes : le
serveur calcule, le client formate. `features/<domaine>/api.ts` ne contient que des types
et des appels. Si un chiffre manque à l'écran, il s'ajoute **au service backend**.

**Aucune valeur inventée à l'écran.** Sur historique vide : un tiret et ce que coûte le
prochain geste, jamais un zéro qui passerait pour une mesure. Attention aux valeurs par
défaut d'un formulaire : `sets: '3'` écrit en dur est une valeur inventée, et il en traînait
trois. Quand une donnée peut être absente, **vérifier ce que le composant dessine dans ce
cas**, pas ce que l'écran croit lui demander.

**Le jour vient du serveur.** Jamais `new Date()` ni `toISOString().slice(0,10)` pour dater
une donnée. Le seul calcul de date qu'un écran s'autorise est de choisir quelle page
demander. Deux écrans ont déjà été corrigés pour ça.

**Une valeur proposée n'est pas une mesure.** Ce qu'un modèle rend est proposé : `AiBlock`
et l'état `proposed` du `Stepper`, et **rien d'autre**. Une cinquième façon de le dire
affaiblirait les quatre existantes. Un relevé passé rappelé à l'écran n'est *pas* une
proposition — ne pas le marquer comme tel.

**Les erreurs portent un code, pas un texte.** Le client décide sur `error.code`, jamais sur
le message. Le message vient du serveur, en français, et s'affiche tel quel.

**La garde `If-Match` sur toute modification et suppression** (`STO-05`). Le jeton se lit
sur la ligne, se renvoie en en-tête, et un conflit remonte à l'utilisateur — il ne se force
pas. Un `If-Match` absent est un **conflit**, jamais une permission.

**Le fichier de style suit le composant.** Une variante d'apparence va dans
`primitives.tsx` et son module, jamais en style en ligne dans un écran.

### Deux corollaires qui se ratent facilement

- **Toute écriture invalide son domaine et les vues transverses.** Sans
  `for (const key of CROSS_CUTTING)`, enregistrer une pesée laisse le tableau de bord mentir
  jusqu'à la prochaine navigation. `CROSS_CUTTING` = agrégats + assiduité.
- **`id` est la position de la ligne dans le CSV**, pas une clé stable. Supprimer décale
  tout ce qui suit. C'est `If-Match` qui rattrape — d'où son caractère non négociable.
  Les identifiants **stables** (`workout_id`, `exercise_id`) sont des colonnes à part, et
  une correction ne doit **jamais** en régénérer un : le journal s'y rattache.

---

## 3. Mobile d'abord — les chiffres

Cible d'usage principale : **iPhone 16 Pro, 402 × 874 px CSS**. Les feuilles de style
s'écrivent pour **390 px** — c'est le plancher, pas la cible.

| Règle | Valeur |
|---|---|
| Plancher de toute cible | `--tap` = **44 px** |
| Action qui **termine** un geste | `--tap-lg` = **56 px** |
| Champ de saisie | **16 px** minimum, sinon iOS zoome et décale la page |
| Seuil de glissement | `--swipe-threshold` = **56 px** |
| Plancher de texte | **12 px** |
| Points de rupture | **deux**, `600` et `960`, tous deux en `min-width` |

**Trois règles encadrent le glissement**, chacune payée :

- **Un geste n'est jamais la seule porte.** Ce qu'un glissement révèle existe dans le
  document et s'affiche d'emblée sous `(pointer: fine)`.
- **Un geste plus vertical qu'horizontal appartient à la page.** Sans cette garde, faire
  défiler au pouce déclencherait l'action — qui, sur l'historique, est une suppression.
- **Le glissement navigue, il ne mesure pas.** Pas de curseur pour une charge.

Une seule implémentation : [`lib/swipe.ts`](frontend/src/lib/swipe.ts). Deux en donneraient
deux seuils.

**Deux appuis pour détruire.** Le projet n'a aucune annulation. `SwipeRow` porte le motif —
glissement pour révéler, premier appui qui arme, second qui exécute. Le réemployer, ne pas
inventer un second vocabulaire. Une **addition**, elle, se défait (c'est la suppression que
l'utilisateur ferait) : elle n'a pas à être confirmée. Demander confirmation partout finit
par la faire ignorer là où elle compte.

**Aucune couleur en dur.** Tout passe par [`styles/tokens.css`](frontend/src/styles/tokens.css),
qui porte deux thèmes. Une couleur se change **par paires** : `--x` et `--x-rgb`.

---

## 4. L'architecture, en un écran

```
backend/app/domains/<domaine>/     models.py · schemas.py · service.py · router.py
                                   models = le CSV · schemas = l'API · service = les calculs
                                   router = mince, valide et délègue

frontend/src/styles/tokens.css     les valeurs      couleurs, espacements, tailles, cibles
frontend/src/styles/base.css       le socle         reset, .wrap, .stack, .row, .grid
frontend/src/components/ui/        les composants   primitives.tsx · data.tsx · Sheet · Chart
frontend/src/features/<d>/api.ts   types + appels, aucun calcul
frontend/src/routes/<Écran>.tsx    assemblage seulement — aucune valeur décidée ici
```

Un écran importe **toujours** depuis `@/components/ui`, jamais depuis
`@/components/ui/primitives`.

**Quatre états par écran, jamais trois** : chargement, vide, erreur, données. L'état vide
dit ce que coûte le prochain geste et n'affiche aucune valeur inventée.

**Le conteneur de page** est `cx('wrap', styles.screen)`. En oublier un désaligne le
contenu de l'en-tête — le défaut a été trouvé deux fois, jamais par un test.

Un écran qui dépasse ~800 lignes se découpe en `routes/<écran>/`, comme `routes/settings/`
et `routes/activity/`.

---

## 5. Vérifier

### Ce que `make check` couvre

```bash
make check     # ruff, ruff format, mypy (157 fichiers), 1 120 tests backend
               # prettier, eslint, tsc, 285 tests d'écran
```

Il doit être vert **avant** de commiter, sans exception.

### Ce qu'il ne couvre pas, et qui trouve tout le reste

Un test vérifie ce qu'on a pensé à vérifier. **Sur les cinq derniers lots, la moitié des
défauts sont sortis en regardant la page, et zéro de la batterie.** Le dernier lot en date :
douze écrans à `0 défaut mesurable`, et six défauts visibles à l'œil en dix secondes.

```bash
make dev                                    # VÉRIFIER le port annoncé par Vite
node scripts/audit-mobile.mjs --base http://localhost:<port> --token "<jeton>"

# et l'autre thème, captures à part — sans --theme, on ne regarde qu'une moitié
node scripts/audit-mobile.mjs --base http://localhost:<port> --token "<jeton>" \
  --theme light --shots audit-shots-clair
```

Un jeton :

```bash
cd backend && .venv/bin/python -c "from app.config import get_settings; \
from app.core.security import TokenIssuer; s=get_settings(); \
print(TokenIssuer(s).issue(s.auth_username).access_token)"
```

**Puis regarder les captures.** C'est l'étape qui rapporte, pas celle qu'on saute.

### Les surfaces qui n'existent qu'après un appui

`audit-mobile.mjs` ne touche à rien — délibérément : un script qui clique au hasard sur des
données réelles finit par en supprimer. Mais une cible qui n'entre dans le DOM qu'après un
appui n'est donc jamais dans son compte. C'est ainsi qu'une poignée de `Sheet` est restée à
32 px sur six surfaces pendant que les douze écrans affichaient `0 cible < 44 px`.

```bash
node scripts/audit-surfaces.mjs --base http://localhost:<port> --token "<jeton>"
```

Il ouvre huit feuilles — saisie rapide, « Plus », les trois de `/activite`, les deux de
`/assistant` — à **402, 390 et 360 px**, et les mesure. Il ne redéfinit rien : la sonde, le
pilotage et les planchers viennent de `audit-mobile.mjs`, qui les exporte. Chaque appui est
déclaré nommément dans sa table `SURFACES` ; il ne remplit aucun champ et n'arme aucune
destruction.

**Quand une feuille est ajoutée à l'application, elle s'ajoute à cette table.** Sans quoi
elle rejoint l'angle mort d'où celle-ci vient de sortir.

### Deux limites qui restent

1. **L'audit mesure une seule largeur** (402). Les feuilles de style visent 390, et un
   petit Android fait 360 — `audit-surfaces.mjs` couvre les trois, l'autre non.
2. **Sa capture pleine page peut partir d'une position défilée.** Pour regarder le haut
   d'un écran, capturer soi-même après `window.scrollTo(0, 0)`.

### Piloter le navigateur, sans rien installer

Chrome en CDP depuis le `WebSocket` natif de Node — ni Playwright, ni `ws`, ni Puppeteer.

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --remote-debugging-port=9222 --no-first-run --user-data-dir=/tmp/metric-audit
```

Puis `Emulation.setDeviceMetricsOverride` à 402 × 874 DPR 3,
`localStorage.setItem('metric.token', …)` sur l'origine de l'app, et naviguer.

**Deux pièges mesurés :**

- `base.css` pose `scroll-behavior: smooth`. Le rectangle lu juste après `scrollIntoView`
  est celui d'**avant** le défilement — un appui s'y fiant tombe hors écran et ne prouve
  rien. Défiler en `behavior: 'instant'`, attendre, puis relire.
- Pour éprouver un geste tactile, `Input.dispatchTouchEvent` et **non**
  `dispatchMouseEvent` : `touchOnly` désactive les gestes à la souris, ce qui masque
  exactement ce qu'on cherche.

### Quand le stockage réel est injoignable

Une doublure d'API en `http.server` de la bibliothèque standard, sur un port libre, et
`METRIC_API_PORT=<port> npm run dev`. C'est ce qui permet de regarder les écrans sans
toucher aux vraies données. Filtrer `.sr-only` dans toute mesure de cibles, comme le fait
`audit-mobile.mjs` — deux filtres différents donneraient deux comptes pour la même page.

### Nettoyer

`lsof -ti:<port> -sTCP:LISTEN | xargs kill`, et Chrome **par son `--user-data-dir`** —
jamais `pkill -f "Google Chrome"`, qui emporterait le navigateur de l'utilisateur. Ne pas
tuer de processus qu'on n'a pas démarré soi-même.

---

## 6. Méthode

- **Lire avant d'écrire.** Le motif existe presque toujours déjà ailleurs dans le dépôt :
  corriger une ligne, c'est `/corps` ; gérer une petite collection, c'est le carnet de
  `/assistant` ; détruire, c'est `SwipeRow`. Réemployer plutôt qu'inventer un deuxième
  vocabulaire pour la même chose.
- **Commenter le pourquoi, jamais le quoi.** Le dépôt commente les décisions et ce
  qu'elles ont coûté. Suivre cette densité.
- **Dire ce qu'on n'a pas fait.** Un défaut trouvé et laissé se nomme, avec sa raison.
  Élargir le périmètre sans le dire est pire que le laisser.
- **Ne pas commiter le travail en cours de l'utilisateur** avec le sien. Vérifier
  `git status` en début de session ; si l'arbre est sale, proposer un commit de sauvegarde
  d'abord.

### Les commits

Français, préfixe conventionnel, sujet qui dit la **décision** et non le fichier touché —
`fix(sto): un verrou tenu n'est pas une panne passagère`. Le corps explique le diagnostic,
ce qui a été mesuré, ce qui a été écarté et pourquoi, et finit par ce qui a été vérifié.

---

## 7. Ce qui est ouvert

À prendre pour lui-même, pas en passant.

| Sujet | État |
|---|---|
| `LogButton` casse les noms longs sur trois lignes, hauteurs inégales dans la grille | vu en capture sur `/activite` ; correction dans `primitives.tsx`, vaut aussi pour la saisie rapide |
| Calculs métier côté client sur `/activite` | la tuile « Tonnage » somme `data.muscles[]`, deux `Bars` dérivent leur ratio d'un `Math.max` |
| **Huit** écrans encore sur `className="wrap"` au lieu de `cx('wrap', styles.screen)` | `.wrap .wrap` neutralise la conséquence visible en attendant |
| Trois styles en ligne dans `routes/settings/Tracks.tsx` | `marginTop: 14`, qui contournent l'échelle `--s1`…`--s8` |
| `Tracks.tsx` (856 l.) et `Planning.tsx` (877 l.) | à découper par section |
| Aucun écran n'a jamais été touché sur un **vrai téléphone** | l'émulation ne reproduit ni le pouce, ni le clavier système, ni la latence |

**Un point d'environnement** : une instance d'API tourne parfois depuis plusieurs jours sur
le port 8000 avec un stockage Nextcloud devenu injoignable. Symptôme : `storage_unavailable`
ou un écran bloqué sur « Chargement… ». Redémarrer l'API avant de conclure à une régression.
