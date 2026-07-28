"""Formes échangées pour les agrégats (`AGG-01` → `AGG-04`).

Un principe gouverne ce module : **il ne définit presque rien.** Les indicateurs de poids,
les totaux d'entraînement, les macros du jour, l'hydratation et le ratio de suppléments
sont les schémas de leurs domaines, importés tels quels. Redéclarer ici un
`DashboardWeight` avec les mêmes champs aurait créé un second endroit où corriger une
unité — et une occasion de la corriger d'un seul côté.

Seuls deux objets sont propres aux agrégats, parce qu'ils n'appartiennent à aucun
domaine : la **série d'assiduité**, qui les traverse tous (`AGG-03`), et le **contrat de
série temporelle**, qui vaut pour n'importe quelle métrique (`AGG-04`).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.domains.activity.schemas import TrainingTotals
from app.domains.body.schemas import WeightStats
from app.domains.hydration.schemas import HydrationStats
from app.domains.nutrition.schemas import DayTotals
from app.domains.supplements.schemas import DayRatio

# ── Série d'assiduité (`AGG-03`) ──────────────────────


class StreakDay(BaseModel):
    """Un jour de la fenêtre récente."""

    date: date
    active: bool
    #: Domaines renseignés ce jour-là. Vide n'est pas la même chose qu'absent : le jour
    #: est retourné quoi qu'il arrive, la plage n'a pas de trou.
    sources: list[str] = Field(default_factory=list)


class Streak(BaseModel):
    """Jours consécutifs avec au moins une donnée, toutes sources confondues.

    À ne pas confondre avec `HEAT-27`, la série cadence-consciente par piste. Celle-ci
    mesure l'**assiduité de suivi** — ai-je noté quelque chose — l'autre mesure le respect
    d'un engagement. Ce sont deux algorithmes distincts et ils le resteront.
    """

    #: Série en cours. La journée d'hier reste valide tant que celle du jour n'est pas
    #: terminée : sinon la série se casserait chaque matin au réveil.
    current: int
    longest: int
    #: Nombre total de jours ayant reçu au moins une donnée.
    active_days: int
    #: Les sept derniers jours, le plus ancien en premier.
    last_seven: list[StreakDay]


# ── Séries temporelles génériques (`AGG-04`) ──────────


class MetricSubject(BaseModel):
    """Sujet d'une métrique paramétrée — un exercice, par exemple."""

    key: str
    label: str


class MetricDescriptor(BaseModel):
    """Une entrée du catalogue de métriques.

    Publié pour que le sélecteur de l'écran ne code aucune liste en dur : ajouter une
    métrique au serveur la rend choisissable sans toucher au client.
    """

    key: str
    label: str
    unit: str
    #: « day » ou « week ». Le client s'en sert pour formater l'axe, pas pour calculer.
    granularity: str
    #: Sujets disponibles quand la métrique en exige un. Vide sinon.
    subjects: list[MetricSubject] = Field(default_factory=list)


class SeriesPoint(BaseModel):
    date: date
    value: float


class SeriesStats(BaseModel):
    """Les cinq chiffres qui accompagnent une série (`AGG-04`).

    Tous `None` sur une plage vide, et c'est délibéré : un zéro s'afficherait comme une
    mesure alors qu'il n'y a rien eu à mesurer.
    """

    latest: float | None = None
    latest_date: date | None = None
    #: Écart entre le premier et le dernier point **de la plage retournée**. Changer de
    #: plage change donc la variation, ce qui est la lecture attendue.
    change: float | None = None
    average: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    count: int


class SeriesView(BaseModel):
    """Contrat unique, réutilisé pour toute métrique suivie (`AGG-04`)."""

    metric: str
    label: str
    unit: str
    granularity: str
    subject: str | None = None
    range: str = Field(description="« 1m », « 3m » ou « all »")
    points: list[SeriesPoint]
    stats: SeriesStats


# ── Tableau de bord (`AGG-01`) ────────────────────────


class DashboardView(BaseModel):
    """Tous les indicateurs de synthèse en une requête.

    C'est la raison d'être du lot : dix appels parallèles au chargement de l'écran
    d'accueil signifieraient dix allers-retours vers Nextcloud.

    La série est **incluse** plutôt que demandée à part, pour que la première peinture de
    l'écran — graphique compris — tienne en un appel. Changer de métrique ou de plage
    interroge ensuite `/aggregates/series`, et rien d'autre n'est rechargé.
    """

    date: date
    weight: WeightStats
    training: TrainingTotals
    nutrition: DayTotals
    hydration: HydrationStats
    supplements: DayRatio
    streak: Streak
    series: SeriesView
    #: Métrique mise en avant (`HEAT-08`), telle que réglée par l'utilisateur.
    highlight: str
