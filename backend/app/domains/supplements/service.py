"""Planning, checklist et prises de suppléments (`SUP-01` → `SUP-06`)."""

from __future__ import annotations

import secrets
from datetime import date, timedelta

from app.core.cadence import Cadence
from app.core.dates import local_day_of, now_local, today_local
from app.domains.supplements.models import ScheduleRow, SupplementIntakeRow
from app.domains.supplements.schemas import (
    ChecklistItem,
    ChecklistView,
    DayRatio,
    Supplement,
    SupplementPayload,
)
from app.storage.csv_repo import CsvRepository, Row
from app.storage.errors import StorageNotFoundError
from app.storage.files import FileStore
from app.storage.paths import SUPPLEMENT_LOG, SUPPLEMENT_SCHEDULE

#: Profondeur maximale de calcul d'une série. Au-delà, l'information n'ajoute rien et
#: le coût de lecture augmente sans raison.
STREAK_LIMIT = 400


class SupplementService:
    def __init__(self, store: FileStore) -> None:
        self._schedule: CsvRepository[ScheduleRow] = CsvRepository(
            store, SUPPLEMENT_SCHEDULE, ScheduleRow
        )
        self._log: CsvRepository[SupplementIntakeRow] = CsvRepository(
            store, SUPPLEMENT_LOG, SupplementIntakeRow
        )

    # ── Planning (`SUP-01`, `SUP-02`) ─────────────────

    @staticmethod
    def _to_schema(row: Row[ScheduleRow]) -> Supplement:
        model = row.model
        return Supplement(
            id=row.index,
            token=row.token,
            schedule_id=model.id,
            name=model.name,
            dose=model.dose,
            unit=model.unit,
            time=model.time,
            frequency=model.frequency,
            cadence_label=Cadence.parse(model.frequency).describe(),
            active=model.active,
            created=model.created,
        )

    async def schedule(self, *, active_only: bool = False) -> list[Supplement]:
        """Planning trié par horaire — l'ordre de la checklist (`SUP-01`)."""
        rows = await self._schedule.read_all()
        items = [self._to_schema(row) for row in rows]
        if active_only:
            items = [item for item in items if item.active]
        return sorted(items, key=lambda item: (item.time, item.name))

    async def create(self, payload: SupplementPayload) -> Supplement:
        row = await self._schedule.append(
            ScheduleRow(
                id=secrets.token_hex(6),
                name=payload.name,
                dose=payload.dose,
                unit=payload.unit,
                time=payload.time,
                frequency=payload.frequency,
                active=payload.active,
                # Date d'entrée au planning : ajouter la créatine aujourd'hui ne rendra
                # pas rouges les six mois précédents (`HEAT-07`).
                created=today_local(),
            )
        )
        return self._to_schema(row)

    async def update(self, index: int, token: str, payload: SupplementPayload) -> Supplement:
        rows = await self._schedule.read_all(fresh=True)
        if not 0 <= index < len(rows):
            raise StorageNotFoundError("Ce supplément n'est pas au planning.")
        existing = rows[index].model

        row = await self._schedule.replace_by_token(
            index,
            token,
            ScheduleRow(
                # Identifiant et date d'entrée survivent : le journal s'y rattache, et la
                # non-rétroactivité ne doit pas se réinitialiser à chaque correction.
                id=existing.id,
                name=payload.name,
                dose=payload.dose,
                unit=payload.unit,
                time=payload.time,
                frequency=payload.frequency,
                active=payload.active,
                created=existing.created,
            ),
        )
        return self._to_schema(row)

    async def remove(self, index: int, token: str) -> None:
        """Retire du planning **sans toucher au journal** (`SUP-02`).

        L'historique des prises déjà enregistrées survit — c'est pourquoi le journal
        duplique le nom, la dose et l'unité.
        """
        await self._schedule.delete_by_token(index, token)

    # ── Checklist (`SUP-03`, `SUP-05`, `SUP-06`) ──────

    async def checklist(self, day: date) -> ChecklistView:
        """État du jour. Repart vierge chaque jour : rien n'est mémorisé, tout est déduit
        du journal des prises."""
        planned = await self.schedule(active_only=True)
        entries = await self._log.read_all()

        taken_today = {
            row.model.schedule_id: row
            for row in entries
            if local_day_of(row.model.datetime_) == day
        }
        streaks = self._streaks(entries, day)

        items: list[ChecklistItem] = []
        for supplement in planned:
            row = taken_today.get(supplement.schedule_id)
            items.append(
                ChecklistItem(
                    schedule_id=supplement.schedule_id,
                    name=supplement.name,
                    dose=supplement.dose,
                    unit=supplement.unit,
                    time=supplement.time,
                    cadence_label=supplement.cadence_label,
                    taken=row is not None,
                    taken_at=row.model.datetime_ if row else None,
                    intake_id=row.index if row else None,
                    intake_token=row.token if row else None,
                    streak=streaks.get(supplement.schedule_id, 0),
                )
            )

        taken = sum(1 for item in items if item.taken)
        return ChecklistView(
            date=day,
            items=items,
            ratio=DayRatio(
                taken=taken,
                planned=len(items),
                ratio=taken / len(items) if items else 0.0,
                # « Journée complète » exige que tout ait été coché, pas la majorité.
                complete=bool(items) and taken == len(items),
            ),
        )

    async def intakes(self) -> list[Row[SupplementIntakeRow]]:
        """Journal complet des prises — source de la piste `supplement.intake`."""
        return await self._log.read_all()

    async def intake_days(self) -> set[date]:
        """Jours portant au moins une prise — source de la série d'assiduité (`AGG-03`)."""
        return {local_day_of(row.model.datetime_) for row in await self.intakes()}

    @staticmethod
    def _streaks(entries: list[Row[SupplementIntakeRow]], day: date) -> dict[str, int]:
        """Jours consécutifs de prise, en remontant depuis `day`.

        La journée en cours ne casse pas la série tant qu'elle n'est pas terminée : on
        compte à partir de `day` si la prise est faite, sinon à partir de la veille.
        C'est la règle déjà appliquée à la série d'assiduité (`AGG-03`).
        """
        by_supplement: dict[str, set[date]] = {}
        for row in entries:
            by_supplement.setdefault(row.model.schedule_id, set()).add(
                local_day_of(row.model.datetime_)
            )

        streaks: dict[str, int] = {}
        for schedule_id, days in by_supplement.items():
            cursor = day if day in days else day - timedelta(days=1)
            count = 0
            while cursor in days and count < STREAK_LIMIT:
                count += 1
                cursor -= timedelta(days=1)
            streaks[schedule_id] = count
        return streaks

    async def take(self, schedule_id: str) -> ChecklistView:
        """Coche un item : écrit une prise horodatée (`SUP-03`)."""
        planned = await self.schedule()
        supplement = next((item for item in planned if item.schedule_id == schedule_id), None)
        if supplement is None:
            raise StorageNotFoundError("Ce supplément n'est pas au planning.")

        day = today_local()
        current = await self.checklist(day)
        if any(item.schedule_id == schedule_id and item.taken for item in current.items):
            # Déjà pris aujourd'hui : la bascule est idempotente, deux clics rapides ne
            # doivent pas écrire deux prises.
            return current

        await self._log.append(
            SupplementIntakeRow(
                datetime_=now_local(),
                schedule_id=schedule_id,
                # Dupliqué pour que l'historique survive au retrait du planning.
                name=supplement.name,
                dose=supplement.dose,
                unit=supplement.unit,
            )
        )
        return await self.checklist(day)

    async def untake(self, schedule_id: str) -> ChecklistView:
        """Décoche : supprime la prise du jour (`SUP-05`)."""
        day = today_local()
        removed = await self._log.remove_where(
            lambda row: row.schedule_id == schedule_id and local_day_of(row.datetime_) == day
        )
        del removed
        return await self.checklist(day)
