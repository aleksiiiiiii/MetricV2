"""Repas, totaux et favoris (`NUT-01` → `NUT-10`)."""

from __future__ import annotations

import secrets
from datetime import date, datetime

from app.core.dates import local_day_of, now_local
from app.domains.app_settings.service import SettingsService
from app.domains.nutrition.models import TYPE_BY_HOUR, FavoriteRow, MealRow, MealType
from app.domains.nutrition.photos import build_path, content_type, storage_path
from app.domains.nutrition.schemas import (
    DayTotals,
    Favorite,
    FavoritePayload,
    Meal,
    MealPayload,
    NutritionView,
)
from app.storage.csv_repo import CsvRepository, Row
from app.storage.errors import StorageNotFoundError
from app.storage.files import FileStore
from app.storage.paths import MEAL_FAVORITES, MEAL_PHOTOS, MEALS


def suggested_type(moment: datetime) -> MealType:
    """Type présélectionné selon l'heure (`NUT-03`)."""
    for until, kind in TYPE_BY_HOUR:
        if moment.hour < until:
            return kind
    return MealType.DINNER


class NutritionService:
    def __init__(self, store: FileStore) -> None:
        self._store = store
        self._meals: CsvRepository[MealRow] = CsvRepository(store, MEALS, MealRow)
        self._favorites: CsvRepository[FavoriteRow] = CsvRepository(
            store, MEAL_FAVORITES, FavoriteRow
        )
        self._settings = SettingsService(store)

    # ── Lecture ───────────────────────────────────────

    @staticmethod
    def _to_schema(row: Row[MealRow]) -> Meal:
        model = row.model
        return Meal(
            id=row.index,
            token=row.token,
            datetime=model.datetime_,
            meal_type=model.meal_type,
            comment=model.comment,
            photo=model.photo,
            protein_g=model.protein_g,
            added_sugar_g=model.added_sugar_g,
            calories=model.calories,
            source=model.source,
        )

    async def totals(self, day: date) -> DayTotals:
        """Totaux du jour seuls (`NUT-06`, `AGG-01`).

        Le tableau de bord s'arrête là : lui servir le journal complet et les favoris
        coûterait une lecture de fichier pour rien.
        """
        rows = await self._meals.read_all()
        today = [row for row in rows if local_day_of(row.model.datetime_) == day]

        values = await self._settings.values()
        protein_target = values.target_protein_g
        sugar_max = values.max_added_sugar_g

        protein = sum(row.model.protein_g or 0 for row in today)
        sugar = sum(row.model.added_sugar_g or 0 for row in today)

        return DayTotals(
            protein_g=round(protein, 1),
            protein_target_g=protein_target,
            protein_ratio=min(1.0, protein / protein_target) if protein_target else 0.0,
            added_sugar_g=round(sugar, 1),
            added_sugar_max_g=sugar_max,
            # Un dépassement est un signal, pas une réussite : il se dit à part du ratio
            # de protéines.
            over_sugar=sugar > sugar_max,
            calories=sum(row.model.calories or 0 for row in today),
            calories_known=sum(1 for row in today if row.model.calories is not None),
            meals=len(today),
        )

    async def meal_days(self) -> set[date]:
        """Jours portant au moins un repas — source de la série d'assiduité (`AGG-03`)."""
        rows = await self._meals.read_all()
        return {local_day_of(row.model.datetime_) for row in rows}

    async def view(self, day: date, *, limit: int | None = None) -> NutritionView:
        rows = await self._meals.read_all()
        today = [row for row in rows if local_day_of(row.model.datetime_) == day]

        listed = sorted(today, key=lambda row: row.model.datetime_, reverse=True)
        if limit is not None:
            listed = listed[:limit]

        return NutritionView(
            date=day,
            totals=await self.totals(day),
            meals=[self._to_schema(row) for row in listed],
            favorites=await self.favorites(),
            suggested_type=suggested_type(now_local()).value,
            types=[kind.value for kind in MealType],
        )

    # ── Écriture (`NUT-01`, `NUT-02`, `NUT-09`) ───────

    async def create(
        self,
        *,
        meal_type: str,
        comment: str | None,
        photo: bytes | None,
        protein_g: float | None,
        added_sugar_g: float | None,
        calories: int | None,
        source: str = "manual",
    ) -> Meal:
        moment = now_local()

        relative: str | None = None
        if photo:
            relative = build_path(photo, moment)
            await self._store.write_binary(
                f"{MEAL_PHOTOS}/{relative}", photo, content_type=content_type(relative)
            )

        row = await self._meals.append(
            MealRow(
                datetime_=moment,
                meal_type=meal_type,
                comment=comment,
                photo=relative,
                protein_g=protein_g,
                added_sugar_g=added_sugar_g,
                calories=calories,
                source=source,
            )
        )
        return self._to_schema(row)

    async def update(self, index: int, token: str, payload: MealPayload) -> Meal:
        rows = await self._meals.read_all(fresh=True)
        if not 0 <= index < len(rows):
            raise StorageNotFoundError("Ce repas n'existe pas.")
        existing = rows[index].model

        row = await self._meals.replace_by_token(
            index,
            token,
            MealRow(
                datetime_=payload.datetime or existing.datetime_,
                meal_type=payload.meal_type,
                comment=payload.comment,
                # Photo et source d'origine préservées (`NUT-09`) : corriger une macro
                # estimée par l'IA ne supprime pas la photo ni ne réécrit la provenance.
                photo=existing.photo,
                protein_g=payload.protein_g,
                added_sugar_g=payload.added_sugar_g,
                calories=payload.calories,
                source=existing.source,
            ),
        )
        return self._to_schema(row)

    async def delete(self, index: int, token: str) -> None:
        """Supprime la ligne du repas.

        La photo reste sur Nextcloud : elle est rangée par date, consultable hors de
        l'app, et l'effacer d'un clic dans une liste ferait perdre un souvenir qu'aucune
        annulation ne rendrait. La suppression du fichier reste manuelle, et assumée.
        """
        await self._meals.delete_by_token(index, token)

    async def read_photo(self, relative: str) -> tuple[bytes, str]:
        """Contenu d'une photo, après validation stricte du chemin (`NUT-08`)."""
        data = await self._store.read_binary(storage_path(relative))
        if not data:
            raise StorageNotFoundError("Cette photo n'existe pas.")
        return data, content_type(relative)

    # ── Favoris (`NUT-10`) ────────────────────────────

    @staticmethod
    def _favorite_to_schema(row: Row[FavoriteRow]) -> Favorite:
        return Favorite(
            id=row.index,
            token=row.token,
            favorite_id=row.model.id,
            name=row.model.name,
            protein_g=row.model.protein_g,
            added_sugar_g=row.model.added_sugar_g,
            calories=row.model.calories,
        )

    async def favorites(self) -> list[Favorite]:
        rows = await self._favorites.read_all()
        # Un favori sans identifiant ne peut pas être rejoué : on l'écarte de la liste
        # plutôt que d'offrir un bouton qui échouerait.
        return [self._favorite_to_schema(row) for row in rows if row.model.id]

    async def add_favorite(self, payload: FavoritePayload) -> Favorite:
        row = await self._favorites.append(
            FavoriteRow(
                id=secrets.token_hex(6),
                name=payload.name,
                protein_g=payload.protein_g,
                added_sugar_g=payload.added_sugar_g,
                calories=payload.calories,
            )
        )
        return self._favorite_to_schema(row)

    async def remove_favorite(self, index: int, token: str) -> None:
        await self._favorites.delete_by_token(index, token)

    async def replay_favorite(self, favorite_id: str) -> Meal:
        """Rejoue un repas récurrent en une action, sans photo ni IA (`NUT-10`)."""
        favorite = next(
            (item for item in await self.favorites() if item.favorite_id == favorite_id), None
        )
        if favorite is None:
            raise StorageNotFoundError("Ce repas favori n'existe pas.")

        return await self.create(
            meal_type=suggested_type(now_local()).value,
            comment=favorite.name,
            photo=None,
            protein_g=favorite.protein_g,
            added_sugar_g=favorite.added_sugar_g,
            calories=favorite.calories,
        )
