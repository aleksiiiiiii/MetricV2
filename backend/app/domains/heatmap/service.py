"""Cycle de vie des pistes d'assiduité (`HEAT-01`, `HEAT-06`, `HEAT-14`, `HEAT-18` → `HEAT-23`).

Ce module gère **ce qu'on attend**, pas ce qui s'est passé : créer une piste, changer sa
cadence, neutraliser une semaine de grippe. Le calcul des états — `off`, `missed`, `done`,
`bonus` — est le lot suivant. La séparation est volontaire : la configuration a son propre
cycle de vie, ses propres gardes, et se teste sans moteur.

## Deux asymétries assumées

**Une cadence est un engagement daté ; un seuil est une définition.** Changer la cadence
n'affecte que l'avenir (`HEAT-14`) : passer la whey d'un jour sur deux à un jour sur trois
aujourd'hui ne doit pas réécrire le verdict des mois passés. Changer un seuil de
validation, au contraire, rejuge tout l'historique (`HEAT-20`) — parce qu'un seuil dit ce
que « validé » signifie, et cette signification n'a pas de version. L'asymétrie doit être
**annoncée**, pas subie : `TrackSaved` la porte.

**Une piste de supplément a deux sources de cadence** (décision **D3**).
`supplements/schedule.csv` porte la valeur courante — c'est là que l'utilisateur écrit
« whey un jour sur deux », et il n'y a pas deux endroits pour le dire. Le journal
`heatmap_cadences.csv` porte l'historique. La réconciliation est faite ici, à la lecture :
voir `_sync_supplement_cadences`.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from datetime import date, timedelta

from app.core.cadence import Cadence, CadenceError
from app.core.dates import today_local
from app.domains.activity.service import ExerciseService, RunService
from app.domains.app_settings.service import SettingsService
from app.domains.heatmap.models import CadenceRow, OffDayRow, TrackRow
from app.domains.heatmap.schemas import (
    ACCENTS,
    CadenceView,
    OffDay,
    OffDayPayload,
    SourceDescriptor,
    Track,
    TrackPayload,
    TrackSaved,
    TracksView,
    TrackUpdate,
)
from app.domains.heatmap.sources import SEPARATOR, SOURCES
from app.domains.supplements.service import SupplementService
from app.storage.csv_repo import CsvRepository, Row
from app.storage.errors import StorageNotFoundError
from app.storage.files import FileStore
from app.storage.paths import HEATMAP_CADENCES, HEATMAP_OFF_DAYS, HEATMAP_TRACKS

#: Fenêtre d'observation servant à amorcer les cadences hebdomadaires (décision **D9**).
SEED_WEEKS = 4

#: Seuils d'intensité des pistes musculaires et de la course, en séries et en kilomètres.
#: Quatre bornes croissantes : le niveau est le nombre de bornes atteintes.
DEFAULT_LEVELS = (1.0, 3.0, 6.0, 10.0)

#: Piste eau. La validation passe de 1000 à **1500 ml** (décision **D10**) : à un litre,
#: le vert validait des journées à la moitié de l'objectif et ne voulait plus rien dire.
#: Le gradient, lui, est inchangé — il court toujours jusqu'à 2500 ml (`HEAT-17`).
WATER_VALIDATION = 1500.0
WATER_LEVELS = (1000.0, 1500.0, 2000.0, 2500.0)

#: Regroupement des neuf groupes musculaires de `ACT-06` en cinq pistes.
#:
#: Ce n'est **pas** une constante du moteur : c'est la valeur d'amorçage de la colonne
#: `filter`, que l'utilisateur peut redécouper sans toucher aux données. `autre` reste
#: délibérément non mappé (décision **D7**) — il ne doit polluer aucune piste.
MUSCLE_TRACKS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("torse", "Torse", ("pectoraux", "épaules")),
    ("dos", "Dos", ("dos",)),
    ("bras", "Bras", ("biceps", "triceps")),
    ("jambes", "Jambes", ("jambes", "fessiers")),
    ("abdos", "Abdos", ("abdos",)),
)


def _new_id() -> str:
    return secrets.token_hex(6)


def _levels_to_text(levels: list[float] | tuple[float, ...]) -> str:
    return SEPARATOR.join(f"{value:g}" for value in levels)


def _levels_from_text(raw: str) -> list[float]:
    """Lit les bornes d'intensité, en ignorant ce qui n'est pas un nombre.

    Comme partout dans les fichiers de configuration : une cellule abîmée à la main coûte
    son propre repli, pas l'écran entier.
    """
    values: list[float] = []
    for chunk in raw.split(SEPARATOR):
        try:
            values.append(float(chunk.strip().replace(",", ".")))
        except ValueError:
            continue
    return values


class TrackService:
    """Pistes, cadences versionnées et plages neutralisées."""

    def __init__(self, store: FileStore) -> None:
        self._store = store
        self._tracks: CsvRepository[TrackRow] = CsvRepository(store, HEATMAP_TRACKS, TrackRow)
        self._cadences: CsvRepository[CadenceRow] = CsvRepository(
            store, HEATMAP_CADENCES, CadenceRow
        )
        self._off: CsvRepository[OffDayRow] = CsvRepository(store, HEATMAP_OFF_DAYS, OffDayRow)
        self._settings = SettingsService(store)

    # ── Lecture ───────────────────────────────────────

    async def view(self) -> TracksView:
        """Tout l'écran de configuration en une requête."""
        return TracksView(
            tracks=await self.all(include_inactive=True),
            sources=[
                SourceDescriptor(
                    key=source.key,
                    label=source.label,
                    unit=source.unit,
                    filter_label=source.filter_label,
                )
                for source in SOURCES.values()
            ],
            off_days=await self.off_days(),
            highlight=(await self._settings.values()).heatmap_metric,
        )

    async def all(self, *, include_inactive: bool = False) -> list[Track]:
        rows = await self._tracks.read_all()
        if not rows:
            return []

        await self._sync_supplement_cadences(rows)

        history = await self._history()
        current = await self._supplement_frequencies()

        tracks = [self._to_schema(row, history, current) for row in rows]
        if not include_inactive:
            tracks = [track for track in tracks if track.active]
        return sorted(tracks, key=lambda track: (track.position, track.label))

    async def resolve(self, track_id: str) -> Row[TrackRow]:
        """Ligne d'une piste depuis son identifiant stable.

        L'API désigne une piste par son `track_id` — un identifiant que l'utilisateur
        voit et qui survit à un tri. La garde anti-conflit, elle, travaille sur la
        position dans le fichier : les deux notions cohabitent, et seule la première est
        publique.
        """
        for row in await self._tracks.read_all():
            if row.model.id == track_id:
                return row
        raise StorageNotFoundError("Cette piste n'existe pas.")

    async def cadence_at(self, track_id: str, day: date) -> Cadence:
        """Cadence applicable à une date donnée (`HEAT-14`).

        La ligne retenue est celle dont `valid_from` est la plus récente **antérieure ou
        égale** au jour jugé. Avant la première prise d'effet, on retient la plus ancienne
        connue : une piste amorcée hier avec une cadence n'a pas à rendre le mois dernier
        illisible faute de règle.
        """
        entries = _chronological(
            row.model for row in await self._cadences.read_all() if row.model.track_id == track_id
        )
        if not entries:
            return Cadence.parse("daily")

        applicable = [entry for entry in entries if (entry.valid_from or date.min) <= day]
        chosen = applicable[-1] if applicable else entries[0]
        return self._read_cadence(chosen)

    # ── Écriture (`HEAT-18` → `HEAT-21`) ──────────────

    async def create(self, payload: TrackPayload) -> Track:
        track_id = _new_id()
        rows = await self._tracks.read_all()

        await self._tracks.append(
            TrackRow(
                id=track_id,
                label=payload.label,
                source=payload.source,
                filter=payload.filter,
                validation_threshold=payload.validation_threshold,
                levels=_levels_to_text(payload.levels),
                binary=payload.binary,
                accent=payload.accent,
                # Ajoutée en dernier : l'ordre est un réglage, pas une surprise.
                position=max((row.model.position for row in rows), default=-1) + 1,
                active=payload.active,
                # Immuable, et c'est ce qui rend `HEAT-07` vrai : la piste ne produira
                # aucun état avant ce jour.
                created=today_local(),
            )
        )
        await self._record_cadence(track_id, Cadence.parse(payload.cadence), today_local())
        return await self.get(track_id)

    async def get(self, track_id: str) -> Track:
        row = await self.resolve(track_id)
        return self._to_schema(row, await self._history(), await self._supplement_frequencies())

    async def update(self, track_id: str, token: str, payload: TrackUpdate) -> TrackSaved:
        row = await self.resolve(track_id)
        before = row.model
        cadence = Cadence.parse(payload.cadence)

        # Ce qui redéfinit « validé » rejuge tout le passé ; ce qui décrit un engagement
        # ne vaut que pour l'avenir. La différence est annoncée, pas subie (`HEAT-20`).
        levels = _levels_to_text(payload.levels)
        retroactive = (
            payload.validation_threshold != before.validation_threshold
            or levels != before.levels
            or payload.binary != before.binary
        )

        await self._tracks.replace_by_token(
            row.index,
            token,
            TrackRow(
                id=before.id,
                label=payload.label,
                source=payload.source,
                filter=payload.filter,
                validation_threshold=payload.validation_threshold,
                levels=levels,
                binary=payload.binary,
                accent=payload.accent,
                # Position et date de création survivent : l'une est réglée ailleurs
                # (`HEAT-22`), l'autre est immuable (`HEAT-07`).
                position=before.position,
                active=payload.active,
                created=before.created,
            ),
        )

        changed_cadence = await self._record_cadence(track_id, cadence, today_local())

        warnings: list[str] = []
        if retroactive:
            warnings.append(
                "Les seuils ont changé : tout l'historique de cette piste est rejugé, "
                "y compris les journées déjà passées."
            )
        if changed_cadence:
            warnings.append(
                f"Nouvelle cadence « {cadence.describe()} », effective à partir "
                f"d'aujourd'hui. Les journées antérieures gardent la règle qui "
                f"s'appliquait alors."
            )

        return TrackSaved(
            track=await self.get(track_id),
            recalculated_history=retroactive,
            warnings=warnings,
        )

    async def delete(self, track_id: str, token: str) -> None:
        """Supprime une piste et son historique de cadences.

        **Aucune donnée source n'est touchée** (`HEAT-21`) : les séries, les kilomètres et
        les prises restent dans les fichiers des domaines de saisie. Une piste n'est
        qu'une lecture posée par-dessus, et la défaire ne défait pas ce qui a été fait.

        Pour conserver la grille sans l'afficher, la voie normale est la désactivation.
        """
        row = await self.resolve(track_id)
        await self._tracks.delete_by_token(row.index, token)
        await self._cadences.remove_where(lambda model: model.track_id == track_id)
        await self._off.remove_where(lambda model: model.track_id == track_id)

    async def reorder(self, track_ids: list[str]) -> list[Track]:
        """Applique un nouvel ordre d'affichage (`HEAT-22`).

        Les pistes absentes de la liste gardent leur rang, à la suite : un client qui
        n'enverrait que les trois premières ne doit pas faire disparaître les six autres.
        """
        rows = await self._tracks.read_all(fresh=True)
        ranks = {track_id: index for index, track_id in enumerate(track_ids)}
        tail = len(ranks)

        ordered: list[TrackRow] = []
        for row in rows:
            model = row.model
            ordered.append(
                model.model_copy(update={"position": ranks.get(model.id, tail + row.index)})
            )

        await self._tracks.overwrite(ordered)
        return await self.all(include_inactive=True)

    async def highlight(self, track_id: str) -> str:
        """Met une piste en avant (`HEAT-22`). C'est le réglage `heatmap_metric`."""
        await self.resolve(track_id)
        view = await self._settings.view()
        from app.domains.app_settings.schemas import SettingsPayload

        await self._settings.update(SettingsPayload(heatmap_metric=track_id), view.token)
        return track_id

    # ── Jours neutralisés (`HEAT-06`) ─────────────────

    async def off_days(self) -> list[OffDay]:
        rows = await self._off.read_all()
        return sorted(
            (self._off_to_schema(row) for row in rows if row.model.date_from and row.model.date_to),
            key=lambda item: item.date_from,
            reverse=True,
        )

    async def add_off_days(self, payload: OffDayPayload) -> OffDay:
        if payload.track_id:
            await self.resolve(payload.track_id)

        row = await self._off.append(
            OffDayRow(
                id=_new_id(),
                track_id=payload.track_id,
                date_from=payload.date_from,
                date_to=payload.date_to,
                reason=payload.reason,
            )
        )
        return self._off_to_schema(row)

    async def remove_off_days(self, off_id: str, token: str) -> None:
        for row in await self._off.read_all():
            if row.model.id == off_id:
                await self._off.delete_by_token(row.index, token)
                return
        raise StorageNotFoundError("Cette neutralisation n'existe pas.")

    async def neutralised(self, track_id: str) -> list[OffDayRow]:
        """Plages neutralisant une piste, la neutralisation globale comprise.

        Un `track_id` vide neutralise **toutes** les pistes : c'est le cas d'une semaine
        d'arrêt, qu'on ne veut pas avoir à déclarer neuf fois.
        """
        rows = await self._off.read_all()
        return [row.model for row in rows if row.model.track_id in ("", track_id)]

    # ── Amorçage (`heat_backlog` §5) ──────────────────

    async def ensure_seeded(self) -> list[Track]:
        """Crée les pistes par défaut si le fichier est vide.

        Amorcer n'est pas figer : chaque piste posée ici est ensuite modifiable et
        supprimable. Ce qui compte est qu'un utilisateur qui ouvre l'écran pour la
        première fois voie neuf grilles peuplées de son propre historique, et non un
        formulaire de création vide.

        L'appel est **idempotent** : un fichier non vide est laissé tel quel, y compris
        s'il ne contient qu'une piste que l'utilisateur a gardée après en avoir supprimé
        huit.
        """
        if await self._tracks.read_all():
            return await self.all(include_inactive=True)

        today = today_local()
        rows: list[TrackRow] = []
        cadences: list[CadenceRow] = []
        position = 0

        def add(row: TrackRow, cadence: Cadence) -> None:
            nonlocal position
            row.position = position
            row.created = today
            rows.append(row)
            cadences.append(
                CadenceRow(
                    id=_new_id(),
                    track_id=row.id,
                    type=str(cadence.type),
                    params=_params_text(cadence),
                    valid_from=today,
                )
            )
            position += 1

        # Fréquences réelles des quatre dernières semaines (décision **D9**) : amorcer à
        # « 2 fois par semaine » pour cinq groupes supposerait dix créneaux hebdomadaires,
        # ce qui est beaucoup quand on court aussi. Une piste doit décrire un engagement
        # tenable, sinon la grille est rouge dès le premier jour et on cesse de la lire.
        horizon = today - timedelta(days=SEED_WEEKS * 7 - 1)
        by_group: dict[str, set[date]] = {}
        for entry in await ExerciseService(self._store).log_entries():
            if entry.model.date >= horizon:
                by_group.setdefault(entry.model.muscle_group, set()).add(entry.model.date)

        for track_id, label, groups in MUSCLE_TRACKS:
            days = {day for group in groups for day in by_group.get(group, set())}
            add(
                TrackRow(
                    id=track_id,
                    label=label,
                    source="activity.muscle_group",
                    filter=SEPARATOR.join(groups),
                    validation_threshold=1,
                    levels=_levels_to_text(DEFAULT_LEVELS),
                    accent="effort",
                ),
                Cadence.parse(f"per_week:count={_weekly_frequency(days)}"),
            )

        run_days = {
            row.model.date
            for row in await RunService(self._store).all()
            if row.model.date >= horizon
        }
        add(
            TrackRow(
                id="course",
                label="Course",
                source="activity.runs",
                validation_threshold=1,
                levels=_levels_to_text(DEFAULT_LEVELS),
                accent="signal",
            ),
            Cadence.parse(f"per_week:count={_weekly_frequency(run_days)}"),
        )

        add(
            TrackRow(
                id="eau",
                label="Eau",
                source="hydration.intake",
                validation_threshold=WATER_VALIDATION,
                levels=_levels_to_text(WATER_LEVELS),
                accent="signal",
            ),
            Cadence.parse("daily"),
        )

        # Une piste par supplément actif, avec **sa** cadence (`HEAT-18`, `HEAT-23`). La
        # spec cite « créatine » et « whey » en exemple ; les coder en dur donnerait deux
        # grilles vides à qui prend autre chose.
        for supplement in await SupplementService(self._store).schedule(active_only=True):
            add(
                TrackRow(
                    id=f"sup-{supplement.schedule_id}",
                    label=supplement.name,
                    source="supplement.intake",
                    filter=supplement.schedule_id,
                    validation_threshold=1,
                    # Binaire par défaut (décision **D11**) : une prise est une prise.
                    # Le mode gradué est supporté, il suffit de renseigner deux seuils.
                    binary=True,
                    accent="recover",
                ),
                Cadence.parse(supplement.frequency),
            )

        await self._tracks.overwrite(rows)
        await self._cadences.overwrite(cadences)
        return await self.all(include_inactive=True)

    # ── Interne ───────────────────────────────────────

    async def _history(self) -> dict[str, list[CadenceRow]]:
        by_track: dict[str, list[CadenceRow]] = {}
        for row in await self._cadences.read_all():
            by_track.setdefault(row.model.track_id, []).append(row.model)
        return {track_id: _chronological(entries) for track_id, entries in by_track.items()}

    async def _supplement_frequencies(self) -> dict[str, str]:
        """Cadence **courante** de chaque supplément, lue au planning (décision **D3**)."""
        return {
            item.schedule_id: item.frequency
            for item in await SupplementService(self._store).schedule()
        }

    async def _record_cadence(self, track_id: str, cadence: Cadence, day: date) -> bool:
        """Ajoute une prise d'effet si la cadence a réellement changé.

        Le journal est en **ajout seul** : on n'y remplace jamais une ligne, même pour
        corriger celle du jour. Deux prises d'effet le même jour sont départagées par
        l'ordre du fichier, et la plus récente gagne — ce qui est le comportement voulu
        quand on se ravise dans la minute.
        """
        entries = (await self._history()).get(track_id, [])
        if entries and self._read_cadence(entries[-1]) == cadence:
            return False

        await self._cadences.append(
            CadenceRow(
                id=_new_id(),
                track_id=track_id,
                type=str(cadence.type),
                params=_params_text(cadence),
                valid_from=day,
            )
        )
        return True

    async def _sync_supplement_cadences(self, rows: list[Row[TrackRow]]) -> None:
        """Réconcilie le journal avec le planning des suppléments (décision **D3**).

        `supplements/schedule.csv` est la valeur courante et il n'y a pas deux endroits
        où écrire « whey un jour sur deux ». Mais ce fichier est modifiable depuis l'écran
        Routine **et à la main dans un tableur** : brancher un déclencheur sur la seule
        écriture de l'application laisserait le journal muet dans le second cas, et le
        moteur jugerait le passé avec une cadence périmée.

        La réconciliation vit donc à la lecture, et elle n'écrit que lorsqu'un écart
        existe réellement. Une lecture qui répare un journal se justifie ici : la justesse
        du journal *est* la fonctionnalité.
        """
        supplement_tracks = [row for row in rows if row.model.source == "supplement.intake"]
        if not supplement_tracks:
            return

        current = await self._supplement_frequencies()
        history = await self._history()
        today = today_local()

        for row in supplement_tracks:
            frequency = current.get(row.model.filter)
            if frequency is None:
                continue  # supplément retiré du planning : l'historique reste jugeable
            try:
                cadence = Cadence.parse(frequency)
            except CadenceError:
                continue  # cadence illisible au planning : ne pas propager l'erreur ici

            entries = history.get(row.model.id, [])
            if entries and self._read_cadence(entries[-1]) == cadence:
                continue
            await self._record_cadence(row.model.id, cadence, today)

    @staticmethod
    def _read_cadence(model: CadenceRow) -> Cadence:
        """Relit une ligne du journal, en retombant sur `daily` si elle est abîmée."""
        raw = f"{model.type}:{model.params}" if model.params else model.type
        try:
            return Cadence.parse(raw)
        except CadenceError:
            return Cadence.parse("daily")

    def _to_schema(
        self, row: Row[TrackRow], history: dict[str, list[CadenceRow]], current: dict[str, str]
    ) -> Track:
        model = row.model
        source = SOURCES.get(model.source)
        entries = history.get(model.id, [])

        cadence = self._current_cadence(model, entries, current)

        return Track(
            id=row.index,
            token=row.token,
            track_id=model.id,
            label=model.label or model.id,
            source=model.source,
            source_label=source.label if source else "source inconnue",
            unit=source.unit if source else "",
            filter=model.filter,
            validation_threshold=model.validation_threshold,
            levels=[] if model.binary else _levels_from_text(model.levels),
            binary=model.binary,
            accent=model.accent if model.accent in ACCENTS else "signal",
            position=model.position,
            active=model.active,
            created=model.created,
            cadence=_cadence_view(cadence, None),
            cadence_history=[
                _cadence_view(self._read_cadence(entry), entry.valid_from) for entry in entries
            ],
        )

    def _current_cadence(
        self, model: TrackRow, entries: list[CadenceRow], current: dict[str, str]
    ) -> Cadence:
        """Cadence en vigueur aujourd'hui.

        Pour un supplément, elle vient du **planning** et non du journal : c'est la
        valeur que l'utilisateur édite, et la seule qui décrive le présent (**D3**).
        """
        if model.source == "supplement.intake" and model.filter in current:
            try:
                return Cadence.parse(current[model.filter])
            except CadenceError:
                pass
        return self._read_cadence(entries[-1]) if entries else Cadence.parse("daily")

    @staticmethod
    def _off_to_schema(row: Row[OffDayRow]) -> OffDay:
        model = row.model
        assert model.date_from is not None and model.date_to is not None
        return OffDay(
            id=row.index,
            token=row.token,
            off_id=model.id,
            track_id=model.track_id,
            date_from=model.date_from,
            date_to=model.date_to,
            reason=model.reason,
            days=(model.date_to - model.date_from).days + 1,
        )


