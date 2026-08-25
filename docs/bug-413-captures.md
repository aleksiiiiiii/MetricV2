# Prompt — le `413` à l'ajout de captures

> **Corrigé le 25 août 2026.** Ce document reste comme trace du diagnostic et des deux
> pièges — voir « Ce qui a été fait » en fin de page.

---

## Le symptôme

Sur `/activite`, l'import d'une activité Apple : j'ajoute mes captures d'écran, et le
serveur répond **`413`**. Avec une seule capture ça passe parfois, avec plusieurs non.

## Ce qui a déjà été vérifié — ne le refais pas

**Les captures partent brutes.** [`routes/activity/AppleImport.tsx`](../frontend/src/routes/activity/AppleImport.tsx)
met les `File` choisis directement dans le `FormData` (`importsApi.analyze(screenshots)`).
Il n'appelle **pas** `reduceImage`.

**L'autre chemin, lui, réduit.** [`routes/nutrition/MealSheet.tsx`](../frontend/src/routes/nutrition/MealSheet.tsx)
importe `reduceImage` de [`lib/image.ts`](../frontend/src/lib/image.ts) et l'applique avant
d'envoyer — précisément parce qu'une photo de repas de 5 à 8 Mo se faisait refuser par le
reverse-proxy avec un `413` nu. Le correctif existe donc dans le dépôt, il n'a jamais été
appliqué au second chemin.

**Jusqu'à six captures partent dans la même requête.** `MAX_SCREENSHOTS = 6` dans
[`domains/imports/router.py`](../backend/app/domains/imports/router.py).

**Trois plafonds, à ne surtout pas confondre :**

| Où | Combien | Sur quoi |
|---|---|---|
| Nginx Proxy Manager (`docs/deploiement.md`) | `client_max_body_size 16m` | la requête entière |
| `RequestSizeLimit` ([`core/limits.py`](../backend/app/core/limits.py)) | `MAX_REQUEST_BYTES` = 16 Mo | la requête entière, lue sur `Content-Length` |
| `prepare_data_url` ([`domains/ai/images.py`](../backend/app/domains/ai/images.py)) | `MAX_BYTES` = 12 Mo | **une** image |

Le plafond qui saute est un plafond **de requête**, pas d'image : six captures d'iPhone à
2–4 Mo dépassent 16 Mo sans qu'aucune image ne dépasse 12 Mo. C'est pour ça que ça passe à
l'unité et échoue en lot.

## L'argument qui tranche

`images.py` porte `MAX_SIDE = 1024` : **le serveur redimensionne déjà chaque image à
1 024 px de côté** avant de l'envoyer au modèle. Tout pixel envoyé au-delà est transporté
puis jeté. Réduire côté client ne perd donc rien — ça retire du transport ce que le serveur
allait retirer de toute façon.

## Ce que j'attends

1. **Réduire les captures avant l'envoi**, dans `AppleImport.tsx`, comme le fait
   `MealSheet.tsx`. Réemploie `reduceImage` — n'écris pas une seconde réduction.
2. **Dis ce qui a été réduit**, comme l'écran des repas : le poids avant/après avec
   `fileSize`. Un envoi qui rétrécit une image sans le dire est une transformation muette
   sur une donnée que l'utilisateur croit avoir fournie telle quelle.
3. **Ne touche à aucune garde serveur.** Les trois plafonds restent. Le correctif client ne
   les remplace pas — il fait qu'on ne les atteint plus dans l'usage normal.

## Les deux pièges

**Une capture d'écran n'est pas une photo de repas.** Elle porte du **texte** — des
chiffres d'allure, de fréquence cardiaque, de paliers — et c'est un modèle qui doit le lire.
Une compression JPEG agressive rend ces chiffres illisibles, et le symptôme sera un import
qui rate au lieu d'un `413` : un échec plus difficile à diagnostiquer que celui qu'on
corrige. `MAX_SIDE = 1600` et `QUALITY = 0.8` sont les valeurs pensées pour une assiette.
**Vérifie sur une vraie capture** que la lecture marche encore après réduction, et si elle
ne marche pas, passe des options à `reduceImage` plutôt que de changer ses défauts — l'écran
des repas s'en sert et n'a pas le même besoin.

**Deux captures, deux réductions, et la mémoire de l'onglet.** `AppleImport.tsx` porte déjà
un commentaire là-dessus (« recommencer trois fois laisse trois images vivantes dans la
mémoire de l'onglet »). Regarde ce qu'il fait des `File` remplacés avant d'en ajouter un
étage.

## Vérifier

- `make check` vert.
- Un test d'écran sur `/activite` : six captures choisies produisent un envoi réduit, et le
  poids annoncé est celui d'après réduction.
- **Et un vrai import**, sur de vraies captures Apple, avec l'API branchée sur le stockage
  réel. C'est la seule étape qui dit si le modèle lit encore les chiffres.


---

## Ce qui a été fait (25 août 2026)

`AppleImport.tsx` réduit les captures **au moment du choix**, comme `MealSheet.tsx`, en
réemployant `reduceImage` — aucune seconde réduction n'a été écrite.

**Trois décisions valent d'être nommées :**

1. **La qualité monte à 0,92**, `maxSide` ne bouge pas. Une capture porte des chiffres qu'un
   modèle doit lire, et le serveur la réencodera une seconde fois en JPEG : deux
   compressions à 0,8 feraient baver un `5:12` en `5:l2`, et le symptôme serait un import
   qui rate — plus difficile à diagnostiquer que le `413` qu'on corrige. Le côté long est ce
   qui pèse, la qualité ne coûte presque rien. Les options passent à l'appel : `MAX_SIDE` et
   `QUALITY` restent ceux de l'écran des repas, qui n'a pas le même besoin.
2. **Le poids est annoncé** — `1,4 Mo → 312 ko` — parce qu'une transformation muette sur une
   donnée que l'utilisateur croit avoir fournie telle quelle serait pire que le défaut.
3. **Retirer une capture ne relance pas de réduction.** Les fichiers retenus le sont déjà,
   et repasser un JPEG dans l'encodeur ne ferait que le dégrader.

**Le choix est une mutation** et non un appel direct : réduire six captures prend une
seconde sur un téléphone, et `isPending` est ce qui empêche l'écran de paraître figé.

**Aucune garde serveur n'a bougé.** Les trois plafonds restent ; le correctif client fait
qu'on ne les atteint plus dans l'usage normal.

**Vérifié** : `make check` vert, et trois tests d'écran — chaque capture passe au réducteur,
le poids est annoncé, et ce sont les fichiers **réduits** qui partent dans le `FormData`.
`reduceImage` y est doublé, faute de canevas en jsdom : ce qui est vérifié est le contrat de
l'écran, pas le moteur de rendu.

**Ce qui reste à faire par toi** : un vrai import, sur de vraies captures Apple, contre le
stockage réel. C'est la seule étape qui dit si le modèle lit encore les chiffres après
réduction — et je ne peux pas la faire à ta place.
