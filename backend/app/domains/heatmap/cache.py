"""Cache des grilles d'assiduité (`HEAT-33`, décision **D8**).

## Ce qu'il économise, et ce qu'il n'économise pas

Mesuré sur un an de saisie réaliste — 98 ko, neuf pistes, 371 jours :

| | Sans cache de grilles | Avec |
|---|---|---|
| Requêtes WebDAV, cache fichier chaud | 0 | 0 |
| Temps CPU par affichage | ~50 ms | ~1 ms |

Le réseau était **déjà** réglé par le cache de `FileStore` (`STO-06`) : c'est lui qui
tient la promesse « ne pas relire Nextcloud à chaque affichage ». Ce qui restait est du
calcul refait pour rien — 70 % d'analyse CSV et de validation Pydantic, 6 000 lignes
revalidées par affichage parce que neuf pistes rouvrent les mêmes cinq fichiers, et 22 %
de moteur.

Un cache qui aurait visé le réseau aurait donc doublé un mécanisme existant sans rien
gagner. C'est la raison d'avoir mesuré avant d'écrire.

## Pourquoi l'empreinte, et pas une horloge

Un TTL suffirait si nous étions seuls à écrire. Nous ne le sommes pas : Nextcloud se
modifie depuis un téléphone, un client de synchro, un tableur (décision **D8**). Une
grille mémorisée n'est donc valable que tant que **tous les fichiers qui l'ont produite**
portent le même ETag qu'au moment du calcul.

L'empreinte n'est pas déclarée à la main : elle est relevée pendant le calcul par
`FileStore.observe`. Une liste écrite à la main aurait l'air juste et cesserait de l'être
au premier fichier lu en plus, sans que rien ne le signale — et le symptôme serait une
grille qui refuse de changer après une saisie.

Vérifier l'empreinte coûte une lecture par fichier, servie par le cache de `FileStore` :
gratuite pendant son TTL, un `304` ensuite. Le compromis est explicite — on paie la
fraîcheur en revalidations, jamais en recalculs.

## Ce qui n'est pas mémorisé

Une empreinte contenant un fichier servi **sans ETag** est refusée : nous ne saurions pas
l'invalider, et une grille qu'on ne peut pas invalider vaut moins que pas de cache du
tout.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from app.domains.heatmap.engine import Grid
from app.storage.files import UNVERSIONED

#: Grilles gardées en mémoire. Neuf pistes × quelques plages consultées, plus la marge
#: des tiroirs de détail — chacun évalue un jour, donc une entrée de plus par cellule
#: ouverte. Deux cents entrées tiennent largement une session, et la plus ancienne part
#: en premier.
MAX_ENTRIES = 200


@dataclass(frozen=True, slots=True)
class GridKey:
    """Ce qui identifie une grille indépendamment des données qui la remplissent.

    `today` en fait partie : la même piste sur la même plage ne rend pas la même grille
    hier et aujourd'hui — la journée en cours n'est jamais manquée (`HEAT-08`), et à
    minuit celle d'hier le devient. Sans cette borne, une session ouverte la nuit
    afficherait le lendemain une grille d'hier.
    """

    track_id: str
    start: date
    end: date
    today: date


@dataclass(frozen=True, slots=True)
class CachedGrid:
    grid: Grid
    #: `chemin → ETag` des fichiers lus pour produire cette grille.
    fingerprint: Mapping[str, str]


@dataclass(slots=True)
class GridCache:
    """Grilles mémorisées, invalidées par la version de leurs sources."""

    max_entries: int = MAX_ENTRIES
    _entries: OrderedDict[GridKey, CachedGrid] = field(default_factory=OrderedDict)
    hits: int = 0
    misses: int = 0

    def get(self, key: GridKey) -> CachedGrid | None:
        """Entrée mémorisée, **sans** garantie de fraîcheur.

        C'est à l'appelant de confronter l'empreinte au stockage : lui seul sait lire, et
        ce module reste ainsi vérifiable sans monter de dépôt.
        """
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._entries.move_to_end(key)
        return entry

    def store(self, key: GridKey, grid: Grid, fingerprint: Mapping[str, str]) -> None:
        """Mémorise une grille, sauf si son empreinte ne prouve rien.

        Une empreinte vide — aucun fichier lu — ou contenant un fichier sans ETag ne
        permettrait pas de détecter un changement. On préfère recalculer.
        """
        if not fingerprint or UNVERSIONED in fingerprint.values():
            return

        self._entries[key] = CachedGrid(grid=grid, fingerprint=dict(fingerprint))
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def record(self, *, hit: bool) -> None:
        """Compte les succès et les échecs, pour que le test de performance mesure au
        lieu de supposer."""
        if hit:
            self.hits += 1
        else:
            self.misses += 1

    def clear(self) -> None:
        self._entries.clear()
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._entries)
