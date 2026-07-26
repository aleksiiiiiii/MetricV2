"""Erreurs de stockage typées (`STO-09`, `API-07`).

Chaque échec porte un **code machine stable** en plus du message français. Le client
mappe les codes vers ses propres formulations : il ne parse jamais du texte.

Règle de traduction : une panne du stockage n'est jamais une 500 brute. Ce qui vient
d'en face devient `502`, ce qui relève de l'indisponibilité ou de la configuration
devient `503`, un conflit d'écriture devient `409`.
"""

from __future__ import annotations


class StorageError(Exception):
    """Base de toutes les erreurs de la couche stockage."""

    code = "storage_error"
    status_code = 502
    message = "Le stockage a renvoyé une réponse inattendue."

    def __init__(self, message: str | None = None, *, detail: str | None = None) -> None:
        self.message = message or type(self).message
        self.detail = detail
        super().__init__(self.message)

    def __str__(self) -> str:
        return f"{self.message} ({self.detail})" if self.detail else self.message


class StorageUnavailableError(StorageError):
    """Nextcloud injoignable, saturé, ou trop lent."""

    code = "storage_unavailable"
    status_code = 503
    message = "Le stockage est momentanément injoignable. Réessaie dans un instant."


class StorageNotConfiguredError(StorageError):
    """Aucune URL ni identifiant Nextcloud dans la configuration."""

    code = "storage_not_configured"
    status_code = 503
    message = "Le stockage n'est pas configuré : renseigne Nextcloud dans le fichier .env."


class StorageAuthFailedError(StorageError):
    """Identifiants Nextcloud refusés.

    Volontairement laconique côté message : on ne dit pas *lequel* des deux champs est
    en cause, et on ne renvoie jamais l'identifiant utilisé.
    """

    code = "storage_auth_failed"
    status_code = 503
    message = "Le stockage a refusé les identifiants. Vérifie la configuration Nextcloud."


class StorageNotFoundError(StorageError):
    """Chemin absent côté Nextcloud."""

    code = "storage_not_found"
    status_code = 404
    message = "La ressource demandée n'existe pas dans le stockage."


class StorageConflictError(StorageError):
    """Garde anti-conflit multi-appareils (`STO-05`).

    Levée quand la ligne visée, ou le fichier qui la contient, a changé depuis la
    lecture. C'est le cas normal quand l'app est ouverte sur deux appareils : on refuse
    plutôt que d'écraser la mauvaise ligne.
    """

    code = "conflict"
    status_code = 409
    message = (
        "Cette donnée a été modifiée ailleurs depuis son affichage. Recharge avant de réessayer."
    )


class StorageSchemaError(StorageError):
    """Fichier CSV illisible : en-tête absent, colonnes inattendues, valeur invalide."""

    code = "storage_schema_error"
    status_code = 502
    message = "Un fichier de données est illisible."
