"""Calculs du domaine Corps (`BODY-03` → `BODY-09`).

Tout est calculé ici, jamais dans le client : c'est la règle du projet, et elle vaut
autant pour une moyenne mobile que pour une cadence d'assiduité. Un client qui
recalculerait la tendance finirait par afficher une autre courbe que le serveur.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.domains.app_settings.service import SettingsService
from app.domains.body.models import MEASUREMENT_FIELDS, MeasurementRow, WeightRow
from app.domains.body.schemas import (
    MeasurementEntry,
    MeasurementIndicator,
    MeasurementPayload,
    MeasurementView,
    WeightEntry,
    WeightPayload,
    WeightPoint,
    WeightStats,
    WeightView,
)
from app.storage.csv_repo import CsvRepository, Row
from app.storage.files import FileStore
from app.storage.paths import MEASUREMENTS, WEIGHT

#: Fenêtre de la tendance lissée (`BODY-05`).
TREND_DAYS = 7

#: Nombre de pesées sur lesquelles est mesurée la variation (`BODY-03`).
CHANGE_WINDOW = 8


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


class WeightService:
    """Pesées : saisie, correction, indicateurs, tendance."""

    def __init__(self, store: FileStore) -> None:
        self._repo: CsvRepository[WeightRow] = CsvRepository(store, WEIGHT, WeightRow)
        self._settings = SettingsService(store)

    # ── Lecture ───────────────────────────────────────

    async def view(self, *, limit: int, offset: int) -> WeightView:
        rows = await self._repo.read_all()
        target = await self._settings.number("target_weight_kg")

        # Le fichier est en ordre d'écriture : on peut enregistrer aujourd'hui une pesée
        # d'avant-hier. Série et statistiques se lisent dans l'ordre chronologique.
        chronological = sorted(rows, key=lambda row: row.model.date)

        # L'historique, lui, se lit du plus récent au plus ancien (`BODY-06`).
        recent = sorted(rows, key=lambda row: (row.model.date, row.index), reverse=True)
        page = recent[offset : offset + limit]

        return WeightView(
            stats=self._stats(chronological, target),
            series=self._series(chronological),
            entries=[self._entry(row) for row in page],
            total=len(rows),
        )

    async def summary(self) -> WeightStats:
        """Indicateurs seuls, sans la série ni l'historique (`AGG-01`).

        Le tableau de bord n'affiche que les chiffres : lui construire une série de trois
        ans pour en jeter 99 % serait du travail pur perte. Les indicateurs, eux, restent
        calculés par la même fonction que l'écran Corps — deux moyennes du même poids
        finiraient par ne plus dire la même chose.
        """
        rows = await self._repo.read_all()
        target = await self._settings.number("target_weight_kg")
        return self._stats(sorted(rows, key=lambda row: row.model.date), target)

    async def points(self) -> list[tuple[date, float]]:
        """Pesées en couples `(jour, valeur)`, triées (`AGG-04`, `AGG-03`).

        La forme la plus pauvre possible, et c'est le but : les séries temporelles
        génériques n'ont pas à connaître le domaine dont vient le chiffre.
        """
        rows = await self._repo.read_all()
        return sorted((row.model.date, row.model.weight_kg) for row in rows)

    @staticmethod
    def _entry(row: Row[WeightRow]) -> WeightEntry:
        return WeightEntry(
            id=row.index,
            token=row.token,
            date=row.model.date,
            weight_kg=row.model.weight_kg,
            note=row.model.note,
            source=row.model.source,
        )

    @staticmethod
    def _series(rows: list[Row[WeightRow]]) -> list[WeightPoint]:
        """Série avec sa tendance lissée sur 7 jours (`BODY-04`, `BODY-05`).

        La fenêtre est **calendaire** et non un nombre de points : on ne se pèse pas tous
        les jours, et une moyenne des 7 dernières *pesées* couvrirait trois semaines
        après une pause, ce qui lisserait la mauvaise chose.
        """
        points: list[WeightPoint] = []
        for position, row in enumerate(rows):
            horizon = row.model.date - timedelta(days=TREND_DAYS - 1)
            window = [
                other.model.weight_kg
                for other in rows[: position + 1]
                if other.model.date >= horizon
            ]
            points.append(
                WeightPoint(
                    date=row.model.date,
                    weight_kg=row.model.weight_kg,
                    trend_kg=_round(sum(window) / len(window)) if window else None,
                )
            )
        return points

    @staticmethod
    def _stats(rows: list[Row[WeightRow]], target: float) -> WeightStats:
        if not rows:
            return WeightStats(target_kg=target, count=0)

        weights = [row.model.weight_kg for row in rows]
        latest = rows[-1].model

        # Variation sur les huit dernières pesées : de la plus ancienne de la fenêtre à
        # la dernière. Avec moins de deux pesées, il n'y a pas de variation à annoncer.
        window = weights[-CHANGE_WINDOW:]
        change = latest.weight_kg - window[0] if len(window) >= 2 else None

        return WeightStats(
            latest_kg=latest.weight_kg,
            latest_date=latest.date,
            change_kg=_round(change),
            to_target_kg=_round(latest.weight_kg - target),
            target_kg=target,
            min_kg=min(weights),
            max_kg=max(weights),
            amplitude_kg=_round(max(weights) - min(weights)),
            count=len(rows),
        )

    # ── Écriture ──────────────────────────────────────

    async def create(self, payload: WeightPayload) -> WeightEntry:
        row = await self._repo.append(
            WeightRow(date=payload.date, weight_kg=payload.weight_kg, note=payload.note)
        )
        return self._entry(row)

    async def update(self, index: int, token: str, payload: WeightPayload) -> WeightEntry:
        existing = await self._repo.read_all(fresh=True)
        source = existing[index].model.source if 0 <= index < len(existing) else "manual"

        row = await self._repo.replace_by_token(
            index,
            token,
            # La source est préservée : corriger une valeur importée d'Apple n'en fait
            # pas une saisie manuelle (`IMP-05`).
            WeightRow(
                date=payload.date,
                weight_kg=payload.weight_kg,
                note=payload.note,
                source=source,
            ),
        )
        return self._entry(row)

    async def delete(self, index: int, token: str) -> None:
        await self._repo.delete_by_token(index, token)


class MeasurementService:
    """Mensurations : saisie, indicateurs, historique."""

    def __init__(self, store: FileStore) -> None:
        self._repo: CsvRepository[MeasurementRow] = CsvRepository(
            store, MEASUREMENTS, MeasurementRow
        )

    async def view(self, *, limit: int, offset: int) -> MeasurementView:
        rows = await self._repo.read_all()
        chronological = sorted(rows, key=lambda row: row.model.date)
        recent = sorted(rows, key=lambda row: (row.model.date, row.index), reverse=True)

        return MeasurementView(
            indicators=self._indicators(chronological),
            entries=[self._entry(row) for row in recent[offset : offset + limit]],
            total=len(rows),
        )

    async def days(self) -> set[date]:
        """Jours portant un relevé — source de la série d'assiduité (`AGG-03`)."""
        return {row.model.date for row in await self._repo.read_all()}

    async def points(self, field: str) -> list[tuple[date, float]]:
        """Historique d'**une** mesure (`AGG-04`).

        Chaque mesure a le sien : on ne mesure pas tout à chaque fois, et une série de
        tours de bras ne doit pas se trouer parce qu'un jour seul le poids a été relevé.
        """
        rows = await self._repo.read_all()
        return sorted(
            (row.model.date, value)
            for row in rows
            if (value := getattr(row.model, field, None)) is not None
        )

    @staticmethod
    def _entry(row: Row[MeasurementRow]) -> MeasurementEntry:
        model = row.model
        return MeasurementEntry(
            id=row.index,
            token=row.token,
            date=model.date,
            waist_cm=model.waist_cm,
            chest_cm=model.chest_cm,
            arm_cm=model.arm_cm,
            hips_cm=model.hips_cm,
            thigh_cm=model.thigh_cm,
            body_fat_pct=model.body_fat_pct,
            note=model.note,
        )

    @staticmethod
    def _indicators(rows: list[Row[MeasurementRow]]) -> list[MeasurementIndicator]:
        """Dernière valeur, écart et sens, mesure par mesure (`BODY-08`).

        Chaque mesure a son propre historique : on ne mesure pas tout à chaque fois, donc
        « le relevé précédent » d'un tour de bras n'est pas forcément la ligne d'avant.
        """
        indicators: list[MeasurementIndicator] = []

        for field, label in MEASUREMENT_FIELDS:
            history = [
                (row.model.date, value)
                for row in rows
                if (value := getattr(row.model, field)) is not None
            ]
            unit = "%" if field == "body_fat_pct" else "cm"

            if not history:
                indicators.append(MeasurementIndicator(field=field, label=label, unit=unit))
                continue

            last_date, last_value = history[-1]
            delta = last_value - history[-2][1] if len(history) >= 2 else None
            direction = None
            if delta is not None:
                direction = "flat" if abs(delta) < 0.05 else ("up" if delta > 0 else "down")

            indicators.append(
                MeasurementIndicator(
                    field=field,
                    label=label,
                    latest=last_value,
                    latest_date=last_date,
                    delta=_round(delta),
                    direction=direction,
                    unit=unit,
                )
            )
        return indicators

    async def create(self, payload: MeasurementPayload) -> MeasurementEntry:
        row = await self._repo.append(MeasurementRow(**payload.model_dump()))
        return self._entry(row)

    async def update(self, index: int, token: str, payload: MeasurementPayload) -> MeasurementEntry:
        row = await self._repo.replace_by_token(
            index, token, MeasurementRow(**payload.model_dump())
        )
        return self._entry(row)

    async def delete(self, index: int, token: str) -> None:
        await self._repo.delete_by_token(index, token)


__all__ = ["CHANGE_WINDOW", "TREND_DAYS", "MeasurementService", "WeightService", "date"]
