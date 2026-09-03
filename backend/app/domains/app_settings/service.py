"""Lecture et modification des réglages (`L08-01`, `L08-02`).

Le fichier est un simple clé/valeur. Les valeurs de repli sont celles de l'annexe du
backlog, et le serveur les **sert** au lieu de compter sur le frontend pour les recopier :
l'application doit être utilisable immédiatement, avant tout réglage, et les deux côtés ne
doivent pas pouvoir diverger sur ce que vaut un objectif non renseigné.

Un principe traverse ce module : **un réglage illisible ne casse jamais un écran.** Le
fichier est modifiable à la main dans un tableur, et une valeur abîmée y est une
possibilité normale, pas un incident. Chaque lecture typée retombe donc sur son défaut
plutôt que de propager une erreur — c'est un confort d'affichage, pas une donnée de suivi.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.core.validation import usable_base_url
from app.domains.app_settings.models import SettingRow
from app.domains.app_settings.schemas import SettingsPayload, SettingsValues, SettingsView
from app.storage.csv_repo import CsvRepository
from app.storage.files import FileStore
from app.storage.paths import SETTINGS

#: Défauts de l'annexe du backlog. Toute clé absente du fichier prend cette valeur.
DEFAULTS: dict[str, str] = {
    "target_weight_kg": "70",
    "target_protein_g": "150",
    "max_added_sugar_g": "30",
    "target_hydration_ml": "2000",
    "hydration_presets_ml": "250,500,750",
    "heatmap_metric": "activity",
    # Vide, et ce n'est pas un défaut manquant : c'est la fonctionnalité en sommeil
    # (**D1**). Aucune adresse n'est devinée, aucun lien n'est proposé tant que celle-ci
    # n'est pas renseignée.
    "cadence_base_url": "",
}

#: Réglages typés par l'API. Le fichier en porte d'autres — les créneaux `reminders_*` de
#: `NOT-03`, écrits par le domaine Notifications — qui sont conservés à l'écriture sans
#: être exposés ici. Voir `update_keys`, leur point d'entrée.
TYPED_KEYS: tuple[str, ...] = tuple(DEFAULTS)


def _decimal(raw: str, fallback: float) -> float:
    """Nombre décimal, virgule française admise."""
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return fallback


def _whole(raw: str, fallback: int) -> int:
    return round(_decimal(raw, float(fallback)))


def _volumes(raw: str, fallback: list[int]) -> list[int]:
    """Liste de volumes, tolérante à une saisie manuelle bancale (`HYD-02`).

    Les valeurs illisibles ou négatives sont ignorées une par une : une virgule en trop
    ne doit pas faire disparaître les raccourcis qui, eux, sont corrects.
    """
    values = [round(value) for chunk in raw.split(",") if (value := _decimal(chunk.strip(), 0)) > 0]
    return values or fallback


def _render(value: object) -> str:
    """Sérialise une valeur typée vers la cellule du fichier.

    Les nombres sont écrits au plus court — `70`, pas `70.0`. Le fichier doit rester
    agréable à lire dans un tableur (`STO-02`), et un zéro décimal inutile y est du bruit.
    """
    if isinstance(value, list):
        return ",".join(_render(item) for item in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float | int):
        return f"{value:g}"
    return str(value)


def _typed(raw: dict[str, str]) -> SettingsValues:
    """Vue typée d'un jeu de valeurs textuelles complet."""
    return SettingsValues(
        target_weight_kg=_decimal(raw["target_weight_kg"], 70),
        target_protein_g=_decimal(raw["target_protein_g"], 150),
        max_added_sugar_g=_decimal(raw["max_added_sugar_g"], 30),
        target_hydration_ml=_whole(raw["target_hydration_ml"], 2000),
        hydration_presets_ml=_volumes(raw["hydration_presets_ml"], [250, 500, 750]),
        heatmap_metric=raw["heatmap_metric"].strip() or "activity",
        # `usable_base_url` et non un motif recopié ici : la règle de ce qu'est une
        # adresse exploitable vit avec `BaseUrl`, qui la fait respecter à la saisie.
        # Deux écritures finiraient par diverger, et l'écart ne se verrait qu'au clic.
        cadence_base_url=usable_base_url(raw["cadence_base_url"]),
    )


