"""Dépôt CSV typé (`STO-02` → `STO-05`).

Un fichier, un en-tête explicite, un modèle. Le dépôt sait lire, ajouter, modifier et
supprimer une ligne, en absorbant trois problèmes que le domaine ne doit pas connaître :

* **Migration d'en-tête** (`STO-04`) — les anciennes lignes sont remappées par nom de
  colonne, les colonnes nouvelles restent vides. Aucune migration manuelle.
* **Garde anti-conflit** (`STO-05`) — une modification annonce les valeurs qu'elle
  s'attend à trouver ; si elles ont changé, on refuse en `409` plutôt que d'écraser la
  mauvaise ligne. Doublée d'un `If-Match` sur l'ETag du fichier, qui détecte aussi les
  ajouts concurrents ayant décalé les index.
* **Ajout en fin de fichier** (`STO-03`) — voir la note sur le mécanisme, plus bas.

## Note sur « écriture en ajout »

WebDAV n'a pas de verbe d'ajout, et l'extension de mise à jour partielle de Sabre n'est
pas activée sur une Nextcloud standard. Le mécanisme est donc un `PUT` complet du
fichier. L'**invariant** de `STO-03` est néanmoins tenu : on n'ajoute qu'en fin de
fichier, on ne réécrit jamais une ligne existante lors d'un ajout. Et la propriété
recherchée — « plus sûr en cas d'interruption » — est assurée par le serveur : Sabre
écrit dans un fichier temporaire puis le renomme, si bien qu'un téléversement interrompu
laisse la version précédente intacte plutôt qu'un fichier tronqué.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from app.storage.errors import StorageConflictError, StorageSchemaError
from app.storage.files import FileState, FileStore
from app.storage.model import CsvModel

# Les ajouts commutent : deux appareils qui enregistrent une prise en même temps ne
# doivent pas s'envoyer un conflit à la figure. On relit et on rejoue.
APPEND_RETRIES = 3


@dataclass(frozen=True, slots=True)
class Row[TModel: CsvModel]:
    """Ligne lue : sa position, son modèle, et ses cellules brutes.

    `raw` sert à deux choses : construire la garde anti-conflit d'une modification
    ultérieure, et conserver les colonnes que l'app ne connaît pas.
    """

    index: int
    model: TModel
    raw: Mapping[str, str]

    @property
    def token(self) -> str:
        """Empreinte du contenu de la ligne, pour la garde anti-conflit (`STO-05`).

        L'API l'expose et l'exige en retour dans `If-Match` : c'est la façon HTTP de
        dire « je modifie la ligne telle que je l'ai lue ». Plus simple à transporter
        qu'un dictionnaire de valeurs attendues — en particulier sur un `DELETE`, qui
        n'a pas de corps de requête naturel.
        """
        material = "\x1f".join(f"{key}={self.raw.get(key, '')}" for key in sorted(self.raw))
        return hashlib.sha256(material.encode()).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class Sheet[TModel: CsvModel]:
    """État complet d'un fichier à un instant donné."""

    rows: list[Row[TModel]]
    etag: str | None
    exists: bool
    extra_columns: tuple[str, ...]

    @property
    def token(self) -> str:
        """Empreinte de l'état complet du fichier.

        Le pendant de `Row.token` à l'échelle du fichier, pour ce qui s'édite en bloc
        plutôt que ligne par ligne — les réglages, par exemple, où un formulaire écrit
        cinq clés d'un coup. La garde de `STO-05` reste la même règle : on annonce
        l'état qu'on croyait trouver, et une divergence est un `409`.

        Un fichier absent et un fichier vide rendent la même empreinte : dans les deux
        cas il n'y a rien à écraser.
        """
        material = "\x1f".join(row.token for row in self.rows)
        return hashlib.sha256(material.encode()).hexdigest()[:12]


