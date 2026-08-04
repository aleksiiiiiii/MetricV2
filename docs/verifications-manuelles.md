# Vérifications à faire à la main

Ce qui ne peut pas être vérifié par `make check`, accumulé lot après lot, avec pour chaque
entrée **ce qu'on lance**, **ce qu'on regarde** et **ce qui compte comme échec**.

Ce document existe pour une raison précise, écrite au §6 de
[`etat-du-projet.md`](etat-du-projet.md) et confirmée trois lots de suite : *tout ce qui a
été trouvé l'a été en utilisant l'application, pas en la testant.* La refonte de l'écran
Activité est partie avec vingt-quatre tests verts et deux défauts sont sortis en regardant
la page. La passe tactile en a produit trois de plus. La découverte des modèles était
verte sur toute sa batterie simulée, et le vrai catalogue a fait tomber deux entrées
qu'elle acceptait.

Un test vérifie ce qu'on a pensé à vérifier. Cette liste est ce qu'on n'a pas encore
regardé.

**Ordre de lecture** : les sections sont classées par ce qu'elles coûtent à ignorer, pas
par difficulté. La première bloque une clôture de lot.

---

## 1. Ce qui bloque la clôture du lot L12

La DoD de `L12` est vérifiée **à moitié**. La première moitié — « sans clé API, aucune
fonctionnalité n'est bloquée » — l'est par `tests/test_ai_api.py`. La seconde ne peut pas
l'être autrement qu'à la main.

> **Rappel de conduite** : chaque appel réel à OpenRouter se demande avant. `OPENROUTER_MODEL`
> vaut `anthropic/claude-sonnet-5`, un modèle **payant** placé en tête de cascade : chacune
> des vérifications ci-dessous coûte de l'ordre d'un centime. Vider le réglage bascule sur
> les six modèles vision gratuits.

### 1.1 — Une capture Apple Fitness pré-remplit une course

```bash
make dev          # puis /activite, section « Saisie »
```

**Le geste** : carte « Import d'une capture » → choisir une vraie capture d'Apple Fitness
ou de la montre → « Lire la capture ».

**Ce qu'on regarde**, dans cet ordre :

| Point | Ce qui doit se produire |
|---|---|
| Distance | convertie en km si la capture est en miles, avec la bonne valeur *(5,20 MI → 8,369 km)* |
| Durée | `28:45` devenu 28,75 minutes, pas 28 ni 2845 |
| Date | absolue et passée, même si la capture écrit « Hier » ou « Lundi » |
| Champs absents | **vides**, et nommés dans la phrase du bloc IA — jamais à zéro |
| Nature | course si la capture porte une distance, séance sinon |
| Écriture | **rien** dans `runs.csv` tant qu'« Importer cette activité » n'est pas touché |

**Ce qui compte comme échec** : une valeur inventée là où la capture ne portait rien, une
distance en miles restée en miles, une date du jour posée par défaut, ou une ligne écrite
avant validation. Les trois premiers font entrer une mesure fausse dans un fichier censé
rester lisible dans dix ans ; le quatrième casse `IMP-01`.

**Puis** : ouvrir `activity/runs.csv` sur Nextcloud et vérifier que la dernière ligne se
termine par `,apple`. C'est `IMP-05`, et c'est le seul endroit où l'on peut le constater.

### 1.2 — Une vraie photo de repas donne une estimation utilisable

```bash
make dev          # puis /nutrition
```

**Le geste** : « Ajouter un repas » → prendre ou choisir une photo d'assiette →
« Estimer les macros depuis la photo ».

**Ce qu'on regarde** : la phrase du bloc IA annonce des grammes et des kilocalories
plausibles ; « Utiliser ces valeurs » remplit les trois pas-à-pas **en pointillé** ; un
appui sur `+` retire le pointillé du champ touché et de lui seul ; « Pas d'accord » vide ce
qui reste proposé et **garde** ce qui a été retouché.

