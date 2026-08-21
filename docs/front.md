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

## 0. Où en est la refonte mobile

Une refonte mobile d'abord est **en cours** sur la branche `refonte-mobile`, suivant le plan
de [`refonte-mobile.md`](refonte-mobile.md). Point de retour : `613739b` sur `main`.

Ce tableau est la seule source à jour. **Quand une case change, c'est ici qu'on l'écrit
d'abord** — les sections suivantes décrivent l'état d'avant et portent la mention
« dépassé » là où elles ne sont plus vraies.

| | Phase | État |
|---|---|---|
| **0** | [`scripts/audit-mobile.mjs`](../scripts/audit-mobile.mjs) — l'outil de mesure | ✅ **fait** |
| **A** | Socle — échelle typographique, gouttières, zones sûres, points de rupture | ✅ **fait** |
| **B** | Coquille — barre d'onglets basse, feuille « Plus », saisie rapide | ✅ **fait** |
| **C** | Primitives — survol protégé, états d'appui, tailles, `Chart`, `Heatmap` | ✅ **fait** |
| **D** | Les écrans — styles, tailles, points de rupture, `PageHead`, tuiles | ✅ **fait**, sauf `wrap`+`screen` |
| **E** | Finition — mouvement, états de chargement | ✅ **fait** |
| **V** | Vérification dans le navigateur à 402 × 874 | ✅ **12/12**, sauf `/objectif` — voir plus bas |

### Les compteurs, après la passe D

| | Avant | Après |
|---|---|---|
| Déclarations `font-size` en littéral, dans `routes/` | 101 | **1** — le spécimen de police de la charte |
| Styles en ligne dans `routes/` | 47 | **3** — une couleur et deux largeurs calculées |
| `:hover` hors garde de pointeur fin | 27 | **0** |
| Points de rupture distincts | 5 | **2** (`600`, `960`) |
| Tokens CSS appelés mais jamais déclarés | 2 | **0** |

### Ce qui est fait, en détail

