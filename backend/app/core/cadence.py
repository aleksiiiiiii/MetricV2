"""Cadence d'un engagement (`HEAT-09` → `HEAT-14`, `HEAT-23`, décision **D3**).

Une cadence dit **ce qui est attendu**, pas ce qui a été fait. Cinq formes, reprises de
la spec d'assiduité v2 :

| Type | Paramètres | Lecture |
|---|---|---|
| `daily` | — | attendu tous les jours |
| `window` | `min_count`, `window_days` | N fois par fenêtre glissante de D jours |
| `per_week` | `count` | N fois par semaine ISO |
| `conditional` | `trigger` | attendu si un déclencheur est vrai |
| `none` | — | aucune attente, piste descriptive |

## Pourquoi cet objet vit dans le socle

La décision **D3** lie la cadence d'un supplément à `supplements/schedule.csv` et son
historique à `settings/heatmap_cadences.csv`. Deux fichiers, deux domaines, une seule
grammaire — la coder deux fois reproduirait l'erreur évitée au lot L05 avec l'analyse
des durées.

**Ce module ne décide pas si un jour est validé.** Il ne fait que lire, écrire et
valider la forme. L'évaluation est le cœur du moteur d'assiduité, construit au lot L10.

## Forme sérialisée

Une seule colonne doit porter type et paramètres, et rester lisible en tableur
(`STO-02`) :

    daily
    window:min_count=1;window_days=2
    per_week:count=3
    conditional:trigger=workout
    none
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CadenceType(StrEnum):
    DAILY = "daily"
    WINDOW = "window"
    PER_WEEK = "per_week"
    CONDITIONAL = "conditional"
    NONE = "none"


class CadenceError(ValueError):
    """Cadence illisible ou incohérente. Le message est destiné à l'utilisateur."""


#: Paramètres obligatoires par type, et leur type attendu.
_REQUIRED: dict[CadenceType, dict[str, type]] = {
    CadenceType.DAILY: {},
    CadenceType.WINDOW: {"min_count": int, "window_days": int},
    CadenceType.PER_WEEK: {"count": int},
    CadenceType.CONDITIONAL: {"trigger": str},
    CadenceType.NONE: {},
}


@dataclass(frozen=True, slots=True)
class Cadence:
    """Type et paramètres d'un engagement."""

    type: CadenceType
    params: dict[str, str | int] = field(default_factory=dict)

    # ── Lecture ───────────────────────────────────────

    @classmethod
    def parse(cls, raw: str) -> Cadence:
        """Lit la forme sérialisée. Une valeur vide vaut `daily`.

        Le repli sur `daily` est délibéré : une ligne de planning existante sans colonne
        `frequency` — le cas de tout fichier antérieur à ce lot — décrit un complément
        qu'on prend tous les jours, c'est l'usage le plus courant et le moins surprenant.
        """
        text = (raw or "").strip()
        if not text:
            return cls(CadenceType.DAILY)

        head, _, tail = text.partition(":")
        try:
            kind = CadenceType(head.strip().lower())
        except ValueError as exc:
            raise CadenceError(f"cadence inconnue : « {head} »") from exc

        params: dict[str, str | int] = {}
        for chunk in tail.split(";"):
            if not chunk.strip():
                continue
            name, _, value = chunk.partition("=")
            params[name.strip()] = value.strip()

        return cls(kind, params).validated()

    def validated(self) -> Cadence:
        """Vérifie que les paramètres exigés par le type sont présents et bien typés."""
        expected = _REQUIRED[self.type]
        cleaned: dict[str, str | int] = {}

        for name, kind in expected.items():
            if name not in self.params:
                raise CadenceError(f"cadence « {self.type} » : paramètre « {name} » manquant")
            raw = self.params[name]
            if kind is int:
                try:
                    number = int(raw)
                except (TypeError, ValueError) as exc:
                    raise CadenceError(f"« {name} » doit être un entier") from exc
                if number < 1:
                    raise CadenceError(f"« {name} » doit valoir au moins 1")
                cleaned[name] = number
            else:
                text = str(raw).strip()
                if not text:
                    raise CadenceError(f"« {name} » ne peut pas être vide")
                cleaned[name] = text

        # Une fenêtre qui exige plus de validations qu'elle ne compte de jours est
        # intenable par construction : mieux vaut le dire à la saisie.
        if self.type is CadenceType.WINDOW and int(cleaned["min_count"]) > int(
            cleaned["window_days"]
        ):
            raise CadenceError(
                "une fenêtre ne peut pas exiger plus de prises qu'elle ne compte de jours"
            )
        if self.type is CadenceType.PER_WEEK and int(cleaned["count"]) > 7:
            raise CadenceError("une semaine ne compte que sept jours")

        return Cadence(self.type, cleaned)

    # ── Écriture ──────────────────────────────────────

    def serialize(self) -> str:
        """Forme stockée en CSV, lisible en tableur."""
        if not self.params:
            return str(self.type)
        body = ";".join(f"{name}={value}" for name, value in sorted(self.params.items()))
        return f"{self.type}:{body}"

    def describe(self) -> str:
        """Formulation française, pour l'afficher sans que le client la reconstruise."""
        match self.type:
            case CadenceType.DAILY:
                return "tous les jours"
            case CadenceType.WINDOW:
                count, days = self.params["min_count"], self.params["window_days"]
                if int(count) == 1 and int(days) == 2:
                    return "un jour sur deux"
                return f"{count} fois par {days} jours"
            case CadenceType.PER_WEEK:
                count = int(self.params["count"])
                return "une fois par semaine" if count == 1 else f"{count} fois par semaine"
            case CadenceType.CONDITIONAL:
                return f"les jours de {self.params['trigger']}"
            case CadenceType.NONE:
                return "sans attente"

    def __str__(self) -> str:
        return self.serialize()


DAILY = Cadence(CadenceType.DAILY)
