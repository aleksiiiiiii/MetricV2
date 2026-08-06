# Le front de Metric — carte et mode d'emploi

Document de travail pour **modifier l'interface**. Il dit où sont les pages, ce que chaque
couche a le droit de décider, et par quel fichier passer selon ce qu'on veut changer.

Il ne remplace pas `GuidelinesUI.html`, qui reste la **référence exclusive** de la charte,
ni le §2 de [`etat-du-projet.md`](etat-du-projet.md), qui porte les invariants. Il les
rend praticables.

> **À lire avant une refonte** : la [§7](#7--ce-quune-refonte-ne-doit-pas-casser) liste les
> six règles qui ont chacune coûté un incident. Ce sont les seules choses non négociables ;
> tout le reste est ouvert.

---

## 1. Les douze pages

Toutes les adresses de l'application, dans l'ordre de la navigation.

| Adresse | Écran | Feuille de style | Données |
|---|---|---|---|
| `/connexion` | [Login.tsx](../frontend/src/routes/Login.tsx) | [Login.module.css](../frontend/src/routes/Login.module.css) | `lib/api.ts` |
| `/` | [Dashboard.tsx](../frontend/src/routes/Dashboard.tsx) | [Dashboard.module.css](../frontend/src/routes/Dashboard.module.css) | [aggregates/api.ts](../frontend/src/features/aggregates/api.ts) |
| `/corps` | [Body.tsx](../frontend/src/routes/Body.tsx) | [Body.module.css](../frontend/src/routes/Body.module.css) | [body/api.ts](../frontend/src/features/body/api.ts) |
| `/activite` | [Activity.tsx](../frontend/src/routes/Activity.tsx) | [Activity.module.css](../frontend/src/routes/Activity.module.css) | [activity/api.ts](../frontend/src/features/activity/api.ts) · [imports/api.ts](../frontend/src/features/imports/api.ts) |
| `/planning` | [Planning.tsx](../frontend/src/routes/Planning.tsx) | [Planning.module.css](../frontend/src/routes/Planning.module.css) | [planning/api.ts](../frontend/src/features/planning/api.ts) |
| `/objectif` | [Goals.tsx](../frontend/src/routes/Goals.tsx) | [Goals.module.css](../frontend/src/routes/Goals.module.css) | [goals/api.ts](../frontend/src/features/goals/api.ts) |
| `/assistant` | [Assistant.tsx](../frontend/src/routes/Assistant.tsx) | [Assistant.module.css](../frontend/src/routes/Assistant.module.css) | [assistant/api.ts](../frontend/src/features/assistant/api.ts) |
| `/routine` | [Routine.tsx](../frontend/src/routes/Routine.tsx) | [Routine.module.css](../frontend/src/routes/Routine.module.css) | [routine/api.ts](../frontend/src/features/routine/api.ts) |
| `/nutrition` | [Nutrition.tsx](../frontend/src/routes/Nutrition.tsx) | [Nutrition.module.css](../frontend/src/routes/Nutrition.module.css) | [nutrition/api.ts](../frontend/src/features/nutrition/api.ts) |
| `/assiduite` | [Assiduity.tsx](../frontend/src/routes/Assiduity.tsx) | [Assiduity.module.css](../frontend/src/routes/Assiduity.module.css) | [heatmap/api.ts](../frontend/src/features/heatmap/api.ts) |
| `/reglages` | [Settings.tsx](../frontend/src/routes/Settings.tsx) | [Settings.module.css](../frontend/src/routes/Settings.module.css) | [settings/api.ts](../frontend/src/features/settings/api.ts) |
| `/_kitchen-sink` | [KitchenSink.tsx](../frontend/src/routes/KitchenSink.tsx) | [KitchenSink.module.css](../frontend/src/routes/KitchenSink.module.css) | — |

Plus deux écrans sans adresse propre : [NotFound.tsx](../frontend/src/routes/NotFound.tsx)
sur `*`, et `SessionLoading` — exporté par [Shell.tsx](../frontend/src/app/Shell.tsx) —
pendant la vérification du jeton au démarrage.

Un sous-dossier : [routes/settings/](../frontend/src/routes/settings/) regroupe les
sections de l'écran Réglages, qui en porte deux depuis le L11
([Tracks.tsx](../frontend/src/routes/settings/Tracks.tsx), 856 lignes — le réglage des
pistes d'assiduité).

### Ce qu'il faut savoir sur trois d'entre elles

**`/_kitchen-sink` est publique et hors navigation.** Aucune donnée utilisateur : elle
s'ouvre sans session, depuis n'importe quel appareil, et se vérifie par capture
automatisée. Elle a quitté la barre au lot L14, faute de place. **C'est la page à ouvrir en
premier pendant une refonte** : elle montre chaque composant dans tous ses états, et un
changement de token s'y voit immédiatement.

**`/reglages` porte le réglage des pistes** et non `/assiduite` : la piste mise en avant
*est* le réglage `heatmap_metric`, et les séparer obligerait à expliquer deux fois où se
règle la même chose.

**`/assistant` n'a pas d'entrée de navigation non plus.** On y entre par une carte du
tableau de bord et un lien de l'écran Objectif. La barre demandait déjà 806 px pour 695
disponibles ; une dixième entrée l'aurait portée à ~897. Le coût est réel — c'est l'écran
qu'on ouvre pour poser une question, donc souvent — et il est assumé jusqu'à `L17-07`.

### Le routage

[App.tsx](../frontend/src/App.tsx) — trois niveaux :

```
/connexion         hors coquille : ni navigation ni déconnexion à afficher
/_kitchen-sink     hors coquille et hors session
tout le reste      RequireAuth → Shell → <Outlet />
```

Ajouter une page = une ligne dans `App.tsx`, et **peut-être** une entrée dans `NAV`
([Shell.tsx:31](../frontend/src/app/Shell.tsx#L31)). Peut-être seulement : la barre demande
806 px pour 695 disponibles, et les deux dernières pages ajoutées s'en sont passées — voir
[§6](#6--létat-des-lieux-mesuré).

---

## 2. Les cinq couches, et qui décide quoi

Chaque couche ne décide que ce qui lui appartient. C'est ce qui permet de changer une
couleur partout d'une ligne, et c'est aussi pourquoi certaines modifications qui semblent
locales n'ont rien à faire dans un écran.

```
1. tokens.css      les valeurs      couleurs, espacements, rayons, cibles tactiles
2. base.css        le socle         reset, typographie, primitives de mise en page
3. primitives.tsx  les composants   bouton, carte, champ, badge… + leur CSS Module
4. data.tsx        les affichages   anneau, barres, tableau, sparkline, checklist
5. routes/*.tsx    les écrans       assemblage seulement — aucune valeur décidée ici
```

| Fichier | Rôle | Ce qu'on n'y met **jamais** |
|---|---|---|
| [tokens.css](../frontend/src/styles/tokens.css) | Toutes les valeurs, nommées | une valeur utilisée une seule fois |
| [base.css](../frontend/src/styles/base.css) | Reset, `h1`–`h3`, `.wrap`, `.stack`, `.row`, `.spread`, `.grid` | un composant |
| [fonts.css](../frontend/src/styles/fonts.css) | `@font-face`, **généré** par `npm run fonts` | quoi que ce soit à la main |
| [primitives.tsx](../frontend/src/components/ui/primitives.tsx) | Les 16 composants de la charte | un appel réseau, un calcul métier |
| [data.tsx](../frontend/src/components/ui/data.tsx) | Les 8 affichages de données | une dérivation — les chiffres arrivent calculés |
| [Chart.tsx](../frontend/src/components/ui/Chart.tsx) · [Heatmap.tsx](../frontend/src/components/ui/Heatmap.tsx) | Les deux gros composants graphiques | idem |
| [index.ts](../frontend/src/components/ui/index.ts) | **Le seul point d'import** des composants | — |

Un écran importe **toujours** depuis `@/components/ui`, jamais depuis
`@/components/ui/primitives`. C'est ce qui permet de déplacer ou de découper un composant
sans toucher aux douze écrans.

### L'inventaire des composants

**Primitives** — `Eyebrow` · `Rule` · `Button` (`primary`/`ghost`/`quiet`) · `LogButton` ·
`Card` · `CardHead` · `Badge` · `Field` · `Stepper` · `Chip` · `ChipStrip` · `SwipeRow` ·
`Segmented` · `Empty` · `AiBlock`

**Données** — `Stat` · `Sparkline` · `Bars` · `Progress` · `Ring` · `Table` · `CheckGroup` ·
`Check`

**Gros composants** — `Chart` (séries, superpositions, bande, contexte) · `Heatmap`
(grille annuelle, cadences hebdomadaires, infobulle) · `Toaster`

Quatre tons partout, et ils ont un sens fixé par la charte : `signal` (mesure, neutre),
`effort` (série tenue), `load` (seuil approché), `recover` (dette, alerte).

---

## 3. « Je veux changer… » — par où passer

| Ce que tu veux changer | Le fichier | Portée |
|---|---|---|
| Une couleur, un rayon, un espacement | `styles/tokens.css` | **toute l'application** |
| La police | `styles/fonts.css` **et** `--display` / `--mono` | toute l'application |
| La taille des titres, le corps de texte | `styles/base.css` | toute l'application |
| Les marges de page, la largeur de lecture | `.wrap` dans `base.css`, `--wrap` dans les tokens | toute l'application |
| L'apparence d'un bouton, d'une carte, d'un champ | `components/ui/primitives.module.css` | tous les écrans |
| Le comportement d'un composant | `components/ui/primitives.tsx` | tous les écrans |
| **Ajouter** un composant | `primitives.tsx` + son CSS + `index.ts` | — |
| Un anneau, un tableau, des barres | `components/ui/data.tsx` + `data.module.css` | tous les écrans |
| La barre du haut, le pied, la navigation | `app/Shell.tsx` + `Shell.module.css` | toute l'application |
| La mise en page **d'un seul écran** | `routes/<Écran>.module.css` | cet écran |
| Ce qu'un écran affiche | `routes/<Écran>.tsx` | cet écran |
| Une adresse, une nouvelle page | `App.tsx` + `Shell.tsx` (`NAV`) | — |
| Le texte d'une erreur | **le backend** — `app/core/exceptions.py` | — |
| Un chiffre, une moyenne, un ratio | **le backend** — le service du domaine | — |

Les deux dernières lignes ne sont pas une commodité de rangement : voir la
[§7](#7--ce-quune-refonte-ne-doit-pas-casser).

### Le patron d'un écran

Les douze écrans suivent la même forme. En reprendre un revient à respecter quatre points :

```tsx
export function Écran() {
  const { data, isPending, error } = useQuery({ queryKey: keys.<domaine>.…, queryFn: … });

  return (
    <div className={cx('wrap', styles.screen)}>   {/* 1. conteneur de page */}
      {isPending && <Card>Chargement…</Card>}      {/* 2. quatre états, jamais trois */}
      {error !== null && <Card><Empty …/></Card>}
      {data && <>…</>}
    </div>
  );
}
```

1. **`wrap` + `styles.screen`** — `wrap` plafonne la largeur de lecture et pose les marges,
   `screen` gère l'empilement. En oublier un désaligne le contenu de l'en-tête ; le défaut
   a été trouvé deux fois, au L13 et au L14.
2. **Quatre états, jamais trois** : chargement, vide, erreur, données. L'état vide dit ce
   que coûte le prochain geste — « Un chiffre le matin, et la courbe commence » — et
   n'affiche **aucune valeur inventée**.
3. **Le message d'erreur vient du serveur** et s'affiche tel quel : il est déjà en
   français. Le client décide sur le `code`, jamais sur le texte.
4. **Toute écriture invalide son domaine et les vues transverses** :
   ```ts
   void client.invalidateQueries({ queryKey: keys.<domaine>.all() });
   for (const key of CROSS_CUTTING) void client.invalidateQueries({ queryKey: key });
   ```
   Sans cela, enregistrer une pesée laisse le tableau de bord mentir jusqu'à la prochaine
   navigation.

---

## 4. Mobile d'abord — les règles chiffrées

`L17-07` désigne le mobile comme **cible d'usage principale**. Depuis la `v0.12.2` cela se
traduit par des chiffres, plus par une intention.

| Règle | Valeur | Pourquoi |
|---|---|---|
| Plancher de toute cible | `--tap` = **44 px** | un doigt ne vise pas au pixel |
| Action qui **termine** un geste | `--tap-lg` = **56 px** | on la touche entre deux séries, sans regarder |
| Champ numérique | **16 px minimum** | en deçà, iOS zoome et décale la page |
| Seuil de glissement | `--swipe-threshold` = **56 px** | en deçà, c'est un appui qui a bougé |

**Les feuilles de style s'écrivent mobile d'abord** : les règles de base valent pour
390 px, les `min-width` ajoutent ce que la place permet. Les points de rupture employés
aujourd'hui sont `560`, `640`, `900` et `960 px` — quatre valeurs pour douze écrans, ce qui
est déjà une de trop (voir [§6](#6--létat-des-lieux-mesuré)).

**Trois règles encadrent le glissement**, et elles ont chacune coûté quelque chose :

- **Un geste n'est jamais la seule porte.** L'action qu'un glissement découvre existe
  toujours dans le document, et s'affiche d'emblée là où il y a un pointeur fin.
- **Un geste plus vertical qu'horizontal appartient à la page.** Sans cette garde, faire
  défiler une liste au pouce déclencherait son action — qui, sur l'historique, est une
  suppression.
- **Le glissement navigue, il ne mesure pas.** Pas de curseur pour une charge : viser
  82,5 kg au pouce est difficile, et une mesure fausse entrée sans s'en apercevoir coûte
  plus qu'un appui de plus.

Une seule implémentation : [lib/swipe.ts](../frontend/src/lib/swipe.ts). Deux en donneraient
deux seuils.

---

## 5. Vérifier un changement

### Ce que `make check` couvre

```bash
make check      # prettier, eslint, tsc --noEmit, vitest — 215 tests d'écran
```

### Ce qu'il ne couvre pas, et qui a trouvé tous les défauts des quatre derniers lots

Un test vérifie ce qu'on a pensé à vérifier. **Sur les quatre derniers lots, huit défauts
sont sortis en regardant la page, zéro de la batterie.** Le dernier en date était une
violation d'invariant : un anneau qui affichait « 0% » là où l'avancement était
indéterminé, sous 112 tests verts.

Recette de pilotage, sans rien installer et sans toucher aux vraies données :

```bash
# 1. une doublure d'API en http.server stdlib sur un port libre
python3 stub_api.py 53538 &

# 2. le frontend branché dessus — VÉRIFIER le port annoncé, 5173/5174 sont souvent pris
METRIC_API_PORT=53538 npm run dev

# 3. Chrome headless, piloté en CDP depuis Node — ni Playwright ni `ws`
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --remote-debugging-port=9222 \
  --no-first-run --user-data-dir=./chrome-profile
```

Puis, en CDP : `Emulation.setDeviceMetricsOverride` à 390 × 844,
`localStorage.setItem('metric.token', …)` sur l'origine de l'app, et naviguer.

**Les quatre mesures qui rapportent le plus** :

```js
// 1. toute cible sous le plancher tactile
[...document.querySelectorAll('a,button,input,select,textarea,summary')]
  .map(n => ({ t: n.textContent.trim(), h: n.getBoundingClientRect().height }))
  .filter(m => m.h < 44)

// 2. débordement horizontal
document.documentElement.scrollWidth > document.documentElement.clientWidth

// 3. champs qui feront zoomer iOS
[...document.querySelectorAll('input')].filter(n => parseFloat(getComputedStyle(n).fontSize) < 16)

// 4. alignement du contenu sur l'en-tête — c'est celle qui manquait
document.querySelector('header a').getBoundingClientRect().left
  === document.querySelector('main h2').getBoundingClientRect().left
```

**Et ensuite, regarder la capture.** Les trois défauts du L14 étaient une redite, un texte
d'invite copié du mauvais champ, et un pourcentage inventé : aucune mesure ne les
attrapait, l'œil les a vus en dix secondes.

Nettoyer par `lsof -ti:<port> -sTCP:LISTEN | xargs kill`, et tuer Chrome **par son
`--user-data-dir`** — jamais `pkill -f "Google Chrome"`, qui emporterait le navigateur de
l'utilisateur.

---

## 6. L'état des lieux, mesuré

Ce qui est vrai aujourd'hui, chiffres à l'appui. À traiter ou à assumer pendant une
refonte — ce sont des faits, pas des reproches.

### La barre de navigation déborde

**806 px demandés pour 695 disponibles**, mesurés entrée par entrée à 1280 px. Elle défile
horizontalement par conception, avec un dégradé de bord qui dit « ça continue ».

| Entrée | Largeur |
|---|---|
| Tableau de bord | **138,8 px** |
| Nutrition · Assiduité | 91,3 px |
| Activité · Planning · Objectif · Réglages | 83,4 px |
| Routine | 75,5 px |
| Corps | 59,6 px |

« Tableau de bord » pèse à lui seul **le sixième de la barre**. C'est le premier levier :
le raccourcir en « Accueil » rendrait ~80 px. Passer à un tiroir est l'autre piste. Les
deux sont des **décisions de produit** réservées à `L17-07`, pas des ajustements de mise en
page.

### Sept écrans sur douze n'ont pas eu la passe tactile

Traités en émulation : `/activite` (v0.12.2), `/planning` (L13), `/objectif` (L14),
`/assistant` (L14b). Restent `/`, `/corps`, `/routine`, `/nutrition`, `/assiduite`,
`/reglages`, `/connexion`.
Le détail de ce qu'il faut regarder sur chacun est au §3.2 de
[`verifications-manuelles.md`](verifications-manuelles.md).

**Et aucun écran n'a jamais été touché sur un vrai téléphone.** L'émulation ne reproduit
ni l'imprécision du pouce, ni le clavier système qui remonte sur le champ actif, ni la
latence.

### Trois incohérences à trancher

1. **63 styles en ligne** (`style={{…}}`) dans les écrans, dont une trentaine de
   `marginTop: 10` et de `<div style={{ height: 40 }} />` en guise d'espaceur. Ils
   contournent l'échelle `--s1`…`--s8`. Une refonte est le bon moment pour les remplacer
   par des classes.
2. **Quatre points de rupture** — 560, 640, 900, 960 px — pour douze écrans, dont deux en
   `max-width` (l'héritage) et deux en `min-width` (mobile d'abord). Deux valeurs
   suffiraient.
3. **Deux conventions de conteneur de page** : neuf écrans posent `className="wrap"` sur
   plusieurs blocs, trois (`/planning`, `/objectif`, `/assistant`) combinent `wrap` et un
   `styles.screen` qui gère l'empilement. La seconde est la plus récente et la plus
   lisible.

### Le poids des écrans

`Activity.tsx` fait **1383 lignes** et 12 sous-composants, `Tracks.tsx` 856,
`Planning.tsx` 877. Les trois gagneraient à être découpés en fichiers par section, comme
`routes/settings/` l'a fait. Aucun n'est bloquant.

### Ce qui est sain

Aucune couleur en dur hors de `KitchenSink.tsx`, qui les affiche **volontairement** comme
contenu — c'est la page qui documente la charte. Tout le reste passe par les tokens.

---

## 7. Ce qu'une refonte ne doit pas casser

Six règles. Elles ne portent pas sur l'apparence — tout est ouvert de ce côté — mais sur ce
que l'interface a le droit de **dire**. Chacune a coûté un incident.

### Aucun calcul métier côté client

Moyennes, écarts, séries, ratios, cadences : tout est calculé par le serveur. Le client
formate, il ne dérive pas. Deux implémentations d'une même moyenne divergent au premier cas
limite, et c'est l'utilisateur qui arbitre entre deux chiffres qui devraient être
identiques.

Corollaire pratique : `features/<domaine>/api.ts` ne contient que des types et des appels.
S'il faut un nouveau chiffre à l'écran, il s'ajoute **au service backend**.

### Aucune valeur inventée à l'écran

Sur historique vide : un tiret et ce que coûte le prochain geste — jamais un zéro qui
passerait pour une mesure. Un groupe musculaire jamais travaillé rend `null`, pas un grand
nombre.

**C'est la règle la plus facile à casser sans le voir.** Au L14, un anneau de progression
recevait `ratio: null`, l'écran choisissait de ne pas le colorer — et le composant
dessinait quand même « 0% » en son centre, parce qu'un anneau dessine un pourcentage.
Quatre décisions correctes, une page qui ment. **Quand une donnée peut être absente,
vérifier ce que le composant dessine dans ce cas, pas ce que l'écran croit lui demander.**

### Une valeur proposée n'est pas une mesure

Ce qu'un modèle rend est **proposé** : trait discontinu, teinte du bloc IA,
`aria-description`, corrigeable au doigt, et jamais écrit sans validation. Retoucher une
proposition la fait sienne, et la marque disparaît.

Le projet a **une seule** façon de le dire — `AiBlock` et l'état `proposed` du `Stepper` —
et quatre écrans l'emploient (`/nutrition`, `/activite`, `/planning`, `/objectif`). Une
cinquième façon affaiblirait les quatre premières.

### Le jour suit le fuseau local, jamais UTC

Ne jamais écrire `toISOString().slice(0,10)` ni `new Date()` pour dater une donnée. La date
du jour **vient du serveur** (`view.today`) ; le seul calcul de date qu'un écran s'autorise
est de choisir quelle page demander.

### Les erreurs portent un code, pas un texte

Le client décide sur `error.code`, jamais sur le message. Le message vient du serveur, en
français, et s'affiche tel quel. Reformuler un message ne casse rien ; tester un texte
casse au premier lot.

### Le fichier de style suit le composant

Une variante d'apparence s'ajoute dans `primitives.tsx` et son module — **jamais** en style
en ligne dans un écran. C'est ce qui permet qu'un changement de charte se voie partout, et
c'est la règle que les 63 `style={{…}}` actuels contournent.

---

## 8. Par où commencer

Dans cet ordre, du plus rentable au plus coûteux :

1. **Ouvrir `/_kitchen-sink`** et décider ce qui change dans la charte. Tout ce qui s'y
   voit se répercute sur les douze écrans sans les toucher.
2. **Les tokens**, s'il s'agit de couleurs, d'espacements ou de rayons. Une ligne, effet
   global, aucun risque de régression logique.
3. **Les primitives**, s'il s'agit de la forme d'un bouton ou d'une carte. Vérifier dans le
   kitchen sink, qui les montre dans tous leurs états.
4. **La coquille**, pour la navigation — en gardant en tête les 806 px.
5. **Un écran à la fois**, en profitant du passage pour lui faire sa passe tactile s'il ne
   l'a pas eue. Sept l'attendent.
6. **`make check`**, puis **la page dans un navigateur** — pas l'inverse, et jamais l'un
   sans l'autre.
