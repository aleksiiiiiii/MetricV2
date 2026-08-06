"""Avancement vers une cible chiffrée (`GOAL-04`).

**Ce module ne lit rien.** Ni fichier, ni HTTP, ni horloge : on lui passe une série de
couples `(jour, valeur)`, une politique de réduction et une date d'observation, il rend un
nombre. C'est le même parti pris que `heatmap/engine.py`, et pour la même raison — chaque
cas de ce fichier est un test de dix lignes, sans application à monter.

## Ce que ce calcul n'est pas

**Ce n'est pas un quatrième taux.** `AGG-03` mesure l'assiduité de *suivi* — a-t-on relevé
quelque chose ce jour-là. `HEAT-27` mesure le respect d'un *engagement* de cadence.
`PLAN-06` mesure le respect d'un *rendez-vous*. Aucun des trois ne répond à la question
posée ici, qui est « de combien me suis-je rapproché d'un chiffre que je me suis fixé ».
Les quatre resteront distincts : les confondre donnerait une valeur dont personne ne
saurait dire ce qu'elle compte.

## Pourquoi un point de départ, et pas seulement une cible

`courant / cible` serait faux dès le premier objectif de poids : viser 78 kg quand on en
pèse 82 donnerait 105 % d'avancement le jour de l'adoption. La progression se mesure donc
**depuis le point de départ** — la valeur qu'avait la métrique le jour où l'objectif a été
adopté, relue dans les mêmes données. Une seule formule couvre alors les cinq métriques,
qu'elles doivent monter ou descendre, et le sens de l'objectif n'a pas à être déclaré
quelque part où il pourrait mentir.

Corollaire : rien n'est stocké en plus des onze colonnes de l'annexe. Le point de départ
se **redéduit** de `created`, il ne se recopie pas.

## Pourquoi des périodes complètes

La fenêtre d'observation s'arrête à la veille, ou au dimanche dernier. Compter le mardi en
cours dans une moyenne hebdomadaire ferait ressembler chaque lundi matin à un effondrement,
pour remonter le dimanche soir — un chiffre qui ment cinq jours sur sept. C'est la même
règle que la série d'assiduité de `AGG-03`, qui ne casse pas sur la journée en cours.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from app.core.dates import week_start

#: Comment une série devient une valeur courante. Le type vit ici et non dans
#: `metrics.py` pour que ce module ne dépende de rien d'autre que du découpage du temps :
#: importer le registre des métriques pour une annotation lui coûterait sa pureté.
Reduction = Literal["latest", "rate"]

#: Jours observés pour une métrique quotidienne — la semaine révolue.
DAY_WINDOW = 7

#: Semaines observées pour une métrique hebdomadaire. Quatre, comme l'historique servi au
#: modèle par `PLAN-03` : assez pour lisser une semaine de vacances, assez peu pour que le
#: chiffre décrive encore la période en cours.
WEEK_WINDOW = 4


def window(granularity: str, as_of: date) -> tuple[date, date, int]:
    """Bornes de la fenêtre observée et nombre de périodes qu'elle contient.

    Les deux bornes sont **incluses**, et la fenêtre s'arrête avant la période en cours.
    Le troisième membre est le diviseur d'une cadence : il vaut le nombre de périodes de
    la fenêtre, jamais le nombre de périodes qui portent une donnée. Une semaine sans
    séance compte pour une semaine à zéro séance, sinon quatre semaines de repos suivies
    d'une semaine à six séances afficheraient six séances par semaine.
    """
    if granularity == "week":
        current = week_start(as_of)
        return current - timedelta(weeks=WEEK_WINDOW), current - timedelta(days=1), WEEK_WINDOW
    return as_of - timedelta(days=DAY_WINDOW), as_of - timedelta(days=1), DAY_WINDOW


def latest(points: list[tuple[date, float]], as_of: date) -> tuple[float, date] | None:
    """Dernier relevé connu au plus tard le jour `as_of`.

    Sans fenêtre : une pesée d'il y a trois semaines reste le poids qu'on connaît. Sa date
    revient avec elle, pour que l'écran puisse dire de quand elle date plutôt que de la
    faire passer pour celle de ce matin.
    """
    seen = [point for point in points if point[0] <= as_of]
    if not seen:
        return None
    day, value = max(seen, key=lambda point: point[0])
    return value, day


def rate(points: list[tuple[date, float]], granularity: str, as_of: date) -> float:
    """Cadence moyenne sur la fenêtre : total observé divisé par le nombre de périodes.

    Rend `0.0` et non `None` quand rien n'a été relevé : n'avoir couru aucun kilomètre en
    quatre semaines est une information, pas une absence d'information. C'est la limite
    exacte de « aucune valeur inventée à l'écran » — on ne compte que ce qui se compte,
    et une séance non faite se compte.
    """
    start, end, periods = window(granularity, as_of)
    total = sum(value for day, value in points if start <= day <= end)
    return total / periods


def current_value(
    points: list[tuple[date, float]],
    *,
    reduction: Reduction,
    granularity: str,
    as_of: date,
) -> tuple[float | None, date | None]:
    """Valeur courante d'une métrique, et la date à laquelle elle se rapporte.

    `None` n'arrive que pour une mesure — un poids jamais relevé. Une cadence rend
    toujours un nombre.
    """
    if reduction == "latest":
        found = latest(points, as_of)
        return (None, None) if found is None else found
    _, end, _ = window(granularity, as_of)
    return rate(points, granularity, as_of), end


def ratio(baseline: float | None, current: float | None, target: float) -> float | None:
    """Avancement du point de départ vers la cible, borné à `[0, 1]`.

    `None` quand l'un des deux bouts manque : sans point de départ, « à mi-chemin » ne
    veut rien dire, et un zéro tiendrait lieu de mesure alors qu'il n'y en a pas.

    Bornée des deux côtés, et les deux bornes disent quelque chose de vrai. Au-delà de la
    cible, l'objectif est atteint et 130 % n'ajouterait rien. En deçà du point de départ,
    on a reculé : l'avancement est nul, il n'est pas négatif — un anneau qui se remplirait
    à l'envers ne se lirait pas.
    """
    if baseline is None or current is None:
        return None

    span = target - baseline
    if span == 0:
        # La cible était déjà tenue le jour de l'adoption. L'objectif ne demandait rien à
        # parcourir ; le dire « à 0 % » serait faux dans l'autre sens.
        return 1.0

    return max(0.0, min(1.0, (current - baseline) / span))


# ── Mise en mots ──────────────────────────────────────


def fr(value: float) -> str:
    """Un nombre tel qu'il se lit en français, sans décimale inutile.

    Une décimale sous cent, aucune au-delà : « 2,4 séances » et « 78,5 kg » ont besoin de
    la leur, « 1 857,1 ml » n'a besoin de rien. La virgule est décimale — ces chaînes
    s'affichent telles quelles (`API-07`), elles ne sont pas un format d'échange.
    """
    rounded = round(value, 0 if abs(value) >= 100 else 1)
    text = f"{rounded:g}"
    return text.replace(".", ",")


def summary(current: float | None, target: float, unit: str) -> str:
    """Le libellé chiffré que `GOAL-04` demande : « 2,4 sur 3 séances ».

    Sans le nom de la métrique, et c'est une correction faite **en regardant la page** :
    l'écran l'affiche déjà au centre de l'anneau, et « 2,4 sur 3 séances · séances par
    semaine » écrivait « séances » trois fois en une ligne, qui passait alors sur deux.
    Un libellé chiffré dit le chiffre ; ce qu'on mesure se lit à côté.
    """
    head = "—" if current is None else fr(current)
    return f"{head} sur {fr(target)} {unit}".strip()


def basis(reduction: Reduction, granularity: str, as_of: date | None) -> str:
    """Ce sur quoi la valeur courante s'appuie, dit à l'écran.

    Même mot et même intention que le `basis` d'une proposition de planning : un chiffre
    dont on voit la fenêtre se discute, un chiffre nu se croit ou se rejette.
    """
    if reduction == "latest":
        return "dernier relevé" if as_of is None else f"relevé du {as_of:%d/%m/%Y}"
    if granularity == "week":
        return f"moyenne des {WEEK_WINDOW} dernières semaines complètes"
    return f"moyenne des {DAY_WINDOW} derniers jours révolus"


__all__ = [
    "DAY_WINDOW",
    "WEEK_WINDOW",
    "Reduction",
    "basis",
    "current_value",
    "fr",
    "latest",
    "rate",
    "ratio",
    "summary",
    "window",
]
