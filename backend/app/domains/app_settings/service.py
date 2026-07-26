"""Lecture des réglages.

Le fichier est un simple clé/valeur. Les valeurs de repli sont celles de l'annexe du
backlog, et elles sont **partagées avec le frontend** : l'application doit être utilisable
immédiatement, avant tout réglage.
"""

from __future__ import annotations

from app.storage.csv_repo import CsvRepository
from app.storage.files import FileStore
from app.storage.model import CsvModel
from app.storage.paths import SETTINGS

#: Défauts de l'annexe du backlog. Toute clé absente du fichier prend cette valeur.
DEFAULTS: dict[str, str] = {
    "target_weight_kg": "70",
    "target_protein_g": "150",
    "max_added_sugar_g": "30",
    "target_hydration_ml": "2000",
    "hydration_presets_ml": "250,500,750",
    "heatmap_metric": "activity",
}


class SettingRow(CsvModel):
    key: str
    value: str


class SettingsService:
    """Accès typé aux réglages, avec repli sur les défauts."""

    def __init__(self, store: FileStore) -> None:
        self._repo = CsvRepository(store, SETTINGS, SettingRow)

    async def all(self) -> dict[str, str]:
        rows = await self._repo.read_all()
        stored = {row.model.key: row.model.value for row in rows if row.model.key}
        return {**DEFAULTS, **stored}

    async def get(self, key: str) -> str:
        return (await self.all()).get(key, DEFAULTS.get(key, ""))

    async def number(self, key: str) -> float:
        """Réglage numérique, avec repli sur le défaut si la valeur est illisible.

        Un réglage corrompu à la main dans un tableur ne doit pas empêcher l'application
        de fonctionner : c'est un confort d'affichage, pas une donnée.
        """
        raw = await self.get(key)
        try:
            return float(raw.replace(",", "."))
        except ValueError:
            return float(DEFAULTS.get(key, "0") or 0)