**Phase A — le socle.** Huit tokens `--t-*` remplacent les littéraux de taille ; **rien ne
descend plus sous 12 px**, alors que 96 déclarations sur 169 étaient entre 9 et 12. Le corps
passe de 15 à 16 px, `h1` **descend** de 34 à 30 (un titre n'est pas une donnée). Gouttières
`--gutter` / `--card-pad` à 16 px sur téléphone — 16 px de largeur utile rendus au contenu.
`viewport-fit=cover` et `env(safe-area-inset-*)` posés, plus les balises qui font s'ouvrir
l'application sans la barre d'adresse depuis l'écran d'accueil. **Cinq points de rupture
ramenés à deux**, tous deux en `min-width`. `.rule` perd 34 px de marge sur mobile —
**170 px rendus** sur le seul tableau de bord.

> Les grilles `g2`/`g3`/`g4` sont d'abord passées à **deux colonnes par défaut**, puis
> revenues à une. La mesure a montré pourquoi : une `g2` porte presque toujours une carte
> avec un paragraphe et des contrôles, et deux de front dans 390 px donnent 131 px utiles
> — de quoi casser un `Stepper` en trois, ce qui s'est effectivement produit. Ce qui tient
> à deux de front, ce sont des **tuiles** : un libellé, un chiffre, une ligne. Elles ont
> leur classe, `.tiles`, et elle se pose tuile par tuile.

**Phase B — la coquille.** Nouveaux fichiers : [Sheet.tsx](../frontend/src/components/ui/Sheet.tsx),
[icons.tsx](../frontend/src/components/ui/icons.tsx),
[TabBar.tsx](../frontend/src/app/TabBar.tsx),
[QuickLog.tsx](../frontend/src/app/QuickLog.tsx). Sous 960 px, la navigation est **en bas**,
sous le pouce : `Accueil · Activité · Assistant · ⊕ · Plus` (Nutrition y était jusqu'au
lot L18). Le `⊕` écrit un verre d'eau, un
supplément ou une pesée **sans changer d'écran** ; un repas et une séance restent des liens,
parce qu'ils demandent un vrai formulaire. Au-delà de 960 px la barre du haut reprend la
main, avec « Tableau de bord » raccourci en « Accueil » — ~80 px rendus, la demande tombe de
806 à ~726.

**Phase C — les primitives.** Les 26 `:hover` non protégés sont passés sous
`@media (hover: hover)` : plus de bouton qui reste allumé après un appui sur iOS. `:active`
partout à la place, et `-webkit-tap-highlight-color: transparent` pour que le rectangle gris
du système ne se superpose plus aux états de la charte. `LogButton` et les touches du
`Stepper` passent à `--tap-lg`, la case à cocher de 16 à 22 px, les lignes de tableau à
44 px francs.

> **Un défaut trouvé au passage, invisible à la mesure du DOM.** Les étiquettes d'axe de
> `Chart` sont déclarées à 9 px — mais dans un `viewBox` de 720 unités rendu à ~336 px sur
> un téléphone, soit un facteur 0,47 : **elles arrivaient à l'écran en 4,2 px**. Une mesure
> du DOM lit « 9 » et ne voit rien. Il faut diviser par la largeur rendue. Corrigé par trois
> paliers calculés dans [Chart.module.css](../frontend/src/components/ui/Chart.module.css).

**Phase D — les écrans.** Les compteurs ci-dessus. Ajouté au passage :
[`PageHead`](../frontend/src/components/ui/primitives.tsx) — les huit écrans qui ont un
en-tête l'écrivaient à la main avec les mêmes trois styles en ligne. Et **deux défauts de
fond, sans rapport avec le mobile**, trouvés en passant :

- `/nutrition` datait sa page avec **`longDate(new Date())`** — l'horloge du téléphone, et
  non celle qui a daté les repas. C'est l'invariant « le jour vient du serveur », cassé
  depuis le lot qui a créé l'écran. Il lit `data.date` désormais.
- `/assiduite` appelait **`--surface-1` et `--r-md`, deux tokens qui n'ont jamais
  existé** : le tiroir de détail était donc transparent et à coins carrés, par-dessus la
  grille.

**Phase E — la finition.** Fondu d'entrée sur `<main>`, dont la clé suit l'adresse : c'est
ce qui rejoue l'animation à chaque navigation, sans bibliothèque de transition. Les jauges
se remplissent depuis zéro, en `transform` et non en `width` — une largeur animée refait la
mise en page à chaque image. Et l'en-tête reste affiché pendant le chargement et l'erreur,
sur les trois écrans qui rendaient une page nue.

Ce qui n'a **pas** été fait de la phase E : les états vides portent toujours le prochain
geste en mots — « Un chiffre le matin, et la courbe commence » — sans bouton qui ouvre la
feuille de pesée. Le `⊕` de la barre y mène en deux appuis depuis n'importe où, ce qui rend
le gain plus faible qu'il n'y paraissait quand le plan a été écrit.

### Ce qui reste

**La convention de conteneur de page.** **Huit** fichiers de `routes/` posent encore
`className="wrap"` au lieu du `cx('wrap', styles.screen)` de `/planning` — compté le
2026-08-13, le document en annonçait neuf. C'est le seul point
du plan volontairement **laissé de côté** : c'est un remaniement de mise en page dont le
défaut caractéristique — un contenu désaligné de l'en-tête — a été trouvé deux fois en
regardant, jamais par un test. Le faire sans pouvoir regarder les écrans serait le faire à
l'aveugle. En attendant, `.wrap .wrap` neutralise le retrait imbriqué, ce qui en supprime
la conséquence visible.

### Ce qui est vérifié, et ce qui ne l'est pas

| Vérification | État |
|---|---|
| `make check` — ruff, mypy (153 fichiers), 1043 tests backend | ✅ vert |
| `tsc`, `eslint`, `prettier`, 230 tests d'écran | ✅ vert |
| `audit-mobile.mjs` sur les douze écrans | ✅ **12/12 sans défaut mesurable** |
| Les douze écrans **regardés** à 402 × 874 | ✅ sauf `/objectif` |

**Ce que « regarder » a rapporté, chiffré.** Environ **vingt-cinq défauts** sur les douze
écrans. La moitié sortait de l'audit ; l'autre moitié n'était visible qu'en capture,
toutes les mesures étant au vert :

- le sélecteur de métrique du tableau de bord prenait **neuf lignes et 470 px** ;
- `.spread` essorait son paragraphe sur une demi-largeur de carte ;
- les étiquettes du graphique se chevauchaient — « J-29 » par-dessus « 5:00 » ;
- « Un chiffre le matin, et la courbe commence » s'affichait **sous une pesée de 60 kg** ;
- trois écrans rendaient une page nue pendant le chargement, sans même leur titre ;
- `/corps` affirmait « aucune pesée » **avant d'avoir lu l'historique** ;
- douze « 1 séance(s) », qui apparaissent précisément au premier jour d'usage.

**Et à la refonte du tableau de bord, six de plus — dont un qui touchait toute
l'application.** `make check` était vert, l'audit annonçait `14/14 sans défaut mesurable`,
et il restait :

- **toutes les jauges de l'application se peignaient pleines.** `Progress` et `Bars`
  posaient leur largeur avec `percent()`, qui rend « 56 % » : l'espace avant le signe est
  la typographie française, et c'est une largeur **invalide** que le navigateur jette sans
  rien dire. La barre retombait sur sa valeur par défaut. Une semaine à zéro s'affichait
  comme une semaine complète. Aucun test ne le voyait : ils regardaient tous le *texte*,
  et il était juste. [data.test.tsx](../frontend/src/components/ui/data.test.tsx) mesure
  désormais la barre ;
- la page **défilait horizontalement de 3 px à 360 px** — la grille des sept jours
  demandait 330 px pour 294 disponibles, le mois répété sept fois. L'audit ne mesure
  que 402 ;
- « ENCORE 54 G » : un `text-transform: uppercase` appliqué à une unité ;
- `45:00` pour une séance de 45 minutes — `duration()` est un chronomètre, pas une durée ;
- les mêmes deux nombres deux fois sur une ligne, en deux unités ;
- « Cette semaine » sur deux lignes quand « Poids » tenait sur une : trois chiffres censés
  se comparer, et pas de ligne de base commune ;
- **les étiquettes du graphique se chevauchaient** — « 28/05 » par-dessus « 11/06 ». Le pas
  entre deux dates était décidé par l'**écran** (`labelEvery={Math.ceil(points.length / 8)}`,
  sur `/` et sur `/corps`), qui ne connaît ni la largeur d'une étiquette ni l'écart entre
  deux points. Il vit maintenant dans
  [chart-axis.ts](../frontend/src/components/ui/chart-axis.ts), module pur, qui le déduit
  de la géométrie ; `labelEvery` survit comme **plancher**, jamais comme plafond.