**Ce qui compte comme échec** : une estimation grossièrement fausse *(une salade à 2000
kcal)*, un champ rempli alors que le modèle n'a rien su dire, ou un pointillé qui survit à
une correction. Le dernier viderait `NUT-04` de son sens : on ne distinguerait plus ce
qu'on a validé de ce qu'une machine a proposé.

**Puis** : enregistrer, et vérifier dans `nutrition/meals.csv` que la ligne porte `ai` en
dernière colonne. Refaire un repas en refusant l'estimation : il doit porter `manual`.

### 1.3 — Une photo prise après coup s'estime quand même

Un repas enregistré **avec photo et sans macros** doit afficher un bouton « estimer » dans
le journal. C'est la porte pour le « après » que l'écran promet — et le seul chemin qui
relit une photo **déjà rangée sur Nextcloud**, ce que les tests ne couvrent que contre un
faux WebDAV.

**Ce qui compte comme échec** : le bouton absent, ou une estimation qui modifie le repas
sans passer par « Enregistrer ces valeurs ».

### 1.4 — Une capture illisible se dit

Envoyer volontairement une photo qui n'est pas une capture sportive — un paysage, une
capture de messagerie.

**Ce qu'on attend** : un message qui propose de refaire la capture **ou** de saisir à la
main (`IMP-06`), la capture toujours choisie pour relancer en un appui, et les deux
formulaires manuels intacts à côté.

### 1.5 — Le HEIC, écart assumé à confirmer

Envoyer une photo iPhone au format d'origine. Le refus doit **nommer les formats lisibles**
et le repas doit rester enregistrable normalement.

Si le cas se présente à chaque photo en usage réel, c'est le signal qu'il faut rouvrir la
décision et ajouter `pillow-heif`. Sinon, l'écart tient.

---

## 2. Ce qui n'a jamais été touché sur un vrai téléphone

`L17-07` désigne le mobile comme cible d'usage principale. La passe tactile de la `v0.12.2`
est mesurée dans un Chrome émulant un iPhone 14, **en évènements tactiles réels** : cibles,
débordement, glissements, tout est vérifié.

L'émulation ne reproduit ni l'imprécision du pouce, ni le clavier système qui remonte sur
le champ actif, ni la latence du réseau local.

```bash
make dev-lan      # annonce http://<ip>:5180/ — à saisir sur le téléphone
```

### 2.1 — Consigner une vraie série sur `/activite`

**C'est le test qui manque depuis le lot L11c.** Ouvrir l'écran, choisir un exercice,
ajuster une charge au pas-à-pas, consigner — sans jamais dégainer le clavier.

**Ce qu'on regarde** : est-ce qu'on rate les touches `−` et `+` ? Est-ce que le clavier
masque le bouton « Consigner » quand on tape dans le champ ? Est-ce qu'un défilement de
l'historique déclenche une suppression par mégarde ?

**Ce qui compte comme échec** : n'importe laquelle de ces trois. Les deux premières
rendraient le geste plus lent qu'au clavier, ce qui retirerait au pas-à-pas sa raison
d'être ; la troisième détruirait une donnée, et le projet n'a pas d'annulation.

### 2.2 — Les sept écrans qui n'ont pas eu la passe

`L17-07` reste ouvert. Un seul écran sur huit a été traité.

| Écran | À regarder en priorité |
|---|---|
| `/` tableau de bord | densité des cartes à 390 px, cibles des raccourcis |
| `/corps` | saisie d'une pesée au pouce, le champ décimal |
| `/routine` | les cases à cocher — c'est un écran qu'on touche tous les jours |
| `/nutrition` | le sélecteur de type reste un `<select>` natif ; les trois pas-à-pas sont neufs, à éprouver |
| `/assiduite` | la grille à 53 semaines, et si un jour se vise au doigt |
| `/reglages` | les champs numériques, et la section « Assistance » ajoutée au L12 |
| `/connexion` | le clavier au premier plan, le champ mot de passe |

