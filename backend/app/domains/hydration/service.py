"""Calculs de l'hydratation (`HYD-03`, `HYD-05`)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from app.core.dates import days_between, local_day_of, now_local
from app.domains.app_settings.service import SettingsService
from app.domains.hydration.models import DRINK_KINDS, IntakeRow
from app.domains.hydration.schemas import (
    DayVolume,
    HydrationStats,
    HydrationView,
    Intake,
    IntakePayload,
)
from app.storage.csv_repo import CsvRepository, Row
from app.storage.files import FileStore
from app.storage.paths import HYDRATION_LOG

#: Profondeur de la série renvoyée par défaut.
HISTORY_DAYS = 30

#: Repli si le réglage est absent ou illisible.
DEFAULT_PRESETS = (250, 500, 750)


class HydrationService:
    def __init__(self, store: FileStore) -> None:
        self._repo: CsvRepository[IntakeRow] = CsvRepository(store, HYDRATION_LOG, IntakeRow)
        self._settings = SettingsService(store)

    @staticmethod
    def _to_schema(row: Row[IntakeRow]) -> Intake:
        return Intake(
            id=row.index,
            token=row.token,
            datetime=row.model.datetime_,
            volume_ml=row.model.volume_ml,
            kind=row.model.kind,
        )

    async def _presets(self) -> list[int]:
        """Raccourcis de volume (`HYD-02`), tolérants à une saisie manuelle bancale."""
        raw = await self._settings.get("hydration_presets_ml")
        values: list[int] = []
        for chunk in raw.split(","):
            try:
                value = int(chunk.strip())
            except ValueError:
                continue
            if value > 0:
                values.append(value)
        return values or list(DEFAULT_PRESETS)

    async def view(self, today: date, *, days: int = HISTORY_DAYS) -> HydrationView:
        rows = await self._repo.read_all()
        target = int(await self._settings.number("target_hydration_ml"))
        presets = await self._presets()

        # Le rattachement au jour suit le fuseau local : une prise à 23 h 30 appartient
        # au jour qu'affiche l'horloge (`HEAT-32`).
        per_day: defaultdict[date, int] = defaultdict(int)
        for row in rows:
            per_day[local_day_of(row.model.datetime_)] += row.model.volume_ml

        start = today - timedelta(days=days - 1)
        series = [
            DayVolume(
                date=day,
                volume_ml=per_day.get(day, 0),
                reached=per_day.get(day, 0) >= target,
            )
            # Plage complète : les jours sans prise sont retournés à zéro, pas omis.
            for day in days_between(start, today)
        ]

        today_ml = per_day.get(today, 0)
        return HydrationView(
            stats=HydrationStats(
                today_ml=today_ml,
                target_ml=target,
                ratio=min(1.0, today_ml / target) if target > 0 else 0.0,
                average_7d_ml=self._average(series[-7:]),
                average_30d_ml=self._average(series),
                days_reached=sum(1 for day in series if day.reached),
                days_counted=len(series),
            ),
            series=series,
            today=[
                self._to_schema(row) for row in rows if local_day_of(row.model.datetime_) == today
            ],
            presets_ml=presets,
            kinds=list(DRINK_KINDS),
        )

    @staticmethod
    def _average(days: list[DayVolume]) -> int | None:
        """Moyenne sur la fenêtre. `None` sans aucun jour, jamais zéro par défaut."""
        if not days:
            return None
        return round(sum(day.volume_ml for day in days) / len(days))

    async def create(self, payload: IntakePayload) -> Intake:
        row = await self._repo.append(
            IntakeRow(
                # Par défaut maintenant : la cible est un relevé en un geste.
                datetime_=payload.datetime or now_local(),
                volume_ml=payload.volume_ml,
                kind=payload.kind,
            )
        )
        return self._to_schema(row)

    async def delete(self, index: int, token: str) -> None:
        await self._repo.delete_by_token(index, token)
