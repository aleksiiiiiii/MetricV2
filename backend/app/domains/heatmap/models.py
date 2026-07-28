"""Modèles CSV du moteur d'assiduité (spec `HEAT` v2, §9).

Trois fichiers sous `settings/` (décision **D2**), et une contrainte de forme qui les
traverse : **une cellule doit rester lisible dans un tableur** (`STO-02`). Le CSV utilise
déjà la virgule comme séparateur de colonnes ; les listes internes prennent donc le
point-virgule, ce qui évite d'avoir à protéger la cellule par des guillemets et laisse
`min_count=1;window_days=2` ou `1;3;6;10` lisibles à l'œil.

Aucune de ces lignes ne décrit ce qui s'est passé : elles décrivent ce qu'on **attend**.
Les données d'assiduité, elles, sont les fichiers des domaines de saisie, et le moteur ne
les écrit jamais — supprimer une piste n'efface aucune mesure (`HEAT-21`).
"""

from __future__ import annotations

from datetime import date

from app.storage.model import CsvModel


class TrackRow(CsvModel):
    """Une piste. `settings/heatmap_tracks.csv`.

    Tous les champs sauf `id` portent un défaut : ce fichier est destiné à être édité à
    la main, et une colonne laissée vide doit donner une piste utilisable plutôt qu'un
    fichier illisible — la leçon du lot L08 sur `settings.csv`.
    """

    id: str
    label: str = ""
    #: Clé du registre de sources (`HEAT-02`). Une source inconnue désactive la piste
    #: plutôt que de faire tomber la lecture : voir `TrackService`.
    source: str = ""
    #: Sens dépendant de la source : groupes musculaires séparés par `;`, identifiant de
    #: supplément, ou vide. Le mapping groupe musculaire → piste est **ici**, dans la
    #: configuration, et non dans une constante du code (`heat_backlog` §5).
    filter: str = ""
    #: Seuil de validation (`HEAT-04`). Jamais une constante : l'eau se valide à 1500 ml,
    #: une série d'abdos à 1.
    validation_threshold: float = 1
    #: Quatre bornes croissantes d'intensité, `1;3;6;10` (`HEAT-15`).
    levels: str = ""
    #: Un seul niveau : une prise est une prise (`HEAT-16`).
    binary: bool = False
    #: Ton de la charte — `signal`, `effort`, `load`, `recover`.
    accent: str = "signal"
    position: int = 0
    #: Désactiver plutôt que supprimer conserve l'historique (`HEAT-21`).
    active: bool = True
    #: Date d'entrée de la piste. Immuable, et c'est ce qui rend `HEAT-07` vrai : ajouter
    #: la créatine aujourd'hui ne rend pas rouges les six mois précédents.
    created: date | None = None


class CadenceRow(CsvModel):
    """Une prise d'effet de cadence. `settings/heatmap_cadences.csv`.

    **Journal en ajout seul** (décision **D3**) : on n'y modifie ni n'y supprime jamais
    une ligne. Changer une cadence en ajoute une nouvelle, datée du jour du changement.

    C'est ce qui rend `HEAT-14` vrai. Passer la whey d'un jour sur deux à un jour sur
    trois aujourd'hui ne doit pas réécrire le verdict des mois passés : le moteur lit la
    ligne dont `valid_from` est la plus récente **antérieure au jour jugé**.
    """

    id: str
    track_id: str
    type: str = "daily"
    #: Paramètres sérialisés, `min_count=1;window_days=2`.
    params: str = ""
    valid_from: date | None = None


class OffDayRow(CsvModel):
    """Une plage neutralisée. `settings/heatmap_off_days.csv`.

    Maladie, voyage, deload : ces jours passent en `off` quelle que soit la cadence et ne
    comptent ni comme réussite ni comme échec (`HEAT-06`). Une grippe ne casse pas une
    série de quatre-vingt-dix jours.

    `track_id` vide neutralise **toutes** les pistes — le cas d'une semaine d'arrêt.
    """

    id: str
    track_id: str = ""
    date_from: date | None = None
    date_to: date | None = None
    reason: str = ""

    def covers(self, day: date) -> bool:
        """Vrai si `day` tombe dans la plage, bornes comprises.

        Une plage dont une borne manque ne couvre rien : un fichier édité à la main peut
        porter une ligne inachevée, et neutraliser l'éternité par mégarde serait pire que
        de l'ignorer.
        """
        if self.date_from is None or self.date_to is None:
            return False
        return self.date_from <= day <= self.date_to