**Un champ numérique sous 16 px fait zoomer iOS et décale la page.** C'est la règle du §2
la plus facile à casser sans s'en apercevoir sur un écran d'ordinateur.

---

## 3. Ce qui demande que du temps passe

### 3.1 — Une grille d'assiduité dense

Les pistes ont été amorcées le jour de la livraison du L11. `HEAT-07` rend donc tout le
passé `off`, et le taux de respect vaut `null` : comportement correct, mais qui laisse le
rendu d'une grille dense et le calcul des longues séries vérifiés sur données simulées
uniquement.

**Rouvrir `/assiduite` un mois après le 2026-07-28 est le vrai test du lot L11.**

**Ce qu'on regarde** : est-ce que 53 semaines de cases restent lisibles une fois pleines ?
Est-ce que la série en cours dit la vérité ? Est-ce que le taux de respect apparaît enfin ?

### 3.2 — Le cache de grilles sous modification concurrente

`FileStore.observe` invalide une grille mémorisée quand un des fichiers **réellement lus**
change. La décision **D8** repose sur l'idée que Nextcloud se modifie derrière notre dos.

**Le geste** : afficher `/assiduite`, modifier `activity/runs.csv` depuis un tableur ou
depuis le téléphone, recharger l'écran.

**Ce qui compte comme échec** : une grille qui refuse de changer. C'est le symptôme le pire
possible, celui que toute la conception du cache cherche à éviter.

---

## 4. Ce qui ne se simule pas, et qu'on verra à l'usage

Ces points n'ont pas de geste à faire : ils se constatent en utilisant l'application
pendant des semaines.

- **Le coût réel de l'assistance.** Le modèle configuré est payant et en tête de cascade.
  Si le total surprend, vider `OPENROUTER_MODEL` bascule sur les gratuits sans toucher au
  code.
- **La saturation des quotas gratuits.** La cascade est bornée à trois modèles et la
  distinction quota / panne est testée en simulation. Ce qu'on ne sait pas, c'est à quelle
  fréquence un modèle gratuit répond `429` dans la vraie vie — et donc si trois tentatives
  suffisent.
- **La latence d'une analyse d'image.** Le délai de lecture est réglé à 60 s. Si une
  estimation prend couramment vingt secondes, le bouton « Estimer » aura besoin de dire
  davantage que son état d'attente.
- **La qualité de lecture des captures selon leur écran.** Un résumé d'entraînement, un
  anneau d'activité et une page de détail ne se lisent pas pareil. `IMP-07` — captures
  d'anneaux, poids Apple Health, plusieurs captures à la fois — est **hors périmètre v1**,
  et c'est l'usage qui dira s'il faut l'y ramener.

---

## 5. Ce qui a déjà été vérifié, et n'est plus à refaire

Gardé ici pour éviter de le refaire par doute.

| Vérification | Date | Résultat |
|---|---|---|
| Chaîne Nextcloud réelle (`make check-storage`) | 2026-07-28 | connexion, écriture, relecture, nettoyage — et `If-None-Match` honoré avec un `304` |
| Latence WebDAV mesurée | 2026-07-28 | ~180 ms l'aller-retour ; écran d'assiduité 751 ms à froid, 6 ms ensuite |
| Passe tactile de `/activite` en émulation | 2026-07-29 | aucune cible sous 44 px, aucun débordement à 390 px |
| Découverte des modèles sur le vrai catalogue | 2026-07-31 | 365 publiés → 15 retenus → 6 vision ; deux défauts de filtrage trouvés et corrigés |

**La dernière ligne est l'argument de ce document.** La batterie simulée de `IA-02` était
verte, et le vrai catalogue contenait un routeur au prix `"-1"` et un générateur de musique
qui annonçait rendre du texte. Personne n'invente ces formes-là.
