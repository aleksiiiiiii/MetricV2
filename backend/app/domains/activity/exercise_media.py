"""La démonstration d'un exercice, servie par l'instance Cadence de l'utilisateur (**C5**).

## Pourquoi ce module ne stocke rien

`exercise_catalog.py` fige 1324 exercices dans le dépôt, et laisse dehors, délibérément,
le champ qui nomme leur média : les images et les GIF appartiennent à **Gym visual** et ne
sont redistribuables que sous leurs conditions. Ce module ne rouvre pas cette décision — il
ne redistribue rien et n'écrit aucun identifiant dans le dépôt.

Il **demande** l'identifiant à l'instance de l'utilisateur, qui sert déjà ces médias à
Cadence, et rend une adresse. Le navigateur va la chercher là-bas : aucun octet de média ne
transite par Metric.

## Ce qu'une panne rend

`None`, toujours, et jamais une erreur. Trois façons de ne pas avoir d'image — pas
d'adresse de base réglée, instance injoignable, nom sans correspondance — et une seule
conséquence à l'écran. La spécification de Cadence dit déjà que la dernière est bénigne :
« un nom sans correspondance reste parfaitement valide, la séance se déroule, simplement
sans image ». Une feuille de charge qui afficherait « démonstration indisponible » à la
place ferait passer pour une panne ce qui est l'état normal d'un exercice écrit à la main.

## Le rapprochement est **exact**, comme partout ailleurs

`fold` et rien d'autre : minuscules, sans accents, sans ponctuation. Cadence, lui, tolère
les pluriels, les graphies collées et traduit le français mot à mot — le réimplémenter ici
en donnerait une seconde version, qui divergerait au premier cas limite et montrerait dans
Metric une démonstration que l'autre application ne montre pas. C'est la règle écrite dans
`exercise_catalog.py`, et elle vaut ici mot pour mot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import monotonic
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx2

from app.core.text import fold

logger = logging.getLogger(__name__)

#: Le chemin du catalogue, sous l'adresse de base. Celui que sert Cadence, et celui que
#: `scripts/build-exercise-catalog.mjs` documente.
CATALOG_PATH = "exercise-db/catalog.json"

#: Repli du préfixe des GIF quand le catalogue ne le déclare pas. Le fichier servi porte
#: `media.gif`, et c'est lui qui fait autorité : le codage en dur ne sert qu'à un
#: catalogue plus ancien, où le chemin était implicite.
DEFAULT_GIF_PREFIX = "exercise-db/gifs/"

#: Durée de vie du catalogue en mémoire. Six heures : il change quand l'instance est mise
#: à jour, c'est-à-dire quelques fois par an. Le relire à chaque ouverture de feuille
#: ferait payer 128 ko à un geste qui doit être instantané.
TTL_S = 6 * 3600

#: Bornes de l'appel. Court **exprès** : cette requête décore une feuille qui s'ouvre déjà
#: sans elle. Attendre dix secondes une image, c'est faire attendre la charge et la courbe,
#: qui sont, elles, ce qu'on venait lire.
TIMEOUT_S = 4.0


@dataclass(frozen=True)
class _Catalog:
    """Ce qu'on retient du catalogue distant : des noms repliés vers des identifiants."""

    ids: dict[str, str]
    gif_prefix: str
    fetched_at: float


#: Transport HTTP, `None` en production — `AsyncClient` prend alors le sien.
#:
#: La batterie y monte un faux catalogue en ASGI, comme `fake_openrouter.py` le fait pour
#: le modèle. Sans ce point d'injection, éprouver « l'instance ne répond pas » demanderait
#: de couper le réseau de la machine qui fait tourner les tests, et « le catalogue est
#: relu après six heures » ne serait pas éprouvable du tout.
transport: httpx2.AsyncBaseTransport | None = None

#: Le cache, une entrée par adresse de base. Un dictionnaire de module et non un
#: `lru_cache` : l'entrée doit pouvoir périmer sur le temps, ce qu'un cache par argument ne
#: sait pas faire, et l'adresse de base change quand on la corrige dans les réglages.
_CACHE: dict[str, _Catalog] = {}


