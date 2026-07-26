"""Configuration centralisée (`API-02`).

Toute la configuration passe par l'environnement — aucun secret dans le code, aucun
secret exposé au client. Les valeurs de repli sont choisies pour que l'application
démarre et reste inspectable même sans `.env`, ce qui permet de lancer les tests et
le kitchen sink sans Nextcloud.

Le durcissement de la validation (secrets obligatoires en production, bornes de
vraisemblance) relève de `L02-02`.
"""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Réglages du service, lus depuis l'environnement puis `.env`."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Service ───────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"

    # Fuseau de découpage des journées (`HEAT-32`). Jamais UTC : une prise à 23 h 30
    # appartient au jour affiché par l'horloge.
    timezone: str = "Europe/Paris"

    # ── Stockage Nextcloud / WebDAV (`STO-01`) ─────────
    nextcloud_url: str = ""
    nextcloud_username: str = ""
    nextcloud_password: str = ""
    nextcloud_root: str = "Metric"

    # ── Authentification (`AUTH-01`, `AUTH-02`, `AUTH-03`) ──
    auth_username: str = ""
    auth_password_hash: str = ""
    jwt_secret: str = "dev-secret-a-remplacer"
    jwt_algorithm: str = "HS256"
    jwt_ttl_days: int = 7

    # ── CORS (`API-03`) ───────────────────────────────
    # Liste séparée par des virgules : pydantic-settings traiterait un `list[str]`
    # comme du JSON, ce qui interdirait la forme lisible en `.env`.
    cors_origins: str = "http://localhost:5173"

    # ── IA OpenRouter (`IA-01`, `IA-07`) ──────────────
    # Sans clé, les fonctions IA renvoient un message clair et le reste de
    # l'application fonctionne intégralement en saisie manuelle.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = ""

    # ── Export iCal (`PLAN-05`) ───────────────────────
    ical_secret: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        """Origines autorisées, sous forme de liste exploitable."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def tz(self) -> ZoneInfo:
        """Fuseau local de l'application."""
        return ZoneInfo(self.timezone)

    @property
    def ai_enabled(self) -> bool:
        """Vrai si une clé OpenRouter est configurée (`IA-07`)."""
        return bool(self.openrouter_api_key)

    @property
    def storage_configured(self) -> bool:
        """Vrai si le stockage Nextcloud est renseigné."""
        return bool(self.nextcloud_url and self.nextcloud_username)


@lru_cache
def get_settings() -> Settings:
    """Réglages mémorisés — un seul chargement par processus."""
    return Settings()
