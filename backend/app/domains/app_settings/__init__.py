"""Réglages utilisateur (`settings/settings.csv`, décision **D2**).

Les domaines qui ont besoin d'une valeur — l'écart au poids cible (`BODY-03`), l'objectif
d'hydratation (`HYD-03`), le plafond de sucres (`NUT-06`) — passent par ici plutôt que
d'inventer une constante. C'est ce qui a permis au lot L08 de rendre ces valeurs
éditables sans toucher aux domaines qui les consomment.
"""

from app.domains.app_settings.router import router
from app.domains.app_settings.service import DEFAULT_VALUES, DEFAULTS, SettingsService

__all__ = ["DEFAULTS", "DEFAULT_VALUES", "SettingsService", "router"]