def forget() -> None:
    """Vide le cache. Pour la batterie, et pour un futur bouton de réglages."""
    _CACHE.clear()


def _join(base: str, path: str) -> str:
    """`<base>/<path>`, en **conservant la query string** de la base.

    C'est tout l'intérêt : une instance privée sert sa clé d'accès dans l'adresse
    (`https://…/?key=…`), et sans elle chaque média répond `403`. Recoller les morceaux à
    la main — concaténer, puis rajouter un `?` — donnerait une chaîne qui ressemble à une
    URL sans en être une dès que la base porte déjà un paramètre.
    """
    parts = urlsplit(base.strip())
    root = parts.path if parts.path.endswith("/") else f"{parts.path}/"
    return urlunsplit((parts.scheme, parts.netloc, f"{root}{path}", parts.query, ""))


def _read(payload: Any) -> _Catalog:
    """Le JSON de Cadence → la table des identifiants.

    Les exercices sans champ média sont **ignorés** plutôt que rangés avec une valeur
    vide : une entrée qui existe et ne mène à rien ferait afficher une image morte, là où
    une entrée absente fait retomber proprement sur « pas de démonstration ».
    """
    # La forme est vérifiée avant d'être lue, et le refus passe par `ValueError` pour
    # rejoindre le chemin des pannes : un proxy qui sert sa page d'erreur avec un
    # `content-type` JSON rend une chaîne, et une chaîne n'a pas de `.get`. Trouvé par le
    # test, pas à la lecture — c'est exactement le cas qu'une instance derrière nginx
    # produit.
    if not isinstance(payload, dict):
        raise ValueError("le catalogue n'est pas un objet JSON")

    media = payload.get("media")
    entries = payload.get("exercises")
    ids = {
        fold(str(item["n"])): str(item["f"])
        for item in (entries if isinstance(entries, list) else [])
        if isinstance(item, dict) and item.get("n") and item.get("f")
    }
    return _Catalog(
        ids=ids,
        gif_prefix=str(
            (media.get("gif") if isinstance(media, dict) else None) or DEFAULT_GIF_PREFIX
        ),
        fetched_at=monotonic(),
    )


async def _catalog(base: str) -> _Catalog | None:
    """Le catalogue de l'instance, du cache ou du réseau. `None` si elle ne répond pas."""
    cached = _CACHE.get(base)
    if cached is not None and monotonic() - cached.fetched_at < TTL_S:
        return cached

    try:
        async with httpx2.AsyncClient(
            timeout=TIMEOUT_S, follow_redirects=True, transport=transport
        ) as client:
            response = await client.get(_join(base, CATALOG_PATH))
            response.raise_for_status()
            catalog = _read(response.json())
    except (httpx2.HTTPError, ValueError, KeyError, TypeError) as exc:
        # Journalisé et pas remonté : l'appelant décore une feuille, il n'a rien à dire de
        # cette panne. Le niveau est `info` — une instance éteinte est un état courant sur
        # une application personnelle, pas un incident à réveiller quelqu'un.
        logger.info("catalogue Cadence injoignable (%s) : %s", base, exc)
        return None

    _CACHE[base] = catalog
    return catalog


async def demo_url(base: str, name: str) -> str | None:
    """L'adresse du GIF de démonstration, ou `None`.

    L'adresse porte la clé d'accès de la base, puisqu'elle en hérite la query string : elle
    apparaît donc dans le `src` de l'image, comme elle apparaît déjà dans chaque lien de
    séance ouvert depuis Metric. C'est la même clé, et la même exposition — pas une
    nouvelle.
    """
    if not base.strip():
        return None

    catalog = await _catalog(base)
    if catalog is None:
        return None

    identifier = catalog.ids.get(fold(name))
    if identifier is None:
        return None

    return _join(base, f"{catalog.gif_prefix}{identifier}.gif")
