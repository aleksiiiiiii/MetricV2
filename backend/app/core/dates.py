"""Découpage du temps (`HEAT-32`, `ACT-11`).

Deux règles que tout le projet doit partager, et qui n'ont donc qu'une implémentation :

* **le jour suit le fuseau local**, jamais UTC. Une prise à 23 h 30 appartient au jour
  qu'affiche l'horloge, pas au lendemain ;
* **la semaine commence le lundi** — semaine ISO. Le backlog le dit pour l'activité
  (`ACT-11`) comme pour le planning (`PLAN-01`), et la spec d'assiduité en dépend
  (`HEAT-11`).

Les avoir dispersées serait le meilleur moyen d'obtenir deux totaux différents pour la
même journée selon l'écran qui la calcule.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings


def tz() -> ZoneInfo:
    return get_settings().tz


def now_local() -> datetime:
    """Instant courant, dans le fuseau de l'application."""
    return datetime.now(tz=tz())


def today_local() -> date:
    """Jour courant tel que l'affiche l'horloge de l'utilisateur."""
    return now_local().date()


def local_day_of(moment: datetime) -> date:
    """Jour auquel appartient un horodatage.

    Le cœur de `HEAT-32`. Un horodatage stocké avec son décalage est ramené au fuseau
    local avant d'en extraire la date : sans cela, une prise à 23 h 30 à Paris tomberait
    la veille en UTC, et le lendemain pour un décalage négatif.

    Un horodatage sans fuseau est supposé local — c'est le cas d'une valeur saisie à la
    main dans un tableur, et la supposer UTC décalerait silencieusement la journée.
    """
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone(tz()).date()


def local_moment(moment: datetime) -> datetime:
    """Le même instant, toujours situé dans un fuseau.

    Pendant de `local_day_of`, et **même convention** : un horodatage sans fuseau est
    supposé local. Elle est ici pour une raison plus étroite — comparer deux horodatages
    dont l'un serait naïf lève une `TypeError` en Python, ce qui suffirait à faire tomber
    une liste entière parce qu'une seule ligne a été retapée dans un tableur sans son
    décalage. C'est exactement le genre de panne que la famille *planning* du §2 de
    `docs/etat-du-projet.md` promet de ne pas avoir.
    """
    return moment.replace(tzinfo=tz()) if moment.tzinfo is None else moment


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Instants de début et de fin d'une journée locale, fin exclue."""
    zone = tz()
    start = datetime.combine(day, time.min, tzinfo=zone)
    return start, datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)


def week_start(day: date) -> date:
    """Lundi de la semaine ISO contenant `day`."""
    return day - timedelta(days=day.weekday())


def days_between(start: date, end: date) -> list[date]:
    """Tous les jours de `start` à `end`, bornes comprises.

    Rend la plage **complète** : les jours sans donnée sont présents et valent zéro.
    C'est la même exigence que `HEAT-24` — le client ne doit avoir aucun trou à combler.
    """
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
