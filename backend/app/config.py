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

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Valeur de repli du secret JWT. Utilisable en développement, refusée en production.
#: Au moins 32 octets : en deçà, PyJWT signale une clé HMAC trop courte pour SHA-256
#: (RFC 7518 §3.2), et le développement croulerait sous les avertissements.
DEV_JWT_SECRET = "developpement-uniquement-a-remplacer-en-production"

#: Longueur minimale de la clé d'abonnement iCal (`PLAN-05`).
#:
#: Cette clé est le **seul** rempart d'une URL publique qui expose un planning personnel :
#: aucun jeton ne l'accompagne, aucun anti-brute-force ne la protège — un client de
#: calendrier ne saurait ni porter l'un ni encaisser l'autre. 32 caractères, c'est ce que
#: rend `secrets.token_urlsafe(24)`, et c'est le plancher en deçà duquel une clé se
#: devine. En dessous, le flux n'est simplement pas publié.
ICAL_SECRET_MIN_LENGTH = 32


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
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_ttl_days: int = 7

    # ── CORS (`API-03`) ───────────────────────────────
    # Liste séparée par des virgules : pydantic-settings traiterait un `list[str]`
    # comme du JSON, ce qui interdirait la forme lisible en `.env`.
    cors_origins: str = "http://localhost:5173"

    # Derrière un reverse-proxy (`OPS-01`), l'adresse de l'appelant est dans
    # `X-Forwarded-For` (`AUTH-04`). Faux par défaut : en exposition directe, l'en-tête
    # est forgeable et rendrait l'anti-brute-force inopérant.
    trust_proxy_headers: bool = False

    # ── IA OpenRouter (`IA-01`, `IA-07`) ──────────────
    # Sans clé, les fonctions IA renvoient un message clair et le reste de
    # l'application fonctionne intégralement en saisie manuelle.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = ""

    # ── Export iCal (`PLAN-05`) ───────────────────────
    # Sans clé, le flux public n'est pas publié du tout — et le planning reste
    # consultable, modifiable et téléchargeable sous jeton.
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
    def ical_enabled(self) -> bool:
        """Vrai si le flux `.ics` public peut être servi (`PLAN-05`).

        Une clé trop courte vaut une clé absente : accepter `ICAL_SECRET=metric`
        publierait un an de planning derrière un mot de six lettres, et l'utilisateur
        croirait avoir posé une protection. Mieux vaut ne rien publier et le dire.
        """
        return len(self.ical_secret.strip()) >= ICAL_SECRET_MIN_LENGTH

    @property
    def storage_configured(self) -> bool:
        """Vrai si le stockage Nextcloud est renseigné."""
        return bool(self.nextcloud_url and self.nextcloud_username)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @model_validator(mode="after")
    def refuse_unsafe_production(self) -> Settings:
        """Refuse de démarrer en production avec une configuration dangereuse.

        Échouer au démarrage plutôt qu'à la première requête : une API en production
        avec le secret JWT de développement est une porte ouverte, et le seul moment où
        l'on regarde les journaux de démarrage est justement le déploiement.
        """
        if not self.is_production:
            return self

        problems: list[str] = []
        if self.jwt_secret == DEV_JWT_SECRET:
            problems.append("JWT_SECRET est resté sur la valeur de développement")
        if len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET fait moins de 32 caractères")
        if not self.auth_username:
            problems.append("AUTH_USERNAME est vide")
        if not self.auth_password_hash:
            problems.append("AUTH_PASSWORD_HASH est vide (voir « make hash-password »)")
        if not self.storage_configured:
            problems.append("le stockage Nextcloud n'est pas renseigné")

        if problems:
            raise ValueError(
                "Configuration de production incomplète : " + " ; ".join(problems) + "."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Réglages mémorisés — un seul chargement par processus."""
    return Settings()
