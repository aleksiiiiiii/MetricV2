# L'assistant qui agit — plan de travail

Transformer `/assistant` d'un écran qui **répond** en un écran qui **fait** : un fil de
discussion qu'on retrouve, une IA qui écrit dans les données comme le ferait l'utilisateur,
et une mémoire qui se remplit toute seule.

> **État au 8 août 2026 — les sept phases sont faites**, sur la branche `assistant-agent`.
> Ce qui suit reste le document de référence des décisions ; le tableau de la
> [§8](#8-ordre-dexécution) dit ce qui a été livré et ce qui a bougé en chemin.

Ce document tient les décisions et l'ordre d'exécution. Il se lit avec
[`front.md`](front.md) pour le front et le §2 de [`etat-du-projet.md`](etat-du-projet.md)
pour les invariants — dont **trois** changent ici, et c'est le sujet de la première
section.

---

## 1. Ce que ça défait, et pourquoi c'est assumé

Trois décisions du projet sont renversées. Elles ne sont pas contournées : elles sont
réécrites, avec ce qui les remplace.

### « `ask` ne sait pas écrire »

C'est la première phrase de [`assistant/service.py`](../backend/app/domains/assistant/service.py),
et elle est appelée « la garantie du lot ». Le raisonnement d'origine tient toujours : un
modèle qui lit mal « 3×8 à 80 » écrit du faux dans un dossier de santé qui alimente tous
les autres écrans, et **le projet n'a aucune annulation**.

**Ce qui remplace la garantie** : deux niveaux de risque, et une annulation là où on écrit
sans demander (voir [§4](#4-le-catalogue-dactions)). Un ajout se rattrape d'un appui ; une
correction et une suppression demandent le même appui qu'avant, mais une seule fois et dans
le fil.

### `IA-10` — « rien n'est retenu sans validation »

La mémoire devient automatique. Le modèle repérait déjà ce qui méritait d'être retenu et le
**proposait** ; il l'écrira.

**Ce qui remplace la validation** : la note est écrite avec `source: ia`, elle apparaît dans
le fil au moment où elle est prise — « je retiens : … » —, et elle se corrige ou se retire
depuis le carnet, qui existe déjà (`IA-11`). On passe d'une validation *avant* à une
correction *après*. C'est le bon compromis pour une mémoire, parce qu'une note fausse ne
casse aucun chiffre : elle change ce que l'assistant croit savoir, et cela se lit.

### « Le serveur ne se souvient de rien »

L'absence de fil stocké était documentée avec trois bénéfices : deux onglets ne se mélangent
pas, un rechargement repart propre, aucun fichier ne grossit sans fin.

**Ce qu'on perd, et ce qu'on accepte** : le fichier grossira — décision prise, sans limite
(voir [§5](#5-les-fils)). Les deux autres bénéfices se retrouvent autrement : un fil a une
identité, donc deux onglets sur deux fils différents ne se mélangent pas plus qu'avant, et
un rechargement rouvre le fil courant au lieu de le perdre — ce qui est mieux.

### Ce qui **ne** change pas

- **`IA-12`, le garde-fou médical.** Il devient plus important, pas moins : un assistant qui
  peut écrire ne doit pas créer une semaine de repos parce qu'on lui a parlé d'un genou. La
  consigne l'interdit, l'écran l'affiche, et **aucune action n'est déclenchable par une
  plainte physique**.
- **Aucun calcul métier côté client**, et maintenant : **aucun calcul métier côté modèle**.
  Le modèle choisit une action et ses arguments ; ce sont les services du domaine qui
  valident et qui écrivent, exactement comme pour une saisie à l'écran.
- **La garde `If-Match`.** Une correction par l'IA lit le jeton et le renvoie, comme
  l'écran. Un conflit remonte à l'utilisateur ; il n'est jamais forcé.
- **`AiBlock` et l'état `proposed`** restent la seule façon de dire qu'une valeur est
  proposée.

---

## 2. Les décisions prises

| | Décision |
|---|---|
| **Écriture** | Les **ajouts passent directement**, marqués `ia` et annulables d'un appui depuis le message. **Corriger et supprimer demandent** une confirmation. |
| **Périmètre** | **Tout** : saisie du quotidien, catalogue d'exercices, correction et suppression, planning, objectifs et réglages. |
| **Fils** | **Tout sur Nextcloud, sans limite**, avec suppression manuelle possible. |

---

## 3. L'architecture : étendre le contrat JSON, pas des appels d'outils natifs

C'est la décision technique structurante, et elle va contre l'évidence apparente.

**Le client n'a pas d'appel d'outils.** [`ai/client.py`](../backend/app/domains/ai/client.py)
envoie un `chat/completions` avec `messages` et `temperature`, et rien d'autre.

**Et `ask_json` tourne sur les modèles gratuits d'OpenRouter, avec repli.** Il essaie
jusqu'à `MAX_ATTEMPTS` modèles et garde le premier qui rend un JSON exploitable. C'est ce
qui fait tenir l'assistance sans clé payante — et c'est **incompatible avec les appels
d'outils natifs**, dont le support varie d'un modèle gratuit à l'autre : un modèle sans
outils ne dégraderait pas, il échouerait sec, et le repli n'aurait plus rien à quoi se
replier.

**Donc : le contrat JSON existant s'élargit.** Le modèle rend déjà
`{"reply": …, "remember": […]}`. Il rendra :

```json
{
  "reply": "…",
  "remember": [{ "topic": "…", "note": "…" }],
  "actions": [{ "name": "weight.add", "args": { "date": "2026-08-07", "weight_kg": 82.4 } }],
  "need": ["exercises", "meals.today"]
}
```

Quatre conséquences, toutes bonnes :

1. **Ça marche avec n'importe quel modèle** qui sait rendre du JSON — donc avec le repli.
2. **La validation est la nôtre.** Chaque action est relue par un schéma Pydantic et
   exécutée par le service du domaine. Le modèle ne touche jamais un fichier : il nomme une
   intention, le serveur décide si elle est recevable.
3. **C'est testable sans réseau.** L'analyse des actions va dans
   [`conversation.py`](../backend/app/domains/assistant/conversation.py), qui est un module
   **pur** — mêmes garanties que `progress.py` et `weekly.py`.
4. **Un modèle qui invente une action inconnue est ignoré**, pas propagé.

### `need` — deux passes au plus, jamais une boucle

Pour supprimer le repas de midi, il faut son identifiant ; pour ajouter une série, il faut
l'exercice au catalogue. Un agent classique bouclerait : lire, réfléchir, écrire, relire.

Ici, **deux appels au modèle au maximum** :

1. Le condensé factuel habituel (`IA-09`) + la question → réponse.
2. Si la réponse porte un `need` non vide **et qu'on n'en est qu'à la première passe**, le
   serveur ajoute les tranches de contexte demandées et repose la question. Une fois.

Le plafond est dans le code, pas dans la consigne. Une boucle ouverte sur des modèles
gratuits, c'est une latence imprévisible, un coût imprévisible, et un écran qui tourne sans
qu'on sache pourquoi.

---

## 4. Le catalogue d'actions

Chaque action porte un nom, un schéma d'arguments, et **un niveau**. Le niveau n'est pas une
propriété du modèle : il est fixé côté serveur, dans la table, et le modèle ne peut pas le
changer.

### Niveau `ajout` — s'exécute, s'annule

Écrit tout de suite, marqué `source: ia`, avec un bouton « annuler » dans le message tant
que le fil est ouvert.

| Action | Domaine |
|---|---|
| `weight.add` · `measurement.add` | Corps |
| `run.add` · `workout.add` · `set.add` | Activité |
| `meal.add` | Nutrition |
| `water.add` · `supplement.take` | Routine |
| `exercise.create` | Catalogue |
| `plan.add` | Planning |
| `goal.create` | Objectif |
| `memory.add` | Carnet — automatique, voir [§6](#6-la-mémoire-automatique) |

### Niveau `modification` — demande un appui

Rendu comme une action **en attente** dans le fil, avec ce qu'elle changerait, en clair.
Un appui exécute, un autre écarte. Rien n'est écrit avant.

| Action | Pourquoi ce niveau |
|---|---|
| `weight.edit` · `meal.edit` · `run.edit` · `workout.edit` | Écrase une mesure existante |
| `*.delete` (tous domaines) | Il n'y a pas de corbeille |
| `exercise.edit` | Un exercice mal repris pollue l'historique de charge |
| `goal.close` · `goal.abandon` | Clôt un engagement |
| `settings.update` | Ces valeurs servent de référence à **tous** les écrans |
| `plan.delete` | Idem |

**Aucune action n'est déclenchable par une plainte physique** (`IA-12`) : la consigne
l'interdit, et la table refuse `plan.*`, `goal.*` et `settings.*` quand la question porte
une alerte médicale repérée en relecture.

---

## 5. Les fils

Deux fichiers CSV, sous `assistant/` dans le stockage :

```
assistant/threads.csv    id · created · updated · title · message_count
assistant/messages.csv   thread_id · seq · role · content · actions · created
```

- **Le titre est écrit par le modèle** à la première réponse, en cinq mots. Un fil nommé
  « Discussion du 7 août » ne se retrouve pas ; « Stagnation du développé couché » si.
- **`actions` porte le JSON des actions** du tour, avec leur résultat — c'est ce qui permet
  d'afficher « j'ai ajouté … » et de proposer l'annulation en rouvrant le fil.
- **Un seul `messages.csv`** plutôt qu'un fichier par fil : le dépôt CSV du projet est fait
  pour ça, et une lecture complète reste largement tenable à l'échelle d'un carnet
  personnel. Le jour où ça pèse, la migration est un partitionnement par année, pas un
  changement de forme.
- Sans limite d'âge ni de nombre. L'écran laisse supprimer un fil, et tout vider.

---

## 6. La mémoire automatique

Le modèle rend déjà `remember[]`. Trois changements :

1. **Écrite, plus proposée**, avec `source: ia`.
2. **Dédoublonnée** avant écriture : une note dont le texte normalisé existe déjà n'est pas
   réécrite. Sans cela, dire trois fois qu'on dort mal donne trois lignes identiques et la
   consigne se remplit de redites.
3. **Annoncée dans le fil** — « je retiens : … » — avec un appui pour retirer.

Le carnet (`IA-11`) ne change pas : il reste lisible, corrigeable et vidable à la main,
**sans clé API**.

---

## 7. L'écran

`/assistant` devient l'écran principal, et il est déjà dans la barre d'onglets par la
feuille « Plus ». **Il passe en onglet plein**, à la place de `Nutrition`, qui redescend
dans la feuille — c'est le seul écran qu'on ouvre pour *parler*, et le `⊕` couvre déjà la
saisie rapide.

```
┌──────────────────────────────────────┐
│  ☰  Stagnation du développé couché   │  titre du fil + liste des fils
├──────────────────────────────────────┤
│                                      │
│   ●  moi                             │
│   ○  assistant                       │
│      ┌────────────────────────────┐  │
│      │ ✎ ajouté : 3×8 à 82,5 kg   │  │  action faite, annulable
│      │                  [annuler] │  │
│      └────────────────────────────┘  │
│      ┌────────────────────────────┐  │
│      │ ⚠ supprimer le repas 12:30 │  │  action en attente
│      │        [confirmer] [non]   │  │
│      └────────────────────────────┘  │
│      ↳ je retiens : dors mal…        │  mémoire prise
│                                      │
├──────────────────────────────────────┤
│  [ ta question…              ] [→]   │  collée au bas, au-dessus du clavier
└──────────────────────────────────────┘
```

Points de mise en page qui comptent sur un téléphone :

- **La zone de saisie est ancrée en bas**, au-dessus de la barre d'onglets et de la zone
  sûre, et remonte avec le clavier système. Le champ à 16 px, sans quoi iOS zoome.
- **Le fil défile vers le bas tout seul** à l'arrivée d'une réponse, sauf si on a fait
  défiler vers le haut — sinon on perd sa place en relisant.
- **La liste des fils est une feuille** (`Sheet`, déjà construite), pas une page.
- **Le condensé factuel reste consultable** (`IA-09` l'exige) : replié par défaut sous la
  réponse, pas supprimé.

---

## 8. Ordre d'exécution

| Phase | Contenu | État |
|---|---|---|
| **1** | Fils : `threads.csv`, `messages.csv`, quatre routes, historique lu côté serveur | ✅ 12 tests |
| **2** | Contrat étendu : `actions`, `need`, `title` — trois relectures pures et séparées | ✅ 22 tests, sans réseau |
| **3** | Catalogue : 13 actions, deux niveaux, exécuteur, confirmation, annulation | ✅ 20 tests qui relisent les CSV |
| **4** | Seconde passe : 6 tranches nommées, plafond à deux appels | ✅ 5 tests |
| **5** | Mémoire automatique et dédoublonnage sémantique | ✅ |
| **6** | L'écran : discussion pleine hauteur, cartes d'action, feuilles | ✅ 24 tests + 12/12 à l'audit |
| **7** | Documents : `backlogV2.md`, `etat-du-projet.md` §2, `front.md` | ✅ |

**Ce qui a changé en chemin, et qui n'était pas dans le plan.**

* **Le piège des imports circulaires.** L'en-tête de `assistant/router.py` le documentait ;
  il s'est refermé exactement comme annoncé. Importer un service de domaine fait exécuter
  son paquet, donc son routeur — et les *schémas* n'y échappent pas, `planning/__init__.py`
  important le routeur. Le catalogue se construit donc à la demande sous `@cache`, et ses
  imports vivent dans le corps des fonctions.
* **`WeightService.create` ne savait pas dire d'où venait une pesée** alors que la
  correction préservait déjà la source. Réparé ; `measurements.csv` et `intake_log.csv`
  n'ont toujours pas la colonne, et c'est noté dans l'en-tête du catalogue.
* **`CsvDateTime` et `local_moment`** ajoutés au socle : un fil se range à la seconde, et
  comparer un horodatage naïf — une ligne retapée dans un tableur — à un horodatage situé
  lève une `TypeError`.
* **`useAiStatus` expose `pending`.** Sans lui, `enabled` valait `false` pendant le
  chargement et l'écran déclarait « assistance indisponible » avant d'avoir posé la
  question.
* **Les trois points de l'attente** étaient pilotés par le `isPending` de la mutation et
  restaient affichés après la réponse. L'état est à nous, remis à zéro dans `onSettled`.

**Ce qui n'a pas été fait**, et qui reste ouvert :

* les actions d'un fil **rouvert** ne sont pas rejouées — l'annulation d'un ajout a expiré
  avec le jeton de sa ligne, et proposer un geste qui échouerait serait pire que rien ;
* **la table porte 13 actions, la [§4](#4-le-catalogue-dactions) en annonçait 20.** Ce qui
  y est : `weight.add`, `water.add`, `supplement.take`, `meal.add`, `run.add`,
  `workout.add`, `exercise.create`, `plan.add`, et les cinq suppressions correspondantes.
  Ce qui n'y est pas, et pourquoi :
  * `measurement.add` — `measurements.csv` n'a pas de colonne `source`, donc rien ne
    distinguerait un tour de taille noté par l'assistant d'une saisie ;
  * `set.add` — une série se rattache à une séance existante, ce que le contrat actuel ne
    sait pas désigner ;
  * `goal.create`, `goal.close`, `goal.abandon` — un objectif se pose pour huit semaines,
    et le proposer était déjà le travail de `GOAL-02` ; le doublon aurait deux discours ;
  * `settings.update` et les quatre `*.edit` — corriger champ à champ demande de lire la
    ligne existante pour n'en changer qu'une partie, ce que le contrat ne porte pas ;
* la mesure du taux d'actions correctes sur modèles gratuits, qui ne se fait qu'à l'usage.

À chaque phase : `make check`, puis la page dans un navigateur — **jamais l'un sans
l'autre**. C'est ce qui a trouvé la moitié des défauts de la refonte mobile.

---

## 9. Les deux risques à surveiller

**Les modèles gratuits peuvent peiner — mais ce n'est pas ce qui a cassé.** Le premier
`503` a d'abord été attribué à `nemotron-3-ultra`, qui écrit parfois 3 788 caractères de
raisonnement en prose avant la moindre accolade et se fait tronquer. **Le diagnostic était
faux** : `OPENROUTER_MODEL` vaut `anthropic/claude-sonnet-5`, qui passe en tête des
candidats, et Sonnet répond correctement dans toutes les configurations essayées — y
compris l'ancienne, à 900 jetons et sans mode JSON. Le `503` était donc passager.

Les trois correctifs ci-dessous sont conservés parce qu'ils protègent le **repli**, qui
reste peuplé de modèles gratuits, et parce qu'aucun ne coûte rien. Ils ne sont pas la
réparation d'une panne reproduite.

Trois correctifs, chacun mesuré avant d'être posé :

* **`response_format: {"type": "json_object"}`** sur toutes les requêtes. La consigne
  demandait déjà « uniquement un objet JSON » ; ce champ le dit au *fournisseur*, qui
  contraint le décodage au lieu d'espérer l'obéissance. Vérifié sur les six candidats du
  jour : cinq répondus, aucun refus, le sixième au quota.
* **`MAX_TOKENS` de 900 à 1 600.** 900 suffisaient à `{reply, remember}` ; le contrat en
  porte cinq champs, et la marge sert au raisonnement qui précède parfois la réponse — une
  réponse utile occupe moins de 400 caractères.
* **`MAX_ATTEMPTS` de 3 à 5.** Les modèles gratuits tombent souvent au quota, et trois
  essais partaient parfois entièrement en refus.

**La panne reproductible, elle, était ailleurs.** « Il me manque de quoi le faire : kind »,
cinq fois de suite sur une demande de planning. Deux défauts, tous deux réels :

* **la description des arguments était écrite à côté du schéma.** `plan.add` annonçait
  `"kind": texte` alors que le champ n'accepte que `course`, `muscu` ou `autre` : le modèle
  envoyait « abdos/pecs/bras » et Pydantic refusait. Une consigne fausse ne s'améliore pas
  en la répétant. **La description se génère désormais depuis le schéma** — même source que
  la validation, donc elle ne peut plus mentir ;
* **le refus désignait la mauvaise cause.** `kind` *était* fourni ; il était hors liste. Un
  message qui envoie corriger la mauvaise chose est celui qu'on lit cinq fois.

Et la génération a révélé deux trous que personne ne cherchait : `meal.add` exposait
`source`, donc un modèle pouvait **se déclarer humain** (`IMP-05` défait par un argument),
et `water.add` exposait `datetime`, donc dater une prise d'hier avec l'heure d'aujourd'hui.
Les deux sont retirés de la description **et** des arguments reçus — cacher sans filtrer
n'aurait protégé que du modèle honnête.

Vérifié en conditions réelles : la demande de planning qui échouait cinq fois passe
**5 sur 5** avec le bon `kind`, quatre demandes d'écriture sur quatre donnent `weight.add`
avec un titre juste, et quatre questions d'essai — dont « j'ai mal au genou droit » —
n'écrivent **rien**, ce qui est le garde-fou de `IA-12` tenu par le modèle et pas seulement
par la consigne.

**Le fond du risque demeure.** Rendre un JSON valide, ils savent à peu près faire ;
choisir la bonne action avec les bons arguments demande plus. Deux garde-fous : le serveur
**ignore silencieusement** une action inconnue ou mal formée plutôt que d'échouer l'échange,
et la réponse dit toujours en français ce qui a été fait — si l'action a été ignorée, le
texte ne mentionne rien et l'utilisateur le voit. À surveiller à l'usage : si le taux
d'actions correctes est trop bas, la réponse est une clé payante, pas un correctif de code.

**Une action juste sur la mauvaise ligne.** « Supprime ma pesée » quand il y en a deux le
même jour. Le condensé rendu au modèle porte des identifiants explicites, et une action de
modification affiche **la ligne visée en clair** avant confirmation — c'est précisément ce
que ce niveau sert à permettre.
