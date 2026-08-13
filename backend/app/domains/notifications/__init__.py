"""Domaine Notifications push et rappels (`NOT-01` → `NOT-03`).

Un seul routeur, monté dans le groupe protégé de `app/domains/api.py` — sans exception :
le flux `.ics` du planning est la seule route de données du projet à échapper au jeton, et
le §2 de `docs/etat-du-projet.md` dit qu'une deuxième n'y aurait pas droit.

Ce domaine possède deux fichiers CSV et **ne calcule aucune donnée de suivi** : il lit ce
que les autres domaines savent déjà — la checklist des suppléments, le total
d'hydratation, le compte de repas, le planning du jour — pour décider s'il y a quelque
chose à rappeler.

Trois modules valent d'être lus dans cet ordre :

* [`reminders.py`](reminders.py) — **pur**. Ce qui est dû, et ce que ça dit. C'est là que
  vit la règle qui gouverne le lot : un rappel dit ce qui n'est **pas noté**, jamais ce qui
  n'a pas été fait.
* [`scheduler.py`](scheduler.py) — **coud**. Lit, appelle le module pur, envoie, consigne.
  Aucune règle n'y vit.
* [`push.py`](push.py) — le transport. Le seul endroit qui sache ce qu'est `aes128gcm`, et
  il n'en écrit pas une ligne.
"""

from app.domains.notifications.router import router

__all__ = ["router"]