def _chronological(entries: Iterable[CadenceRow]) -> list[CadenceRow]:
    """Trie un journal de cadences, du plus ancien au plus récent.

    Le tri porte sur `valid_from` **seul**, et il est stable : deux prises d'effet le même
    jour gardent donc l'ordre du fichier, et la dernière écrite gagne. C'est le
    comportement voulu quand on se ravise dans la minute.

    Première version : la clé de tri était `(valid_from, id)`. Les identifiants étant
    aléatoires, deux cadences posées le même jour se départageaient **au hasard** — et une
    piste créée puis corrigée dans la foulée pouvait garder l'ancienne règle une fois sur
    deux. Un journal daté au jour ne peut pas s'ordonner par autre chose que son propre
    ordre d'écriture.
    """
    return sorted(entries, key=lambda model: model.valid_from or date.min)


def _params_text(cadence: Cadence) -> str:
    """Corps sérialisé d'une cadence, sans son type — la colonne `params` du fichier."""
    return ";".join(f"{name}={value}" for name, value in sorted(cadence.params.items()))


def _cadence_view(cadence: Cadence, valid_from: date | None) -> CadenceView:
    return CadenceView(
        type=str(cadence.type),
        params=dict(cadence.params),
        label=cadence.describe(),
        serialized=cadence.serialize(),
        valid_from=valid_from,
    )


def _weekly_frequency(days: set[date]) -> int:
    """Fréquence hebdomadaire observée, bornée à 1–7 (décision **D9**).

    Sans historique, on amorce à une fois par semaine plutôt qu'à deux : une piste qu'on
    tient est une piste qu'on regarde, et il est plus facile de monter une exigence que
    de se réconcilier avec une grille rouge.
    """
    return max(1, min(7, round(len(days) / SEED_WEEKS))) if days else 1