class CsvRepository[TModel: CsvModel]:
    """Accès typé à un fichier CSV du stockage."""

    def __init__(self, store: FileStore, path: str, model: type[TModel]) -> None:
        self._store = store
        self._path = path
        self._model = model
        self._columns = model.csv_columns()

    @property
    def path(self) -> str:
        return self._path

    @property
    def columns(self) -> tuple[str, ...]:
        return self._columns

    # ── Lecture ───────────────────────────────────────

    async def load(self, *, fresh: bool = False) -> Sheet[TModel]:
        """Lit le fichier entier et le valide."""
        state = await self._store.read(self._path, fresh=fresh)
        raws, extra = self._parse(state.content)

        rows: list[Row[TModel]] = []
        for index, raw in enumerate(raws):
            rows.append(Row(index=index, model=self._validate(raw, index), raw=raw))

        return Sheet(rows=rows, etag=state.etag, exists=state.exists, extra_columns=extra)

    async def read_all(self, *, fresh: bool = False) -> list[Row[TModel]]:
        return (await self.load(fresh=fresh)).rows

    # ── Écriture ──────────────────────────────────────

    async def append(self, item: TModel) -> Row[TModel]:
        """Ajoute une ligne en fin de fichier.

        Rejoue automatiquement en cas d'écriture concurrente : l'ordre de deux ajouts
        simultanés n'a pas d'importance, alors qu'un `409` obligerait l'utilisateur à
        ressaisir.
        """
        last: StorageConflictError | None = None

        for _ in range(APPEND_RETRIES):
            sheet = await self.load(fresh=True)
            raws = [dict(row.raw) for row in sheet.rows]
            raws.append(item.to_csv())
            try:
                await self._save(raws, sheet)
            except StorageConflictError as exc:
                last = exc
                continue
            return Row(index=len(raws) - 1, model=item, raw=item.to_csv())

        raise last or StorageConflictError()

    async def replace(
        self,
        index: int,
        expected: Mapping[str, str] | CsvModel,
        item: TModel,
    ) -> Row[TModel]:
        """Remplace une ligne, sous garde anti-conflit (`STO-05`)."""
        sheet = await self.load(fresh=True)
        self._guard(sheet, index, expected)

        raws = [dict(row.raw) for row in sheet.rows]
        # Les colonnes inconnues de l'app présentes sur cette ligne sont conservées.
        raws[index] = {**raws[index], **item.to_csv()}
        await self._save(raws, sheet)

        return Row(index=index, model=item, raw=raws[index])

    async def replace_by_token(self, index: int, token: str, item: TModel) -> Row[TModel]:
        """Remplace une ligne identifiée par sa position et garantie par son jeton.

        Une seule lecture fraîche au lieu de deux : le jeton **est** la garde, il n'y a
        pas à comparer les valeurs une seconde fois.
        """
        sheet = await self.load(fresh=True)
        self._guard_token(sheet, index, token)

        raws = [dict(row.raw) for row in sheet.rows]
        raws[index] = {**raws[index], **item.to_csv()}
        await self._save(raws, sheet)

        return Row(index=index, model=item, raw=raws[index])

    async def delete_by_token(self, index: int, token: str) -> None:
        """Supprime une ligne identifiée par sa position et garantie par son jeton."""
        sheet = await self.load(fresh=True)
        self._guard_token(sheet, index, token)

        raws = [dict(row.raw) for i, row in enumerate(sheet.rows) if i != index]
        await self._save(raws, sheet)

    def _guard_token(self, sheet: Sheet[TModel], index: int, token: str) -> None:
        if not 0 <= index < len(sheet.rows):
            raise StorageConflictError(
                detail=f"{self._path} : ligne {index} absente ({len(sheet.rows)} lignes)"
            )
        current = sheet.rows[index]
        if current.token != token:
            raise StorageConflictError(
                detail=(
                    f"{self._path}, ligne {index + 2} : jeton « {token} » périmé, "
                    f"la ligne vaut désormais « {current.token} »"
                )
            )

    async def delete(self, index: int, expected: Mapping[str, str] | CsvModel) -> None:
        """Supprime une ligne, sous garde anti-conflit (`STO-05`)."""
        sheet = await self.load(fresh=True)
        self._guard(sheet, index, expected)

        raws = [dict(row.raw) for i, row in enumerate(sheet.rows) if i != index]
        await self._save(raws, sheet)

    async def remove_where(self, matches: Callable[[TModel], bool]) -> int:
        """Supprime toutes les lignes qui satisfont un critère, en une écriture.

        Nécessaire aux suppressions en cascade — purger les exercices d'une séance
        supprimée (`ACT-04`). Les faire une par une multiplierait les allers-retours et
        laisserait le fichier dans un état intermédiaire en cas de coupure.

        Sans garde par jeton : la ligne visée n'est pas désignée par l'utilisateur mais
        déduite d'une suppression qu'il a déjà confirmée.
        """
        sheet = await self.load(fresh=True)
        kept = [dict(row.raw) for row in sheet.rows if not matches(row.model)]

        removed = len(sheet.rows) - len(kept)
        if removed:
            await self._save(kept, sheet)
        return removed

    async def overwrite(self, items: Sequence[TModel], *, token: str | None = None) -> None:
        """Réécrit le fichier entier.

        Réservé à l'amorçage et aux fichiers de configuration, jamais utilisé pour une
        saisie utilisateur ligne à ligne — qui passe toujours par `append`.

        `token` porte la garde anti-conflit du fichier entier (`Sheet.token`) : la même
        lecture fraîche sert à vérifier et à écrire, si bien qu'aucune écriture
        concurrente ne peut se glisser entre les deux.
        """
        sheet = await self.load(fresh=True)
        if token is not None and sheet.token != token:
            raise StorageConflictError(
                detail=(
                    f"{self._path} : jeton « {token} » périmé, "
                    f"le fichier vaut désormais « {sheet.token} »"
                )
            )
        await self._save([item.to_csv() for item in items], sheet)

    # ── Interne ───────────────────────────────────────

    def _validate(self, raw: Mapping[str, str], index: int) -> TModel:
        try:
            return self._model.from_csv(raw)
        except ValidationError as exc:
            # Ligne 1 = en-tête : la ligne de données 0 est la ligne 2 du fichier.
            first = exc.errors()[0]
            column = ".".join(str(part) for part in first["loc"]) or "?"
            raise StorageSchemaError(
                detail=(f"{self._path}, ligne {index + 2}, colonne « {column} » : {first['msg']}")
            ) from exc

    def _guard(
        self,
        sheet: Sheet[TModel],
        index: int,
        expected: Mapping[str, str] | CsvModel,
    ) -> None:
        """Refuse l'écriture si la ligne visée n'est plus celle qu'on croyait."""
        if not 0 <= index < len(sheet.rows):
            raise StorageConflictError(
                detail=f"{self._path} : ligne {index} absente ({len(sheet.rows)} lignes)"
            )

        wanted = expected.to_csv() if isinstance(expected, CsvModel) else dict(expected)
        current = sheet.rows[index].raw

        for column, value in wanted.items():
            if current.get(column, "") != value:
                raise StorageConflictError(
                    detail=(
                        f"{self._path}, ligne {index + 2}, colonne « {column} » : "
                        f"attendu « {value} », trouvé « {current.get(column, '')} »"
                    )
                )

    async def _save(self, raws: Sequence[Mapping[str, str]], sheet: Sheet[TModel]) -> None:
        """Écrit le fichier en exigeant qu'il n'ait pas changé depuis la lecture."""
        content = self._render(raws, sheet.extra_columns)

        if sheet.exists:
            # `if_match=None` si le serveur n'annonce pas d'ETag : la garde par valeurs
            # attendues reste active, seule la détection des ajouts concurrents tombe.
            await self._store.write(self._path, content, if_match=sheet.etag)
        else:
            # Le fichier n'existait pas : refuser de l'écraser s'il vient d'apparaître.
            await self._store.write(self._path, content, if_none_match="*")

    def _parse(self, content: bytes) -> tuple[list[dict[str, str]], tuple[str, ...]]:
        """Découpe un CSV en lignes normalisées, et repère les colonnes étrangères."""
        text = content.decode("utf-8-sig", errors="strict") if content else ""
        if not text.strip():
            return [], ()

        reader = csv.reader(io.StringIO(text, newline=""))
        try:
            header = next(reader)
        except StopIteration:  # pragma: no cover - couvert par le test de fichier vide
            return [], ()

        header = [name.strip() for name in header]
        # Colonnes présentes dans le fichier que le modèle ne connaît pas : ajoutées à
        # la main dans un tableur, par exemple. On ne les détruit pas (`STO-02`).
        extra = tuple(name for name in header if name and name not in self._columns)

        rows: list[dict[str, str]] = []
        for values in reader:
            if not any(value.strip() for value in values):
                continue  # ligne vide en fin de fichier
            present = dict(zip(header, values, strict=False))
            rows.append({column: present.get(column, "") for column in (*self._columns, *extra)})
        return rows, extra

    def _render(self, raws: Sequence[Mapping[str, str]], extra: Sequence[str]) -> bytes:
        """Sérialise les lignes, en-tête explicite d'abord.

        Encodage UTF-8 **avec BOM** : sans lui, un double-clic sur le fichier dans Excel
        sous Windows massacre les accents. C'est le prix d'une des promesses du projet —
        des données exploitables dans un tableur même si l'app disparaît (`STO-02`).
        """
        header = [*self._columns, *extra]
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(
            buffer, fieldnames=header, lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        for raw in raws:
            writer.writerow({column: raw.get(column, "") for column in header})
        return buffer.getvalue().encode("utf-8-sig")


__all__ = ["CsvRepository", "FileState", "Row", "Sheet"]
