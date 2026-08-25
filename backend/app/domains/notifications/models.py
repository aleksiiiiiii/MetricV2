"""Modèles CSV des notifications push (`NOT-01`, `NOT-02`).

`notifications/subscriptions.csv` : id, created, endpoint, p256dh, auth, user_agent
`notifications/sent.csv`          : date, kind, sent_at

**Les deux fichiers sont de la famille *planning*** au sens du §2 de
`docs/etat-du-projet.md` : chaque colonne porte un défaut, les dates s'annotent `CsvDate`
et les horodatages `CsvDateTime`. Ce ne sont pas des mesures — personne ne les ouvre pour
y lire un chiffre de suivi — et une cellule abîmée n'a aucune raison d'empêcher un rappel
de partir, encore moins de faire tomber un écran.

C'est la leçon directe du `502` qu'une cellule `time` vide de `supplements/schedule.csv` a
coûté au tableau de bord entier lors du premier usage réel.

Deux choix méritent une explication.

**`sent.csv` est un fichier, pas une variable.** L'ordonnanceur doit se souvenir de ce
qu'il a envoyé *à travers un redémarrage*, sinon relancer l'API à 20 h 30 renvoie le rappel
de 20 h. Et comme tout le stockage du projet, il se lit dans un tableur : « quand ai-je été
rappelé, et de quoi » est exactement la question qu'on se pose le jour où un rappel arrive
au mauvais moment.

**L'abonnement porte son `endpoint` en clair**, qui est sa véritable identité — c'est le
navigateur qui le choisit, et c'est lui que le service push reconnaît. La colonne `id` sert
au dépôt CSV ; deux lignes de même `endpoint` seraient un doublon, pas deux appareils.
"""

from __future__ import annotations

from app.storage.model import CsvDate, CsvDateTime, CsvModel


class SubscriptionRow(CsvModel):
    """Un appareil abonné aux notifications. `notifications/subscriptions.csv`.

    Les trois valeurs qui comptent — `endpoint`, `p256dh`, `auth` — viennent telles quelles
    de `PushSubscription.toJSON()` côté navigateur. On ne les interprète jamais : elles
    repartent au chiffrement exactement comme elles sont arrivées.
    """

    id: str = ""
    #: Date d'abonnement. Sert à dire « depuis quand », jamais à décider quoi que ce soit.
    created: CsvDate = None
    #: Adresse du service push, choisie par le navigateur. C'est l'identité de la ligne.
    endpoint: str = ""
    #: Clé publique de l'appareil, base64url. Entre dans l'échange ECDH.
    p256dh: str = ""
    #: Secret d'authentification de l'abonnement, base64url.
    auth: str = ""
    #: Ce que le navigateur a annoncé de lui-même, pour distinguer deux appareils à
    #: l'écran. Purement informatif — aucune décision ne s'y appuie.
    user_agent: str = ""


class SentRow(CsvModel):
    """Un rappel effectivement envoyé. `notifications/sent.csv`.

    La clé est le triplet **(`date`, `kind`, `slot`)** : un rappel par contrôle et par
    jour. Elle n'est pas déclarée au dépôt — le stockage du projet ne connaît pas les
    contraintes d'unicité — mais c'est elle que l'ordonnanceur consulte avant chaque envoi.

    **`slot` a été ajouté quand l'hydratation a gagné trois contrôles** (**N2**). Sans lui,
    celui de 14 h éteindrait ceux de 18 h et de 22 h 30 : le couple (`date`, `kind`) ne
    distingue pas deux moments de la même journée.
    """

    #: Jour **local** du rappel (`HEAT-32`), jamais UTC.
    date: CsvDate = None
    #: Type de rappel : `supplements`, `hydration`, `meals`, `workout`, `protein`.
    kind: str = ""
    #: L'heure du contrôle, `HH:MM`.
    #:
    #: **Vide sur les lignes écrites avant ce lot**, et c'est lu comme « ce type est parti
    #: aujourd'hui, à un moment qu'on ne sait plus ». Le repli est volontairement
    #: conservateur : il éteint tous les contrôles de ce type pour la journée, plutôt que
    #: de risquer un doublon le jour du déploiement. La divergence dure une journée
    #: (`STO-04`).
    slot: str = ""
    #: Instant exact de l'envoi, avec décalage. Sert à relire l'historique à l'œil ; la
    #: décision, elle, ne regarde que le jour.
    sent_at: CsvDateTime = None
