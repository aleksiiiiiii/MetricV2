# Patron de domaine

Le domaine **Corps** (`backend/app/domains/body/`) est la première tranche verticale du
projet, et sert de référence aux cinq suivants. Ce document décrit ce qui doit être
recopié, et surtout **pourquoi**.

Un domaine se recopie en quatre fichiers, une clé de cache et un écran.

---

## 1. Backend — quatre fichiers, quatre responsabilités

```
app/domains/<domaine>/
├── __init__.py     n'exporte que `router`
├── models.py       ce que contient le fichier CSV
├── schemas.py      ce qui circule sur l'API
├── service.py      les calculs
└── router.py       les endpoints, minces
```

### `models.py` — le fichier

Un `CsvModel` par fichier, avec **exactement** les colonnes de l'annexe du backlog. Ce
modèle décrit le fichier tel qu'il est sur Nextcloud, y compris ses lignes anciennes :
tout champ doit donc tolérer d'être absent si le fichier précède son ajout (`STO-04`).

```python
class WeightRow(CsvModel):
    date: date
    weight_kg: float
    note: str | None = None
    source: str = "manual"
```

> Une valeur par défaut n'est pas un détail : c'est ce qui permet d'ajouter une colonne
> sans invalider trois ans d'historique.

### `schemas.py` — l'API

Deux familles distinctes, et la distinction compte :

* **charge utile** (`WeightPayload`) — ce que le client envoie. Elle porte les bornes de
  vraisemblance de `app.core.validation` : `PastDate`, `WeightKg`, `Note`. Le fichier
  peut contenir une ligne partielle héritée ; une saisie, non.
* **entrée** (`WeightEntry`) — ce que le client reçoit. Elle porte toujours `id` et
  `token`.

Une **vue** (`WeightView`) regroupe indicateurs, série et historique en une seule
réponse. Trois requêtes pour peindre un écran seraient trois allers-retours vers
Nextcloud.

### `service.py` — les calculs

**Tout calcul vit ici.** Moyenne mobile, écart à l'objectif, sens de variation : rien de
tout cela ne doit exister côté client. La règle vient de `HEAT-30` mais vaut partout —
deux implémentations d'une même moyenne divergent au premier cas limite, et c'est
l'utilisateur qui arbitre entre deux chiffres qui devraient être le même.

Deux pièges rencontrés sur le domaine Corps, qui se reposeront ailleurs :

* **L'ordre du fichier n'est pas l'ordre chronologique.** On peut enregistrer aujourd'hui
  une pesée d'avant-hier. Les séries se trient par date, l'historique par date
  décroissante, et l'`id` reste la position dans le fichier.
* **Une fenêtre temporelle se compte en jours, pas en points.** La tendance 7 jours est
  une moyenne des relevés des 7 derniers *jours*. Une moyenne des 7 derniers *relevés*
  couvrirait trois semaines après une pause, et lisserait la mauvaise chose.

### `router.py` — les endpoints

Minces : ils valident, appellent le service, rendent. Aucune logique.

```python
@router.get("/weight", response_model=WeightView)
async def read_weight(store: StoreDep, limit: Limit = 50, offset: Offset = 0) -> WeightView:
    return await WeightService(store).view(limit=limit, offset=offset)
```

Le routeur n'a **pas** à déclarer d'authentification : il est monté dans le groupe
protégé de `app/domains/api.py`, et un test structurel vérifie à chaque exécution que
toute opération publiée exige un jeton (`AUTH-05`).

---

## 2. La garde anti-conflit, en HTTP

`STO-05` exige qu'une modification annonce les valeurs qu'elle s'attend à trouver. Le
projet le traduit en un **jeton de ligne** :

| Étape | Mécanisme |
|---|---|
| Lecture | chaque entrée porte `token`, empreinte de son contenu (`Row.token`) |
| Écriture | le client le renvoie dans l'en-tête `If-Match` |
| Conflit | jeton absent ou périmé → `409 conflict`, rien n'est écrit |

Un `If-Match` **absent** est traité comme un conflit, jamais comme une permission :
sinon la garde se contournerait en omettant l'en-tête.

Côté dépôt, `replace_by_token` et `delete_by_token` font une seule lecture fraîche — le
jeton *est* la garde, il n'y a pas à comparer les valeurs une seconde fois.

```python
await repo.replace_by_token(index, token, item)
await repo.delete_by_token(index, token)
```

---

## 3. Frontend — trois pièces

```
src/features/<domaine>/api.ts    types + appels, aucun calcul
src/routes/<Écran>.tsx           l'écran
src/lib/query.ts                 la clé de cache du domaine
```

### `api.ts`

Les types reflètent **exactement** les schémas du serveur. Aucune dérivation : ce qui
arrive est déjà calculé.

### Invalidation croisée

Une écriture invalide son domaine **et** les vues transverses :

```ts
void client.invalidateQueries({ queryKey: keys.body.all() });
for (const key of CROSS_CUTTING) void client.invalidateQueries({ queryKey: key });
```

`CROSS_CUTTING` couvre les agrégats (`AGG-01`) et les grilles d'assiduité (`HEAT-33`).
Sans cela, enregistrer une pesée laisserait le tableau de bord mentir jusqu'à la
prochaine navigation.

### L'écran

Quatre états, jamais trois : **chargement**, **vide**, **erreur**, **données**. L'état
vide dit ce que coûte le prochain geste — « Un chiffre le matin, et la courbe commence » —
et n'affiche **aucune valeur inventée**. Dans une application de mesure, un faux chiffre
est pire qu'un tiret.

Le message d'erreur vient du serveur et s'affiche tel quel : il est déjà en français. Le
client décide sur le `code`, jamais sur le texte (`API-07`).

---

## 4. Ce qu'il faut tester

La batterie du domaine Corps (`backend/tests/test_body.py`) couvre huit familles, toutes
transposables :

1. **Écriture réelle dans le CSV** — en-tête, ordre des colonnes, accents, BOM.
2. **Bornes refusées** — date future, valeur aberrante.
3. **Garde anti-conflit** — jeton absent, jeton périmé, et le fichier resté intact après
   un refus.
4. **Préservation de la provenance** — corriger une valeur importée ne la transforme pas
   en saisie manuelle (`IMP-05`).
5. **Indicateurs** — y compris sur historique vide, où l'API doit répondre sans échouer.
6. **Fenêtres de calcul** — la borne exacte (huit relevés, sept jours), pas « à peu près ».
7. **Ordre** — série chronologique même si le fichier est écrit dans le désordre.
8. **Pagination** — `limit`, `offset`, et `total` qui reste le total.

Côté frontend, le parcours **saisir → corriger → supprimer**, en vérifiant que le jeton
lu est bien celui renvoyé en `If-Match`.

---

## 5. Liste de reprise

- [ ] `models.py` aligné sur l'annexe CSV du backlog, défauts sur les champs récents
- [ ] `schemas.py` : charge utile bornée, entrée avec `id` et `token`, vue unique
- [ ] `service.py` : aucun calcul laissé au client
- [ ] `router.py` : mince, `If-Match` exigé sur `PATCH` et `DELETE`
- [ ] Chemin de fichier déclaré dans `app/storage/paths.py`
- [ ] Routeur ajouté au groupe protégé de `app/domains/api.py`
- [ ] Clé de cache ajoutée à `src/lib/query.ts`
- [ ] Écran avec ses quatre états, sans valeur inventée
- [ ] Invalidation croisée après écriture
- [ ] Les huit familles de tests backend, plus le parcours frontend
