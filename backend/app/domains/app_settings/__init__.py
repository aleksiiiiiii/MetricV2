"""Réglages utilisateur (`settings/settings.csv`, décision **D2**).

Lecture seule pour l'instant : les endpoints d'édition sont construits au lot L08. Les
domaines qui ont besoin d'une valeur — l'écart au poids cible (`BODY-03`), l'objectif
d'hydratation (`HYD-03`) — passent par ici plutôt que d'inventer une constante.
"""

from app.domains.app_settings.router import router
from app.domains.app_settings.service import DEFAULTS, SettingsService

__all__ = ["DEFAULTS", "SettingsService", "router"]