**Le seul écran non vérifié : `/objectif`.** Il reste sur « Chargement de l'objectif… »
parce que **`/api/goals` et `/api/goals/weekly` ne répondent pas** — 25 s sans réponse,
mesurés en direct. Ce n'est pas la refonte : aucun fichier du backend n'a changé
(`git diff 613739b..HEAD -- backend/` est vide) et `make check` passe entièrement,
1043 tests compris. C'est l'instance qui tourne depuis la veille qui est en cause,
probablement sur une lecture Nextcloud. **À revérifier après un redémarrage de l'API.**

Pour rejouer l'audit :

```bash
make dev                                   # vérifier le port annoncé
node scripts/audit-mobile.mjs --base http://localhost:<port> --token "<jeton>"

# et l'autre thème, captures rangées à part — sans `--theme`, l'audit ne regarde
# qu'une moitié de l'application : Chrome en headless annonce « sombre ».
node scripts/audit-mobile.mjs --base http://localhost:<port> --token "<jeton>" \
  --theme light --shots audit-shots-clair
```

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

Deux sous-dossiers. [routes/dashboard/](../frontend/src/routes/dashboard/) porte les trois
sections nouvelles du tableau de bord — `Brief.tsx` (la lecture du jour), `Today.tsx` (la
journée à finir et la bande de chiffres), `Aim.tsx` (« où je vais ») — refonte décrite dans
[tableau-de-bord.md](tableau-de-bord.md). Et
[routes/settings/](../frontend/src/routes/settings/) regroupe les
sections de l'écran Réglages, qui en porte **trois** depuis le L15 —
[Tracks.tsx](../frontend/src/routes/settings/Tracks.tsx) (856 lignes, le réglage des pistes
d'assiduité) et [Reminders.tsx](../frontend/src/routes/settings/Reminders.tsx) (les rappels
push, `NOT-01` et `NOT-03`).

