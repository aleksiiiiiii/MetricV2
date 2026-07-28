"""Modèle CSV des réglages. `settings/settings.csv` : key, value.

Un clé/valeur volontairement dégénéré : deux colonnes, aucune typage dans le fichier.
C'est ce qui permet d'ajouter un réglage sans migration, et de le corriger dans un
tableur sans connaître le schéma. Le typage vit dans `schemas.py`, à la frontière.

**Décision D2** : le fichier est sous `settings/` et non à la racine comme le pose
l'annexe du backlog. Un fichier `settings.csv` et un dossier `settings/` au même niveau
est légal mais piégeux.
"""

from __future__ import annotations

from app.storage.model import CsvModel


class SettingRow(CsvModel):
    #: Les deux colonnes ont une valeur par défaut, et ce n'est pas un oubli. Une cellule
    #: vide est une possibilité normale dans un fichier édité à la main — un réglage
    #: qu'on vide pour « revenir au défaut », une ligne restée en chantier. Sans défaut,
    #: cette cellule lèverait une erreur de schéma et rendrait illisible **tout** le
    #: fichier : plus de poids cible, plus d'objectif d'hydratation, plus un écran qui
    #: s'affiche. Un réglage abîmé doit coûter son propre repli, pas l'application.
    key: str = ""
    value: str = ""