#: Défauts sous leur forme typée. Calculés depuis `DEFAULTS`, jamais recopiés : deux
#: listes à tenir en phase finiraient par diverger.
DEFAULT_VALUES: SettingsValues = _typed(DEFAULTS)


class SettingsService:
    """Accès typé aux réglages, avec repli sur les défauts."""

    def __init__(self, store: FileStore) -> None:
        self._repo: CsvRepository[SettingRow] = CsvRepository(store, SETTINGS, SettingRow)

    # ── Lecture ───────────────────────────────────────

    async def all(self) -> dict[str, str]:
        """Réglages en vigueur, défauts compris, sous leur forme textuelle."""
        rows = await self._repo.read_all()
        stored = {row.model.key: row.model.value for row in rows if row.model.key}
        return {**DEFAULTS, **stored}

    async def get(self, key: str) -> str:
        return (await self.all()).get(key, DEFAULTS.get(key, ""))

    async def number(self, key: str) -> float:
        """Réglage numérique, avec repli sur le défaut si la valeur est illisible."""
        return _decimal(await self.get(key), _decimal(DEFAULTS.get(key, "0"), 0))

    async def values(self) -> SettingsValues:
        """Réglages typés. Le point d'entrée des autres domaines."""
        return _typed(await self.all())

    async def view(self) -> SettingsView:
        sheet = await self._repo.load()
        stored = {row.model.key: row.model.value for row in sheet.rows if row.model.key}

        return SettingsView(
            values=_typed({**DEFAULTS, **stored}),
            defaults=DEFAULT_VALUES,
            stored=[key for key in TYPED_KEYS if key in stored],
            token=sheet.token,
        )

    # ── Écriture (`L08-02`) ───────────────────────────

    async def update(self, payload: SettingsPayload, token: str) -> SettingsView:
        """Applique une modification partielle, sous garde anti-conflit.

        Les clés que l'API ne connaît pas sont **conservées** : le fichier peut porter des
        réglages posés à la main ou par un lot ultérieur, et une modification du poids
        cible n'a aucune raison de les effacer.

        Un champ à `None` est ici « non fourni », pas « à vider » : aucun réglage typé
        n'admet l'absence comme valeur. Les créneaux de rappel, eux, si — d'où
        `update_keys`, plus bas.
        """
        changes = {
            key: _render(value)
            for key, value in payload.model_dump(exclude_unset=True).items()
            if value is not None
        }
        await self.update_keys(changes, token)
        return await self.view()

    async def update_keys(self, changes: Mapping[str, str], token: str) -> None:
        """Écrit des clés **brutes**, sous la même garde que le reste du fichier.

        Point d'entrée des réglages que l'API ne type pas — aujourd'hui les créneaux de
        rappel de `NOT-03`, que le domaine Notifications possède et que celui-ci n'a
        aucune raison de connaître.

        Une différence avec `update`, et elle porte tout le sens : **une valeur vide est
        écrite**, elle n'est pas ignorée. Pour un créneau, la cellule vide *est* la
        donnée — elle veut dire « pas de rappel ». C'est le même parti pris que la colonne
        `time` de `plan.csv`, vide par conception.
        """
        # Lecture cachée, et c'est volontaire : la garde prouve que le fichier est encore
        # celui que le client a lu. S'il avait changé, `overwrite` refuserait — donc une
        # base de fusion périmée ne peut jamais être écrite.
        rows = await self._repo.read_all()
        merged: dict[str, str] = {row.model.key: row.model.value for row in rows if row.model.key}
        merged.update(changes)

        await self._repo.overwrite(
            [SettingRow(key=key, value=value) for key, value in merged.items()],
            token=token,
        )

    async def token(self) -> str:
        """Jeton du fichier, pour un domaine qui écrit ses propres clés (`STO-05`)."""
        return (await self._repo.load()).token


__all__ = ["DEFAULTS", "DEFAULT_VALUES", "TYPED_KEYS", "SettingRow", "SettingsService"]