### La PWA — trois fichiers hors des douze pages

Le lot L15 ajoute une couche qui ne s'affiche nulle part et qu'il faut donc savoir trouver :

| Fichier | Rôle |
|---|---|
| [sw/strategy.ts](../frontend/src/sw/strategy.ts) | **Pur** : l'URL → la stratégie de cache. C'est là qu'est la règle, et elle est testée |
| [sw/index.ts](../frontend/src/sw/index.ts) | Le worker : cache, `push`, `notificationclick`. Aucune règle |
| [lib/push.ts](../frontend/src/lib/push.ts) | L'abonnement côté navigateur — permission, `pushManager`, base64url |
| [lib/pwa.ts](../frontend/src/lib/pwa.ts) | L'enregistrement du worker, **en production uniquement** |

Le worker est bâti à part (`vite.sw.config.ts`) vers `dist/sw.js`, sans empreinte dans le
nom. **Il ne s'enregistre pas en `make dev`** : il servirait des `/assets` périmés pendant
qu'on code. Pour l'éprouver : `npm run build`, puis `vite preview`.

> **La règle à ne pas casser** : tout ce qui commence par `/api` va au réseau, **sans
> repli**. Un écran servi du cache avec les chiffres d'hier est une valeur inventée à
> l'écran — et le pire cas, parce que la page a l'air normale. La décision vit dans une
> seule fonction pure ; une exception écrite ailleurs échapperait à ses seize assertions.

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

> **Dépassé.** Sur mobile, `/assistant` **est un onglet plein** depuis le lot L18 —
> `Accueil · Activité · Assistant · ⊕ · Plus` —, et Nutrition est descendue dans la
> feuille. C'est le seul écran qu'on ouvre pour *parler*, et depuis qu'il sait écrire dans
> les données il est aussi la porte la plus courte vers la plupart des gestes ; Nutrition
> demande un formulaire que rien n'abrège, et le `⊕` couvre déjà ce qui se saisit en un
> chiffre. Sur ordinateur, rien ne change : il reste hors de la barre du haut.

### Le routage

[App.tsx](../frontend/src/App.tsx) — trois niveaux :

```
/connexion         hors coquille : ni navigation ni déconnexion à afficher
/_kitchen-sink     hors coquille et hors session
tout le reste      RequireAuth → Shell → <Outlet />
```

Ajouter une page = une ligne dans `App.tsx`, et **deux entrées à décider, pas une** depuis
la phase B :

* `NAV` dans [Shell.tsx](../frontend/src/app/Shell.tsx) — la barre d'ordinateur, au-delà de
  960 px. Elle demande ~726 px pour ~708 : une entrée de plus se paie.
* `TABS` ou `MORE` dans [TabBar.tsx](../frontend/src/app/TabBar.tsx) — le téléphone.
  `TABS` est **plein à trois destinations** et le restera ; toute page nouvelle va dans
  `MORE`, qui n'a pas de limite parce qu'une feuille défile.

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

> `AiBlock` accepte depuis la refonte du tableau de bord un **corps tappable** (`onOpen`,
> `hint`) : le texte devient la cible, et la rangée d'actions reste en dehors — un bouton
> imbriqué dans un autre déclencherait les deux. Le tag, la pastille et la teinte ne
> bougent pas : c'est le même bloc, pas une cinquième façon de dire « proposé ».
>
> `Progress` accepte `bare`, qui retire le compte brut à droite. Quand la ligne au-dessus
> dit déjà « 1,4 L / 2,5 L », `1400 / 2500` écrit les mêmes deux nombres une seconde fois.

