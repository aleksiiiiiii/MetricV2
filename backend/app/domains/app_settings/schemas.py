"""Formes échangées pour les réglages (`L08-01`, `L08-02`).

Le fichier ne connaît que du texte ; l'API, elle, rend des valeurs typées. La frontière
est ici, et elle porte deux garanties.

**Les valeurs de repli sont servies, pas dupliquées.** Le backlog exige que backend et
frontend s'accordent sur ce que vaut un objectif non renseigné. Le faire tenir par la
discipline — la même constante recopiée dans deux langages — durerait jusqu'au premier
oubli. La réponse porte donc à la fois les valeurs effectives et les défauts, et le
client n'en code aucun.

**Une modification est partielle.** L'écran des réglages n'écrit que ce qu'il a changé :
un champ absent de la requête reste à sa valeur, il n'est pas remis à son défaut.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.validation import (
    BaseUrl,
    HydrationTargetMl,
    Label,
    ProteinG,
    SugarG,
    VolumeMl,
    WeightKg,
)


class SettingsValues(BaseModel):
    """Réglages typés (`L08-02`)."""

    target_weight_kg: float = Field(description="Objectif de poids, `BODY-03`")
    target_protein_g: float = Field(description="Objectif quotidien de protéines, `NUT-06`")
    max_added_sugar_g: float = Field(description="Plafond de sucres ajoutés, `NUT-06`")
    target_hydration_ml: int = Field(description="Objectif quotidien d'hydratation, `HYD-03`")
    hydration_presets_ml: list[int] = Field(description="Raccourcis de volume, `HYD-02`")
    heatmap_metric: str = Field(description="Métrique mise en avant, `HEAT-08`")
    #: Adresse de Cadence Tabata, l'application qui exécute les séances (**D1**).
    #:
    #: **Vide par défaut, et c'est un état qui a un sens** : la fonctionnalité est en
    #: sommeil. Aucun domaine deviné, aucune adresse en dur — le seul autre choix aurait
    #: été d'écrire un domaine dans le code, où il ne se corrige qu'en redéployant.
    #:
    #: Homonyme assumé avec `app/core/cadence.py`, qui décrit la **fréquence** d'une piste
    #: d'assiduité, et avec `RunRow.cadence_spm`, qui compte des pas. Ici, « Cadence » est
    #: le nom d'une application tierce ; les trois ne se croisent dans aucun fichier.
    cadence_base_url: str = Field(description="Adresse de base de Cadence Tabata")


class SettingsPayload(BaseModel):
    """Modification partielle. Un champ omis n'est pas touché."""

    target_weight_kg: WeightKg | None = None
    target_protein_g: ProteinG | None = None
    max_added_sugar_g: SugarG | None = None
    target_hydration_ml: HydrationTargetMl | None = None
    #: Entre un et six raccourcis : au-delà, la rangée de boutons cesse d'être un geste.
    hydration_presets_ml: list[VolumeMl] | None = Field(default=None, min_length=1, max_length=6)
    #: Volontairement **non contraint à une liste fermée**. Les pistes d'assiduité sont
    #: des données utilisateur créées au lot L09 ; figer ici un vocabulaire que ce lot
    #: remplacera obligerait à rejeter une piste légitime, ou à mentir sur son nom.
    heatmap_metric: Label | None = None
    #: `BaseUrl` accepte la chaîne vide, et le service l'écrit au lieu de l'ignorer : ce
    #: réglage est le seul de cette liste qu'on doit pouvoir **effacer**, puisqu'il n'a
    #: pas de valeur de repli sur laquelle retomber.
    cadence_base_url: BaseUrl | None = None


class SettingsView(BaseModel):
    """Réponse unique de l'écran Réglages."""

    values: SettingsValues
    #: Ce que vaut chaque réglage non renseigné. Servi pour que le client n'ait aucune
    #: valeur de repli à connaître — donc aucune occasion de diverger du serveur.
    defaults: SettingsValues
    #: Clés effectivement présentes dans le fichier. Le reste vient des défauts, et
    #: l'écran peut le dire au lieu de faire passer un repli pour un choix.
    stored: list[str]
    #: Garde anti-conflit du fichier entier (`STO-05`), à renvoyer en « If-Match ».
    token: str
