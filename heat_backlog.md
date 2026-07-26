# Spec `HEAT` v2 — Moteur d'assiduité multi-pistes

Remplace la section 12 « Agrégats, heatmaps & assiduité » du backlog v2 pour la partie
`HEAT`. Les `AGG-01` à `AGG-04` restent inchangés.

Document **agnostique de l'interface** : il décrit le modèle de données, les règles de
calcul et le contrat d'API. Le rendu de la grille (taille des cellules, palette,
libellés, grille de fond des graphiques) relève du fichier de guidelines UI.

**Principe directeur** : une heatmap ne mesure pas l'activité, elle mesure le **respect
d'un engagement**. Un jour vide n'est un échec que si quelque chose était attendu ce
jour-là. Tout le reste du document découle de ça.

---

## 1. Modèle de piste

| ID | Fonctionnalité | Description |
|---|---|---|
| HEAT-01 | Notion de piste | Une piste est une série d'assiduité indépendante, décrite par : identifiant, libellé, source de données, filtre, règle de validation, cadence, seuils d'intensité, état actif. Toutes les heatmaps de l'app sont des instances de ce même objet — il n'existe pas de code spécifique « heatmap whey » ou « heatmap jambes ». |
| HEAT-02 | Sources de données supportées | Une piste tire ses valeurs d'une source parmi : `activity.muscle_group` (séries d'un groupe musculaire), `activity.runs` (distance courue), `activity.duration` (minutes toutes activités), `supplement.intake` (prises d'un supplément donné), `hydration.intake` (volume bu), `entry_count` (nombre de domaines renseignés). Ajouter une source est le seul cas nécessitant du code. |
| HEAT-03 | Agrégat quotidien | Chaque source produit une **valeur numérique unique par jour** (séries, km, ml, nombre de prises). C'est le seul contrat entre la source et le moteur : tout le reste — validation, cadence, intensité — ne travaille que sur ce nombre. |
| HEAT-04 | Règle de validation | Un seuil sur l'agrégat quotidien décide si le jour est validé : `agrégat ≥ seuil`. Eau : 1000 ml. Muscu : 1 série. Supplément : 1 prise. Le seuil est un paramètre de la piste, jamais une constante. |

## 2. États du jour

| ID | Fonctionnalité | Description |
|---|---|---|
| HEAT-05 | Quatre états, pas cinq niveaux | Chaque jour de chaque piste porte un état : `off` (rien n'était attendu), `missed` (attendu, non validé), `done` (validé, avec un niveau d'intensité 1–4), `bonus` (validé alors que rien n'était attendu). C'est ce qui rend lisible une piste non quotidienne : une grille majoritairement `off` n'est pas un échec. |
| HEAT-06 | Jours neutralisés | Une plage de dates peut être marquée neutralisée (maladie, voyage, deload). Ces jours passent en `off` quelle que soit la cadence et ne comptent ni comme réussite ni comme échec. Une grippe ne casse pas une série de 90 jours. |
| HEAT-07 | Jours antérieurs à la piste | Une piste ne produit aucun état avant sa date de création. Ajouter la créatine aujourd'hui ne rend pas rouges les six mois précédents. La date de création est portée par la piste et immuable. |
| HEAT-08 | Jour en cours | Le jour courant n'est jamais `missed` tant qu'il n'est pas terminé : il reste `off` ou `done`. Cohérent avec la règle déjà appliquée à la série d'assiduité `AGG-03`. |

## 3. Cadences

| ID | Fonctionnalité | Description |
|---|---|---|
| HEAT-09 | Cadence `daily` | Attendu tous les jours. Tout jour non validé est `missed`. Créatine, eau. |
| HEAT-10 | Cadence `window` — N fois par fenêtre glissante de D jours | Paramètres : `min_count`, `window_days`. Un jour est `missed` uniquement si la fenêtre qui s'y referme contient moins de `min_count` validations. Whey « un jour sur deux » = `min_count: 1, window_days: 2`. Choix délibéré d'une fenêtre glissante plutôt qu'une parité de calendrier : lundi/mercredi/vendredi et mardi/jeudi/samedi sont deux rythmes également corrects, une règle « jours pairs » en punirait un arbitrairement. |
| HEAT-11 | Cadence `per_week` — N fois par semaine | Paramètre : `count`. L'unité d'évaluation devient la semaine ISO (lundi → dimanche), pas le jour. Les jours restent `done` ou `off`, jamais `missed` individuellement ; c'est la **semaine** qui porte un statut atteint / partiel / manqué. Adapté aux groupes musculaires : « torse 2×/semaine » ne dit rien sur *quel* jour. |
| HEAT-12 | Cadence `conditional` | Attendu uniquement les jours où une autre condition est vraie — typiquement l'existence d'une séance, ou d'une séance d'un groupe donné. Paramètre : la piste ou l'événement déclencheur. C'est la cadence correcte pour un supplément péri-entraînement. |
| HEAT-13 | Cadence `none` | Aucune attente : la piste est purement descriptive, tous les jours validés sont `done`, les autres `off`. Utile pour une piste d'observation qu'on ne veut pas transformer en injonction. |
| HEAT-14 | Cadence versionnée | Changer une cadence n'affecte **que les jours à partir de la date du changement**. Chaque cadence porte une date de prise d'effet, et l'historique des cadences d'une piste est conservé. Passer la whey de 1 jour sur 2 à 1 jour sur 3 aujourd'hui ne réécrit pas le verdict des mois passés. |

## 4. Intensité

| ID | Fonctionnalité | Description |
|---|---|---|
| HEAT-15 | Seuils d'intensité par piste | Quatre bornes croissantes convertissent l'agrégat quotidien en niveau 1–4. Elles sont propres à chaque piste : on ne compare pas des séries d'abdos à des kilomètres. |
| HEAT-16 | Mode binaire | Une piste peut déclarer n'avoir qu'un seul niveau. C'est le cas par défaut des suppléments : une prise est une prise, il n'y a pas de gradient. |
| HEAT-17 | Validation et intensité découplées | Le seuil de validation et les seuils d'intensité sont indépendants. L'eau en est l'illustration : validation à 1 L (décide vert ou rouge), intensité graduée jusqu'à l'objectif de 2 L (décide l'intensité du vert). Un jour à 1,1 L est validé mais pâle. |

## 5. Pistes livrées par défaut

Créées à l'initialisation, toutes modifiables et supprimables ensuite.

| Piste | Source | Filtre | Validation | Cadence par défaut | Intensité |
|---|---|---|---|---|---|
| `abdos` | `activity.muscle_group` | abdos | ≥ 1 série | `per_week`, 2 | séries : 1–2 / 3–5 / 6–9 / 10+ |
| `torse` | `activity.muscle_group` | pectoraux, épaules | ≥ 1 série | `per_week`, 2 | idem |
| `dos` | `activity.muscle_group` | dos | ≥ 1 série | `per_week`, 2 | idem |
| `bras` | `activity.muscle_group` | biceps, triceps | ≥ 1 série | `per_week`, 2 | idem |
| `jambes` | `activity.muscle_group` | jambes, fessiers | ≥ 1 série | `per_week`, 2 | idem |
| `course` | `activity.runs` | — | ≥ 1 km | `per_week`, 2 | km : <3 / 3–6 / 6–10 / 10+ |
| `eau` | `hydration.intake` | — | ≥ 1000 ml | `daily` | ml : 1000 / 1500 / 2000 / 2500 |
| `créatine` | `supplement.intake` | id du supplément | ≥ 1 prise | `daily` | binaire |
| `whey` | `supplement.intake` | id du supplément | ≥ 1 prise | `window`, 1 / 2 j | binaire |

Le dos est une piste distincte du torse : fondus ensemble, un déséquilibre poussée /
tirage devient invisible sur la grille, ce qui est précisément ce qu'on veut voir.

Le mapping groupe musculaire → piste est un **réglage**, pas une constante : la
taxonomie de saisie garde ses 9 valeurs (`ACT-06`), le regroupement en 5 pistes vit
dans la configuration et peut être redécoupé sans toucher aux données.

## 6. Réglages & gestion des pistes

| ID | Fonctionnalité | Description |
|---|---|---|
| HEAT-18 | Créer une piste | Ajout d'une piste en choisissant sa source, son filtre, sa règle de validation, sa cadence et ses seuils. Ajouter un nouveau complément crée sa piste dans la foulée, avec sa propre cadence. |
| HEAT-19 | Modifier une cadence à tout moment | La cadence et ses paramètres sont éditables à tout moment depuis les réglages, sans intervention technique et sans toucher aux fichiers. La modification prend effet à sa date (`HEAT-14`) : l'historique reste jugé selon la règle qui s'appliquait alors. |
| HEAT-20 | Modifier seuils et libellés | Seuil de validation, seuils d'intensité, libellé et couleur d'accent sont éditables. Contrairement à la cadence, un changement de seuil **recalcule l'ensemble de l'historique** — un seuil est une définition, pas un engagement daté. Cette asymétrie est assumée et doit être annoncée à l'utilisateur. |
| HEAT-21 | Désactiver plutôt que supprimer | Une piste peut être désactivée : elle disparaît des vues mais conserve son historique et peut être réactivée. La suppression définitive existe aussi, avec confirmation, et n'efface jamais les données sources sous-jacentes. |
| HEAT-22 | Réordonner et mettre en avant | L'ordre des pistes et celle mise en avant sont des réglages utilisateur. *(remplace `HEAT-08` de la v1)* |
| HEAT-23 | Cadence des suppléments portée par le planning | Pour une piste `supplement.intake`, la cadence est celle de la ligne correspondante de `supplements/schedule.csv` (colonne `frequency`, aujourd'hui inutilisée). Un seul endroit décrit « je prends de la whey un jour sur deux » : le planning de compléments et la heatmap ne peuvent pas diverger. |

## 7. Lecture & statistiques

| ID | Fonctionnalité | Description |
|---|---|---|
| HEAT-24 | Grille d'une piste | Pour une piste et une plage, retour d'un tableau `date → { valeur, état, niveau }` **complet** : les jours sans donnée sont retournés explicitement, jamais omis. Le client n'a aucun trou à combler. |
| HEAT-25 | Lecture multi-pistes | Une requête unique retourne les grilles de plusieurs pistes sur la même plage, pour éviter neuf appels sur un écran qui affiche neuf grilles. |
| HEAT-26 | Statistiques par piste | Sur la plage demandée : jours validés, jours attendus, taux de respect, plus longue série, série en cours, meilleur jour, total cumulé (km, litres, séries). |
| HEAT-27 | Série cadence-consciente | Une série compte les **jours attendus consécutifs validés**. Les jours `off` et neutralisés sont transparents : ils n'incrémentent ni ne cassent la série. Une whey prise un jour sur deux pendant trois mois donne une série de trois mois, pas de deux jours. |
| HEAT-28 | Statuts hebdomadaires | Pour les pistes `per_week`, retour du statut de chaque semaine (atteint / partiel / manqué) avec le compte réalisé sur le compte attendu. |
| HEAT-29 | Détail d'un jour | Pour une piste et une date, retour du détail sous-jacent : exercices et séries du groupe, distance et allure, prises horodatées, volumes bus. Chaque cellule est explorable. |

## 8. Contrat d'API

```
GET    /api/heatmap/tracks                     → liste des pistes et leur config
POST   /api/heatmap/tracks                     → créer une piste
PATCH  /api/heatmap/tracks/{id}                → modifier (cadence versionnée)
DELETE /api/heatmap/tracks/{id}                → supprimer (garde anti-conflit)
GET    /api/heatmap/{id}?from=&to=             → grille + stats d'une piste
GET    /api/heatmap?tracks=a,b,c&from=&to=     → grilles de plusieurs pistes
GET    /api/heatmap/{id}/day/{date}            → détail d'un jour
POST   /api/heatmap/off-days                   → neutraliser une plage
DELETE /api/heatmap/off-days/{id}              → annuler une neutralisation
```

Forme de réponse d'une grille :

```json
{
  "track": { "id": "whey", "label": "Whey", "unit": "prise", "binary": true },
  "cadence": { "type": "window", "min_count": 1, "window_days": 2 },
  "range": { "from": "2025-07-27", "to": "2026-07-26" },
  "days": [
    { "date": "2026-07-24", "value": 1, "state": "done",  "level": 1 },
    { "date": "2026-07-25", "value": 0, "state": "off",   "level": 0 },
    { "date": "2026-07-26", "value": 0, "state": "off",   "level": 0 }
  ],
  "weeks": null,
  "stats": {
    "validated_days": 148, "expected_days": 183, "compliance": 0.81,
    "longest_streak": 62, "current_streak": 12, "best_day": null, "total": 148
  }
}
```

Pour une piste `per_week`, `weeks` porte le statut hebdomadaire et `days` ne contient
jamais `missed`.

| ID | Fonctionnalité | Description |
|---|---|---|
| HEAT-30 | Calcul côté serveur exclusivement | États, niveaux, séries et statuts hebdomadaires sont calculés par le backend. Le client ne réimplémente aucune règle de cadence — sinon les deux divergent au premier cas limite. |
| HEAT-31 | Plage par défaut | 371 jours (53 semaines pleines) se terminant aujourd'hui, alignés sur des semaines complètes commençant le lundi. |
| HEAT-32 | Jour local | Le découpage en jours suit le fuseau local (Europe/Paris), pas UTC. Une prise à 23 h 30 appartient au jour qu'affiche l'horloge, pas au lendemain. |
| HEAT-33 | Cache et invalidation | Les grilles sont cachées côté serveur et invalidées à toute écriture touchant une source ou une configuration de piste. Un calcul sur 371 jours × 9 pistes ne doit pas relire Nextcloud à chaque affichage. |

## 9. Données

Nouveaux fichiers :

| Fichier | Colonnes |
|---|---|
| `settings/heatmap_tracks.csv` | id, label, source, filter, validation_threshold, levels, binary, accent, position, active, created |
| `settings/heatmap_cadences.csv` | id, track_id, type, params, valid_from |
| `settings/heatmap_off_days.csv` | id, track_id, date_from, date_to, reason |

`track_id` vide dans `heatmap_off_days` = neutralisation de toutes les pistes.
`params` est un champ sérialisé (`min_count=1;window_days=2`) pour rester lisible en
tableur, conformément à `STO-02`.

Colonnes ajoutées à l'existant :

| Fichier | Ajout | Raison |
|---|---|---|
| `supplements/schedule.csv` | `frequency` (renseignée), `created` | Cadence du supplément (`HEAT-23`) et non-rétroactivité (`HEAT-07`) |
| `hydration/intake_log.csv` | fichier entier | Source de la piste eau (domaine `HYD`) |

---

## Décisions ouvertes

1. **`per_week` par défaut à 2 pour les 5 groupes musculaires** — ça suppose 10 créneaux
   musculaires hebdomadaires, ce qui est beaucoup si tu cours aussi. À caler sur ta
   fréquence réelle des 4 dernières semaines plutôt que sur une valeur arbitraire.
2. **Piste `eau` : validation à 1 L** — c'est un plancher bas. Il valide des journées où
   tu as bu la moitié de ce qu'il faudrait. Assumé si l'objectif est de ne jamais casser
   la série ; à monter à 1,5 L si tu veux que le vert veuille dire quelque chose.
3. **Compléments en binaire** — si tu prends parfois deux doses de whey, l'information
   se perd. Passer en gradué coûte deux seuils.
   