**Données** — `Stat` · `Sparkline` · `Bars` · `Progress` · `Ring` · `Table` · `CheckGroup` ·
`Check`

**Gros composants** — `Chart` (séries, superpositions, bande, contexte) · `Heatmap`
(grille annuelle, cadences hebdomadaires, infobulle) · `Toaster`

**Ajoutés en phase B** — `Sheet` · `SheetRow` · `SheetGroup`
([Sheet.tsx](../frontend/src/components/ui/Sheet.tsx)), et les treize pictogrammes de
[icons.tsx](../frontend/src/components/ui/icons.tsx). Les icônes sont **le seul module de
`components/ui/` qui ne s'importe pas par `index.ts`** : elles ne sont pas des composants
de charte mais le vocabulaire d'une seule surface, la barre d'onglets.

Quatre tons partout, et ils ont un sens fixé par la charte : `signal` (mesure, neutre),
`effort` (série tenue), `load` (seuil approché), `recover` (dette, alerte).

---

## 3. « Je veux changer… » — par où passer

| Ce que tu veux changer | Le fichier | Portée |
|---|---|---|
| Une couleur, un rayon, un espacement | `styles/tokens.css` | **toute l'application** |
| Une couleur **du thème clair** | `tokens.css`, bloc `:root[data-theme='light']` | le thème clair |
| Comment le thème est choisi ou retenu | [lib/theme.ts](../frontend/src/lib/theme.ts) | — |
| La police | `styles/fonts.css` **et** `--display` / `--mono` | toute l'application |
| La taille des titres, le corps de texte | `styles/base.css` | toute l'application |
| Les marges de page, la largeur de lecture | `.wrap` dans `base.css`, `--wrap` dans les tokens | toute l'application |
| L'apparence d'un bouton, d'une carte, d'un champ | `components/ui/primitives.module.css` | tous les écrans |
| Le comportement d'un composant | `components/ui/primitives.tsx` | tous les écrans |
| **Ajouter** un composant | `primitives.tsx` + son CSS + `index.ts` | — |
| Un anneau, un tableau, des barres | `components/ui/data.tsx` + `data.module.css` | tous les écrans |
| La barre du haut (**ordinateur seulement**) | `app/Shell.tsx` + `Shell.module.css` | ≥ 960 px |
| La barre d'onglets basse, la feuille « Plus » | `app/TabBar.tsx` + `TabBar.module.css` | < 960 px |
| Ce que le bouton `⊕` sait écrire | `app/QuickLog.tsx` | < 960 px |
| Une taille de texte | **`styles/tokens.css`**, bloc `--t-*` | toute l'application |
| Une marge de page, un retrait de carte | `--gutter` / `--card-pad` dans les tokens | toute l'application |
| La mise en page **d'un seul écran** | `routes/<Écran>.module.css` | cet écran |
| Ce qu'un écran affiche | `routes/<Écran>.tsx` | cet écran |
| Une adresse, une nouvelle page | `App.tsx` + `Shell.tsx` (`NAV`) | — |
| Ce qui est mis en cache hors ligne | `src/sw/strategy.ts` — **et nulle part ailleurs** | toute l'application |
| Ce qu'une notification affiche | **le backend** — `domains/notifications/reminders.py` | — |
| Le texte d'une erreur | **le backend** — `app/core/exceptions.py` | — |
| Un chiffre, une moyenne, un ratio | **le backend** — le service du domaine | — |

