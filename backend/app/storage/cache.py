"""Cache mémoire des lectures (`STO-06`, décision **D8**).

Un tableau de bord tire une dizaine de fichiers (`AGG-01`), une page d'assiduité en
tire autant sur 371 jours (`HEAT-33`). Sans cache, chaque affichage martèle Nextcloud.

Le point délicat : **Nextcloud est modifiable derrière notre dos** — autre appareil,
client de synchro, édition dans un tableur. Invalider seulement sur nos propres
écritures laisserait servir des données périmées. D'où deux mécanismes complémentaires :

* un TTL court, pendant lequel on sert sans rien demander ;
* passé le TTL, une **revalidation conditionnelle** par ETag : un 304 coûte un
  aller-retour sans corps et prolonge l'entrée.

La fenêtre d'incohérence maximale est donc le TTL, et c'est assumé.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

# « Quelques dizaines de secondes » (`STO-06`).
DEFAULT_TTL = 30.0


@dataclass(frozen=True, slots=True)
class CacheEntry:
    content: bytes
    etag: str | None
    stored_at: float
    #: Faux quand le serveur a répondu que le fichier n'existe pas.
    #:
    #: **L'absence se mémorise comme le contenu.** Sur une installation neuve aucun
    #: fichier n'existe, et le tableau de bord (`AGG-01`) demande neuf sources dont
    #: plusieurs deux fois : sans cette mémoire, chaque domaine irait redemander un 404
    #: que le précédent venait déjà d'obtenir. La fenêtre d'incohérence reste le TTL,
    #: comme pour un contenu — un fichier déposé depuis un autre appareil apparaît au
    #: plus tard trente secondes après.
    exists: bool = True


@dataclass(slots=True)
class FileCache:
    """Cache par chemin, borné dans le temps."""

    ttl: float = DEFAULT_TTL
    clock: Callable[[], float] = time.monotonic
    _entries: dict[str, CacheEntry] = field(default_factory=dict)

    def get(self, path: str) -> CacheEntry | None:
        """Entrée mémorisée, fraîche ou non. À l'appelant de vérifier `is_fresh`."""
        return self._entries.get(path)

    def is_fresh(self, entry: CacheEntry) -> bool:
        return (self.clock() - entry.stored_at) < self.ttl

    def store(
        self, path: str, content: bytes, etag: str | None, *, exists: bool = True
    ) -> CacheEntry:
        entry = CacheEntry(content=content, etag=etag, stored_at=self.clock(), exists=exists)
        self._entries[path] = entry
        return entry

    def store_absence(self, path: str) -> CacheEntry:
        """Mémorise qu'un fichier n'existe pas."""
        return self.store(path, b"", None, exists=False)

    def touch(self, path: str) -> CacheEntry | None:
        """Prolonge une entrée que le serveur vient de confirmer inchangée (304)."""
        entry = self._entries.get(path)
        if entry is None:
            return None
        refreshed = replace(entry, stored_at=self.clock())
        self._entries[path] = refreshed
        return refreshed

    def invalidate(self, path: str) -> None:
        self._entries.pop(path, None)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
