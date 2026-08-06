# Refonte mobile — plan de travail

Objectif : que les douze écrans soient **agréables sur un iPhone 16 Pro**, et qu'on ait
envie d'y revenir. Ce document est le plan d'exécution ; il se lit avec
[`front.md`](front.md), qui reste la carte du front, et ne touche à aucun des six
invariants de sa [§7](front.md#7--ce-quune-refonte-ne-doit-pas-casser).

Il porte sur **la taille des choses, la densité, la portée du pouce et le plaisir d'usage**.
Pas sur ce que l'interface dit — ça, c'est déjà réglé.

---

## 1. Le constat, mesuré

Cinq faits sortis du code. Ils orientent tout le reste.

### 57 % de la typographie est sous le plancher de lisibilité

Sur **169 déclarations `font-size`** dans les feuilles de style :

| Taille | Occurrences | Où |
|---|---|---|
| **9–12 px** | **96** | surtitres, en-têtes de tableau, notes, unités, libellés de jour, barres |
| 13–15 px | 48 | corps de texte, cartes, checklists |
| 16 px et plus | 25 | champs, titres, chiffres clés |

Le corps de page est à **15 px**, les notes à **13 px**, les surtitres à **11 px** en
capitales espacées à `0.18em`, les en-têtes de tableau à **10 px**. C'est une densité de
tableau de bord vu à 60 cm sur un 27 pouces. À bout de bras sur un téléphone, on plisse les
yeux — et on n'a pas envie de rester.

**C'est le premier levier, et de loin.**

### Aucune gestion des zones sûres

`index.html` déclare `width=device-width, initial-scale=1` sans `viewport-fit=cover`, et
**`env(safe-area-inset-*)` n'apparaît nulle part** dans les 2 400 lignes de CSS. Sur un
16 Pro : 59 px d'îlot dynamique en haut, 34 px d'indicateur d'accueil en bas. Rien n'en
tient compte aujourd'hui — ce qui passe tant que la navigation est en haut, et devient
bloquant dès qu'on met quoi que ce soit en bas.

### 27 règles `:hover`, une seule protégée

Une seule occurrence de `@media (hover: hover)` dans tout le projet
([primitives.module.css:439](../frontend/src/components/ui/primitives.module.css#L439), pour
`SwipeRow`). Les 26 autres s'appliquent au doigt : sur iOS, un appui déclenche le `:hover`
**et le laisse collé** jusqu'à ce qu'on touche ailleurs. Un bouton primaire touché reste
éclairci et remonté d'un pixel (`transform: translateY(-1px)`) — l'interface a l'air
cassée.

Et `-webkit-tap-highlight-color` n'est déclaré nulle part : iOS dessine son rectangle gris
par défaut sur chaque appui, par-dessus les états déjà dessinés par la charte.

### La règle graduée coûte 78 px, cinq fois par écran

`.rule` porte `margin: var(--s8) 0 var(--s6)` — **52 px au-dessus, 26 px en dessous**.
Le tableau de bord en compte cinq, l'écran Activité aussi : **390 px de séparateur pur**,
soit plus de la moitié d'un écran de 16 Pro, pour un trait de 1 px. Le motif est beau ; sa
respiration est celle d'une page large.

### Quatre points de rupture, dont trois à l'envers

`560`, `640`, `760`, `900`, `960` px — cinq valeurs en fait, dont **`max-width: 760px` dans
`base.css`** qui fait retomber `.g2`, `.g3` et `.g4` à une seule colonne sous 760 px. Les
quatre chiffres clés du tableau de bord deviennent donc quatre grandes cartes empilées :
il faut faire défiler pour lire son poids et sa semaine, alors que les deux tiennent côte à
côte.

### Ce qui est déjà bon

Le plancher tactile de 44 px est tenu partout, les champs sont à 16 px (iOS ne zoomera
pas), les tableaux défilent dans leur conteneur, `100dvh` est employé correctement, aucune
couleur n'est en dur. **Le socle est sain — c'est une question d'échelle, pas de
plomberie.**

---

## 2. Ce que « mobile d'abord » veut dire ici

L'appareil cible, en chiffres :

| | Valeur |
|---|---|
| iPhone 16 Pro, portrait | **402 × 874 px CSS** (2622 × 1206 à DPR 3) |
| Zone sûre haute | 59 px (îlot dynamique) |
| Zone sûre basse | 34 px (indicateur d'accueil) |
| Hauteur utile dans Safari | **≈ 745 px**, barre d'adresse affichée |
| Zone atteignable au pouce | le **tiers bas** de l'écran, ~250 px |

Les feuilles de style continuent de s'écrire pour **390 px** — le plancher, pas la cible :
ce qui tient à 390 tient à 402 avec 12 px de marge en cadeau.

Trois conséquences qui décident du plan :

1. **La navigation est en haut, donc hors de portée.** Atteindre « Nutrition » demande de
   changer la prise en main. C'est le geste le plus fréquent de l'application.
2. **La première hauteur d'écran doit montrer une donnée.** Aujourd'hui : surtitre + titre
   34 px + règle graduée = ~150 px avant le premier chiffre, sur 745 disponibles.
3. **Un appui doit répondre.** Pas de survol au doigt : il faut un état `:active`, et il
   faut qu'il soit immédiat.

---

## 3. Les cinq phases

Dans l'ordre, du plus rentable au plus coûteux — le même principe que
[front.md §8](front.md#8--par-où-commencer).

### Phase 0 — L'outil de mesure

Avant de changer quoi que ce soit, un script réutilisable : `scripts/audit-mobile.mjs`.

Il applique la recette de [front.md §5](front.md#5--vérifier-un-changement) — doublure
d'API stdlib, Chrome headless piloté en CDP, `Emulation.setDeviceMetricsOverride` à
**402 × 874, DPR 3** — et parcourt les douze adresses en produisant un tableau :

| Mesure | Seuil |
|---|---|
| Cibles sous 44 px | 0 |
| Débordement horizontal | faux |
| Champs sous 16 px | 0 |
| **Plus petite taille de texte rendue** | ≥ 12 px |
| **Hauteur avant le premier chiffre** | ≤ 220 px |
| Alignement contenu / en-tête | égal |
| Nombre d'écrans à faire défiler | pour information |

Les deux lignes en gras sont nouvelles : ce sont celles qui mesurent « agréable ».

Le script sert de **avant / après** pour chaque phase, et de capture d'écran à regarder —
parce que c'est l'œil qui a trouvé huit défauts sur les quatre derniers lots, pas la
batterie.

**Livrable** : le script, plus un relevé initial des douze écrans dans
`docs/verifications-manuelles.md`.

---

### Phase A — Le socle : tokens, typographie, espacement

Une phase, effet sur douze écrans, aucun risque logique.

#### A1. Échelle typographique nommée

Les tailles cessent d'être des littéraux dispersés dans quatorze fichiers. Nouveaux tokens
dans [tokens.css](../frontend/src/styles/tokens.css) :

| Token | Rôle | Mobile | ≥ 600 px | Remplace |
|---|---|---|---|---|
| `--t-hero` | `h1` | **30 px** | 40 px | `clamp(34px, 6vw, 54px)` |
| `--t-title` | `h2` | **21 px** | 22 px | 22 px |
| `--t-head` | `h3`, titre de carte | **17 px** | 17 px | 16 px |
| `--t-body` | corps, `.check`, `.ai p` | **16 px** | 16 px | 14–15 px |
| `--t-sub` | notes, détails, `.lede` | **15 px** | 15 px | 13–14 px |
| `--t-meta` | surtitres, unités, dates | **12 px** | 12 px | **9, 10, 11 px** |
| `--t-num-xl` | chiffre clé (`Stat`) | **34 px** | 40 px | 32 px |
| `--t-num` | chiffre en ligne | **17 px** | 17 px | 12–14 px |

**Règle : rien sous 12 px.** Les 96 déclarations à 9–12 px remontent toutes à `--t-meta`.

Pour que les surtitres ne s'élargissent pas en grossissant, l'interlettrage baisse en
compensation : `0.18em → 0.12em` sur `.eyebrow`, `0.16em → 0.10em` sur les en-têtes de
tableau. Le gain de chasse (+9 %) et la perte d'espacement (−33 %) se neutralisent — la
barre de navigation et les colonnes de tableau gardent leur largeur. **À vérifier en
mesure, pas au jugé.**

Le `h1` **baisse** de 34 à 30 px : un titre de page n'est pas une donnée, et il mange la
première hauteur d'écran. Le chiffre clé, lui, monte de 32 à 34 — c'est lui qu'on vient
lire.

#### A2. Espacement et gouttières

```css
--gutter: 16px;      /* marge latérale de page — 20px aujourd'hui */
--card-pad: 16px;    /* padding de carte — var(--s5) = 20px aujourd'hui */
--tabbar: 56px;      /* hauteur de la barre du bas, hors zone sûre */
```

À ≥ 600 px, `--gutter` passe à 28 px et `--card-pad` revient à `var(--s5)`.

Gain net de largeur utile sur mobile : **16 px** (4 px × 2 sur la page, 4 px × 2 dans la
carte). Sur 402 px, ce n'est pas rien : `.barRow` du composant `Bars` réserve 166 px de
colonnes fixes, il ne reste aujourd'hui que ~147 px pour la barre elle-même.

`.rule` passe à `margin: var(--s6) 0 var(--s5)` sous 600 px — **44 px au lieu de 78**.
Sur le tableau de bord : **170 px rendus au contenu**, sans rien retirer.

#### A3. Zones sûres

[index.html](../frontend/index.html) :

```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
```

`initial-scale=1` sans `maximum-scale` ni `user-scalable=no` : **le zoom reste possible**,
c'est une question d'accessibilité et ce n'est pas négociable.

Les deux `apple-mobile-web-app-*` font qu'ajouté à l'écran d'accueil, Metric s'ouvre sans
la barre d'adresse de Safari — 745 px utiles deviennent 874. C'est la version la plus
agréable de l'application, et elle est gratuite.

Puis, en tokens :

```css
--safe-t: env(safe-area-inset-top, 0px);
--safe-b: env(safe-area-inset-bottom, 0px);
```

#### A4. Points de rupture : cinq → deux

| Ancien | Nouveau |
|---|---|
| `max-width: 760px` (`base.css`) | supprimé — les grilles deviennent mobile d'abord |
| `min-width: 560px`, `min-width: 640px`, `max-width: 640px` | **`min-width: 600px`** |
| `max-width: 900px`, `max-width: 960px`, `min-width: 960px` | **`min-width: 960px`** |

Et les grilles s'inversent — deux colonnes par défaut, pas une :

```css
.g2 { grid-template-columns: repeat(2, 1fr); }                    /* 2 dès 390px */
.g3, .g4 { grid-template-columns: repeat(2, 1fr); }               /* 2 sur mobile */
@media (min-width: 960px) {
  .g3 { grid-template-columns: repeat(3, 1fr); }
  .g4 { grid-template-columns: repeat(4, 1fr); }
}
```

Les quatre chiffres du tableau de bord tiennent alors en **2 × 2** au lieu de quatre cartes
empilées. Un `Stat` compact (valeur 28 px au lieu de 34) accompagne le changement pour que
« 82,4 kg » tienne dans 159 px.

**Vérification A** : `/_kitchen-sink` d'abord — tout s'y voit —, puis le relevé de
phase 0 rejoué sur les douze écrans. Aucune ligne de `routes/` touchée à ce stade.

---

### Phase B — La coquille : la navigation passe sous le pouce

C'est le changement structurant, et **la seule décision de produit du plan** (voir [§4](#4--la-décision-à-prendre)).

Aujourd'hui : neuf entrées en haut, **806 px demandés pour 695 disponibles**, qui défilent
horizontalement. Sur téléphone, ça veut dire deux gestes pour changer d'écran — faire
défiler la barre, puis viser — et la barre est en haut, hors de portée du pouce.

#### B1. Barre d'onglets basse

```
┌──────────────────────────────────────┐
│  Metric                    ⋯         │  header 52px + zone sûre haute
├──────────────────────────────────────┤
│                                      │
│  contenu                             │
│                                      │
├──────────────────────────────────────┤
│  ⌂        ◷        ◍        ▤    ⋯   │  tabbar 56px + zone sûre basse
│ Accueil  Corps  Activité Nutrition Plus │
└──────────────────────────────────────┘
```

- **Cinq entrées maximum**, chacune ≥ 56 px de haut (`--tap-lg` : ce sont les cibles les
  plus touchées de l'application), libellé à `--t-meta`, icône au-dessus.
- `position: fixed; bottom: 0`, `padding-bottom: var(--safe-b)`, fond flouté comme
  l'en-tête actuel.
- `.main` reçoit `padding-bottom: calc(var(--tabbar) + var(--safe-b) + var(--s5))` pour que
  rien ne finisse sous la barre.
- **Au-delà de 960 px, la barre basse disparaît** et la navigation revient en haut, telle
  qu'elle est aujourd'hui — le desktop ne perd rien.

#### B2. La feuille « Plus »

Les entrées restantes — Planning, Objectif, Routine, Assiduité, Assistant, Réglages,
Déconnexion — dans une feuille qui monte du bas, chaque ligne à `--tap-lg`, fermée par
glissement vers le bas ou appui hors zone.

**L'assistant y gagne une entrée de navigation**, qu'il n'a jamais eue : le compromis de
`L14b` — « on y entre par une carte du tableau de bord » — tombe de lui-même, puisque la
contrainte des 806 px disparaît.

Nouveau composant `Sheet` dans `primitives.tsx` + `index.ts`. Il resservira en phase E.

#### B3. En-tête allégé

52 px, `padding-top: var(--safe-t)`, sticky. Il ne porte plus que la marque et un accès
au « Plus ». Le nom d'utilisateur et « Déconnexion » descendent dans la feuille.

**Vérification B** : les douze écrans au relevé de phase 0, plus trois contrôles propres à
cette phase — rien sous la barre basse au bas de page, la barre ne recouvre pas le clavier
système sur un champ actif, et la feuille se ferme au glissement.

---

### Phase C — Les primitives : le toucher répond

#### C1. Le survol cesse de coller

Les 26 `:hover` non protégés passent sous `@media (hover: hover) and (pointer: fine)`.
C'est mécanique, et ça retire d'un coup l'effet « bouton resté allumé » sur toute
l'application.

#### C2. L'appui répond à la place

`:active { transform: scale(0.97) }` — déjà présent sur `Chip` et `Stepper`, étendu à
`Button`, `LogButton`, `Card` cliquable, `Check`, `Segmented`, entrées de navigation.
Le retour est immédiat : c'est ce qui fait qu'une interface au doigt paraît vivante plutôt
que lente.

Et `-webkit-tap-highlight-color: transparent` sur `body`, pour que le rectangle gris d'iOS
ne se superpose pas aux états de la charte.

#### C3. Les tailles

| Composant | Aujourd'hui | Proposé |
|---|---|---|
| `Button` | 44 px, texte 14 px | 48 px, texte 16 px — 56 px pour `primary` sur mobile |
| `LogButton` | 44 px, mono 13 px | **56 px** (`--tap-lg`) — c'est l'action qui termine un geste |
| `Stepper` touches | 44 px | **56 px** sur mobile — on les touche entre deux séries |
| `Segmented` | 44 px, texte 11 px | 44 px, texte 12 px, `flex: 1` pour occuper la largeur |
| `Check` | ~44 px, case 16 px | 52 px, case 22 px |
| `Badge` | texte 11 px | texte 12 px |
| `Empty` | padding 32 px | 24 px sur mobile |
| `Card` | padding 20 px | `--card-pad` (16 px sur mobile) |

#### C4. Les deux gros composants

`Chart` et `Heatmap` se vérifient à 402 px : lisibilité des étiquettes d'axe, taille de
cellule (`--heat-cell: 12px` + 3 px de gouttière → 53 semaines × 15 px = 795 px, la grille
annuelle déborde forcément et doit défiler proprement), et l'infobulle qui ne doit pas
sortir de l'écran au doigt.

**Vérification C** : `/_kitchen-sink`, qui montre chaque composant dans tous ses états —
c'est exactement ce pour quoi la page existe.

---

### Phase D — Les douze écrans, un par un

Dans l'ordre d'usage réel, pas dans l'ordre du menu.

| # | Écran | Passe tactile ? | Ce qu'on sait déjà |
|---|---|---|---|
| 1 | `/` **Tableau de bord** | non | 5 règles graduées (390 px), `g4` à une colonne, `.split` à 960, 2 styles en ligne, `wrap` sur 3 blocs |
| 2 | `/routine` | non | à mesurer — checklists, cible du geste quotidien |
| 3 | `/nutrition` | non | 787 lignes, 3 styles en ligne, bloc IA |
| 4 | `/corps` | non | 470 lignes, 5 styles en ligne |
| 5 | `/activite` | v0.12.2 | **1383 lignes, 12 sous-composants, 5 règles graduées** — à découper par section |
| 6 | `/planning` | L13 | 877 lignes — convention `wrap + screen`, la bonne |
| 7 | `/objectif` | L14 | convention `wrap + screen` |
| 8 | `/assistant` | L14b | gagne une entrée de navigation en phase B |
| 9 | `/assiduite` | non | `position: fixed` déjà présent (infobulle) — à vérifier contre la barre basse |
| 10 | `/reglages` | non | + `settings/Tracks.tsx`, **856 lignes** |
| 11 | `/connexion` | non | hors coquille, première impression, `h1` en style en ligne |
| 12 | `/_kitchen-sink` | — | mis à jour au fil des phases A et C |

Sur chacun, la même passe :

1. **Le conteneur** : `cx('wrap', styles.screen)` partout — la convention de `/planning`,
   `/objectif` et `/assistant`, la plus récente et la plus lisible. Neuf écrans posent
   encore `wrap` sur plusieurs blocs, ce qui double la marge verticale entre eux.
2. **Les styles en ligne** : les **60 `style={{…}}`** restants deviennent des classes.
   La trentaine de `marginTop: 10` et de `<div style={{ height: 40 }} />` contourne
   l'échelle `--s1`…`--s8` — et le `height: 40` de fin de page devient inutile une fois que
   `.main` porte le dégagement de la barre basse.
3. **La première hauteur d'écran** : un chiffre visible sans faire défiler. Surtitre + `h1`
   se resserrent, la première règle graduée disparaît sur mobile quand elle ouvre l'écran.
4. **Les quatre états** : chargement, vide, erreur, données — et l'état vide dit ce que
   coûte le prochain geste.
5. **Mesure + capture.** Les deux, jamais l'une sans l'autre.

Les trois gros fichiers (`Activity.tsx` 1383, `Planning.tsx` 877, `Tracks.tsx` 856) se
découpent en fichiers par section, comme `routes/settings/` l'a fait. Ce n'est bloquant
pour personne, mais c'est le bon moment.

---

### Phase E — Ce qui donne envie de revenir

Les quatre phases précédentes retirent des irritants. Celle-ci ajoute quelque chose.

#### E1. Le geste de saisie sous le pouce

Un bouton `⊕` au centre de la barre basse ouvre une feuille de saisie rapide : **pesée ·
verre d'eau · supplément · repas · séance**. Chaque entrée écrit en un geste, sans changer
d'écran, et invalide son domaine.

C'est déjà la cible affichée du projet — `LogButton` porte en commentaire « la cible du
projet, un relevé en un geste » — mais elle demande aujourd'hui de naviguer d'abord.
**Réduire un relevé à deux appuis depuis n'importe où est, de loin, ce qui change le plus
la fréquence d'ouverture.**

Réutilise le `Sheet` de la phase B. Aucune écriture nouvelle côté serveur : ce sont les
mêmes appels que les écrans concernés.

#### E2. Le mouvement

- Transition d'écran : fondu de 150 ms sur `<Outlet />`, sous `prefers-reduced-motion`.
- La feuille monte et descend ; elle ne clignote pas.
- `overscroll-behavior: contain` sur la feuille et la barre, pour que le rebond iOS ne
  tire pas la page derrière.
- Les barres et anneaux s'animent depuis zéro à l'apparition — la donnée arrive, elle ne
  se contente pas d'être là.

#### E3. Ce que l'écran dit quand il n'y a rien

Les états vides existent et sont bien écrits. Sur mobile ils doivent en plus **porter le
geste** : « Un chiffre le matin, et la courbe commence » gagne un bouton qui ouvre la
feuille de pesée, au lieu de décrire un écran à trouver.

---

## 4. La décision à prendre

Une seule, et elle conditionne la phase B : **quelles cinq entrées dans la barre basse.**

Six écrans se disputent cinq places — Accueil, Corps, Routine, Nutrition, Activité, et le
« Plus » qui doit exister.

**Option 1 — cinq onglets simples**
`Accueil · Corps · Activité · Nutrition · Plus`
Routine, Planning, Objectif, Assistant, Assiduité et Réglages dans la feuille. Simple,
conventionnel, livrable dès la phase B. Routine — le geste le plus quotidien — se retrouve
à deux appuis.

**Option 2 — quatre onglets et un geste central** *(recommandée)*
`Accueil · Activité · ⊕ · Nutrition · Plus`
Corps et Routine ne sont plus des destinations mais des **actions**, accessibles depuis
n'importe quel écran par le `⊕`. La barre gagne le geste que l'application existe pour
rendre facile, et il est au centre, là où le pouce tombe.
Coût : le `Sheet` et la saisie rapide passent de la phase E à la phase B.

Le reste du plan est identique dans les deux cas. **À trancher avant de commencer la
phase B** ; les phases 0 et A peuvent démarrer sans.

---

## 5. Ce que la refonte ne touche pas

Les six invariants de [front.md §7](front.md#7--ce-quune-refonte-ne-doit-pas-casser)
tiennent, sans exception :

- **Aucun calcul métier côté client.** Un nouveau chiffre à l'écran s'ajoute au service
  backend, jamais dans `features/<domaine>/api.ts`.
- **Aucune valeur inventée.** Un tiret, pas un zéro. Vérifier ce que le **composant**
  dessine quand la donnée est absente, pas ce que l'écran croit lui demander — c'est le
  défaut du L14, et il passait sous 112 tests verts.
- **Une valeur proposée n'est pas une mesure.** `AiBlock` et l'état `proposed` du
  `Stepper` restent la seule façon de le dire. La refonte n'en invente pas une cinquième.
- **Le jour vient du serveur.** Pas de `new Date()` pour dater une donnée.
- **Les erreurs portent un code.** Le client décide sur `error.code`, le message du serveur
  s'affiche tel quel.
- **Le style suit le composant.** Une variante d'apparence va dans `primitives.tsx` et son
  module. C'est précisément ce que la phase D vient réparer, pas contourner.

Et deux ajouts propres à cette refonte :

- **Le zoom reste possible.** Pas de `user-scalable=no`, pas de `maximum-scale`.
- **Le glissement navigue, il ne mesure pas.** Pas de curseur pour une charge, même dans
  une feuille de saisie rapide. Une implémentation unique :
  [lib/swipe.ts](../frontend/src/lib/swipe.ts).

---

## 6. Ordre d'exécution

| Phase | Portée | Fichiers | Risque |
|---|---|---|---|
| **0** | outil de mesure | `scripts/audit-mobile.mjs` | nul |
| **A** | socle | `tokens.css`, `base.css`, `index.html` | faible — visuel global |
| **B** | coquille | `Shell.tsx` + module, `primitives.tsx` (`Sheet`), `App.tsx` | **structurant** |
| **C** | primitives | `primitives.*`, `data.*`, `Chart`, `Heatmap` | faible |
| **D** | 12 écrans | `routes/*` | moyen — un écran à la fois |
| **E** | finition | `Sheet`, transitions, états vides | faible |

Après **chaque** phase :

```bash
make check      # prettier, eslint, tsc --noEmit, vitest — 215 tests d'écran
node scripts/audit-mobile.mjs
```

puis **regarder les captures**. Dans cet ordre, et jamais l'un sans l'autre : sur les
quatre derniers lots, huit défauts sont sortis en regardant la page, zéro de la batterie.

Les tests d'écran vont bouger — ils interrogent des libellés de navigation qui déménagent
en phase B. C'est attendu ; ce qui ne doit pas bouger, ce sont les assertions sur les
`code` d'erreur et sur ce que les écrans **disent**.