Les deux dernières lignes ne sont pas une commodité de rangement : voir la
[§7](#7--ce-quune-refonte-ne-doit-pas-casser).

### Les deux thèmes

Le sombre est celui de `GuidelinesUI.html` et reste le défaut de `:root`. Le clair est une
**seconde table de valeurs** dans le même fichier, sous `:root[data-theme='light']` : il
n'écrase que ce qui dépend de la clarté du fond — surfaces, encres, les quatre tons, et
les opacités qui en dérivent. Il n'ajoute aucun token et n'en retire aucun.

Quatre points valent d'être connus avant d'y toucher :

* **Aucune règle ne consulte `prefers-color-scheme`.** Le mode est résolu une fois, en
  JavaScript, et posé en `data-theme` sur `<html>` — par le script en tête d'`index.html`
  avant la première peinture, puis par `ThemeProvider`. Deux résolutions, une en CSS et
  une en JS, donneraient deux réponses le jour où l'une changerait.
* **Les quatre tons gardent leur sens et leur ordre.** `signal` mesure, `effort` tient,
  `load` approche, `recover` alerte. Même teinte à ±2°, saturation relevée, luminance
  descendue de moitié : c'est ce qu'il faut pour tenir le même contraste sur blanc.
* **Une couleur se change par paires.** `--x` et `--x-rgb` : le texte lit la première, tout
  ce qui dérive une opacité lit la seconde. Les désaccorder donne un badge d'une couleur et
  son libellé d'une autre, sans que rien ne casse.
* **Les opacités de heatmap ne sont pas transposables.** Sur fond sombre, la cellule vide
  est plus sombre que le dégradé et les deux séries divergent ; sur fond clair elles vont
  toutes deux vers le sombre et se disputent le haut de l'échelle. Reprendre `0.2` en clair
  colle le niveau 1 à la cellule vide — **ΔL\* 4, invisible sur un carré de 12 px**. D'où
  `0.35 / 0.57 / 0.79 / 1`, qui tient un pas minimal de **ΔL\* 12,4** sur les quatre tons.

[`styles/tokens.test.ts`](../frontend/src/styles/tokens.test.ts) garde les quatre : accord
hex/RVB, aucun token de couleur oublié dans le clair, séparation des niveaux de heatmap, et
les seuils de contraste. Il lit la feuille de tokens comme une table de valeurs — il ne
rend aucun composant.

> **Deux écarts connus, portés par la charte sombre et hors périmètre du thème clair** :
> `--ink-low` tient 3,4:1 sur `--bg` (AA en demande 4,5) et le badge `recover` 4,2:1. Ils
> sont nommés dans le test avec leur valeur actuelle pour plancher : ils ne peuvent plus
> empirer, et le thème clair, lui, passe partout — `--ink-low` y vaut 4,9:1.

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
390 px, les `min-width` ajoutent ce que la place permet.

> **Dépassé depuis la phase A.** Les points de rupture sont maintenant **deux**, tous deux
> en `min-width` : **600 px** et **960 px**, définis en tête de
> [tokens.css](../frontend/src/styles/tokens.css). Les cinq valeurs d'avant — `560`, `640`,
> `760`, `900`, `960`, dont trois en `max-width` — n'existent plus dans `styles/`,
> `components/` ni `app/`. Elles subsistent dans les feuilles de `routes/`, que la phase D
> n'a pas encore traitées.
>
> S'ajoutent quatre chiffres qui décrivent l'appareil cible, un iPhone 16 Pro :
> **402 × 874 px CSS**, 59 px d'îlot dynamique, 34 px d'indicateur d'accueil.

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

// 5. texte d'un SVG mis à l'échelle : la seule taille qui ment (phase C)
//    Une déclaration `font-size: 9px` dans un `viewBox` de 720 rendu à 336 arrive à
//    l'écran en 4,2 px. `getComputedStyle` lit 9 et ne voit rien.
[...document.querySelectorAll('svg')].map(s => {
  const vb = s.viewBox.baseVal.width;
  if (!vb) return null;
  const facteur = s.getBoundingClientRect().width / vb;
  return [...s.querySelectorAll('text')].map(t =>
    parseFloat(getComputedStyle(t).fontSize) * facteur);
}).flat().filter(px => px !== null && px < 10)
```

Émuler en **402 × 874 à DPR 3** — la géométrie réelle d'un iPhone 16 Pro. Les feuilles de
style, elles, continuent de s'écrire pour 390 px : c'est le plancher, pas la cible.

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

> **Cette section décrit l'état d'avant la refonte.** Les quatre constats ci-dessous
> restent utiles comme point de comparaison ; chacun porte l'état où il en est.

### La barre de navigation déborde — ✅ traité (phase B)

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

> **Les deux ont été prises.** Sous 960 px la barre n'existe plus : c'est
> [TabBar](../frontend/src/app/TabBar.tsx) qui gouverne, cinq cibles en bas de l'écran, et
> le reste dans une feuille. Au-dessus de 960 px, la barre demeure avec « Accueil » à la
> place de « Tableau de bord » : **~726 px demandés pour ~708 disponibles**, ce que le
> dégradé de bord couvre. Les 806 px ne sont plus un argument valable nulle part.

### Sept écrans sur douze n'ont pas eu la passe tactile — ⏳ phase D

Traités en émulation : `/activite` (v0.12.2), `/planning` (L13), `/objectif` (L14),
`/assistant` (L14b). Restent `/`, `/corps`, `/routine`, `/nutrition`, `/assiduite`,
`/reglages`, `/connexion`.
Le détail de ce qu'il faut regarder sur chacun est au §3.2 de
[`verifications-manuelles.md`](verifications-manuelles.md).

**Et aucun écran n'a jamais été touché sur un vrai téléphone.** L'émulation ne reproduit
ni l'imprécision du pouce, ni le clavier système qui remonte sur le champ actif, ni la
latence.

### Trois incohérences à trancher

1. **60 styles en ligne** (`style={{…}}`) dans les écrans — le document en annonçait 63,
   le compte exact est 60 —, dont une trentaine de `marginTop: 10` et de
   `<div style={{ height: 40 }} />` en guise d'espaceur. Ils contournent l'échelle
   `--s1`…`--s8`. — ⏳ **phase D**, sauf les deux de `primitives.tsx` et le `height: 40` de
   fin de page, que le dégagement de la barre d'onglets rend inutile.
2. ~~**Quatre points de rupture**~~ — ✅ **traité en phase A** : deux valeurs, `600` et
   `960`, toutes deux en `min-width`. Reste à propager dans `routes/` (phase D).
3. **Deux conventions de conteneur de page** : neuf écrans posent `className="wrap"` sur
   plusieurs blocs, trois (`/planning`, `/objectif`, `/assistant`) combinent `wrap` et un
   `styles.screen` qui gère l'empilement. La seconde est la plus récente et la plus
   lisible. — ⏳ **phase D**. En attendant, `.wrap .wrap` neutralise le retrait imbriqué,
   pour qu'un écran qui empile plusieurs blocs ne double pas sa marge latérale.

### Le poids des écrans

`Activity.tsx` fait **1383 lignes** et 12 sous-composants, `Tracks.tsx` 856,
`Planning.tsx` 877. Les trois gagneraient à être découpés en fichiers par section, comme
`routes/settings/` l'a fait. Aucun n'est bloquant.

### Ce qui est sain

Aucune couleur en dur hors de `KitchenSink.tsx`, qui les affiche **volontairement** comme
contenu — c'est la page qui documente la charte. Tout le reste passe par les tokens.

> **C'est vrai à la lettre depuis le thème clair, et ça ne l'était pas avant.** Quatre
> littéraux traînaient — `#93b8c3` trois fois (survol du bouton primaire et du disque
> `⊕`), `#1b2530` une fois (survol de `LogButton`) —, plus deux valeurs que seul un fond
> sombre rendait correctes : le voile de `Sheet` en `rgb(0 0 0 / .55)` et le liseré de
> cellule de heatmap en `rgb(255 255 255 / .02)`. Les six sont devenus des tokens
> (`--signal-hover`, `--log-hover`, `--scrim`, `--heat-edge`). Un survol qui *éclaircit*
> n'a pas de sens sur fond clair, où il doit assombrir : un littéral ne sait pas faire les
> deux. Le `#000` du `mask-image` de `Shell.module.css` reste, et c'est normal — un masque
> n'est pas une couleur.

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
