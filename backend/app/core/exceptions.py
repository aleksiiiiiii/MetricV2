"""Catalogue des erreurs métier (`API-07`).

Toute erreur exposée par l'API descend de `MetricError` et porte trois choses :

* un **code machine stable**, que le client mappe vers ses propres formulations ;
* un **message français** affichable en l'état ;
* un **statut HTTP**.

Le client ne parse jamais de texte : reformuler un message ne casse rien, changer un
code est une rupture de contrat. C'est la raison d'être de ce module — un seul endroit
où lire la liste des codes, plutôt qu'un `raise HTTPException(400, "…")` par fichier.

`detail` porte le contexte technique. Il est journalisé, jamais renvoyé : il contient
des chemins, des statuts amont et des noms de fichiers qui n'aident pas l'utilisateur.
"""

from __future__ import annotations


class MetricError(Exception):
    """Base de toutes les erreurs métier."""

    code = "internal_error"
    status_code = 500
    message = "Une erreur inattendue s'est produite."

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or type(self).message
        self.detail = detail
        self.headers = headers
        super().__init__(self.message)

    def __str__(self) -> str:
        return f"{self.message} ({self.detail})" if self.detail else self.message


# ── Authentification ──────────────────────────────────


class InvalidCredentialsError(MetricError):
    """Identifiant ou mot de passe faux (`AUTH-01`).

    Message volontairement indistinct : dire *lequel* des deux champs est en cause
    aiderait surtout quelqu'un qui cherche à devenir l'identifiant.
    """

    code = "invalid_credentials"
    status_code = 401
    message = "Identifiant ou mot de passe incorrect."


class SessionExpiredError(MetricError):
    """Jeton absent, expiré, mal signé ou illisible (`AUTH-06`).

    Un seul code pour tous ces cas : côté client la conduite à tenir est la même —
    purger le jeton local et redemander la connexion.
    """

    code = "session_expired"
    status_code = 401
    message = "Session expirée. Reconnecte-toi."


class TooManyAttemptsError(MetricError):
    """Trop d'échecs de connexion depuis la même adresse (`AUTH-04`)."""

    code = "too_many_attempts"
    status_code = 429
    message = "Trop de tentatives de connexion. Réessaie dans un instant."

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            f"Trop de tentatives de connexion. Réessaie dans {retry_after} secondes.",
            detail=f"retry_after={retry_after}",
            headers={"Retry-After": str(retry_after)},
        )
        self.retry_after = retry_after


class AuthNotConfiguredError(MetricError):
    """Aucun hash de mot de passe en configuration.

    Sans cela, l'API refuse toute connexion — plutôt que d'être ouverte à tous, ce qui
    serait le comportement d'un `if hash == password` naïf sur une valeur vide.
    """

    code = "auth_not_configured"
    status_code = 503
    message = (
        "L'authentification n'est pas configurée : génère un hash avec "
        "« make hash-password » et renseigne AUTH_PASSWORD_HASH."
    )


# ── Requête ───────────────────────────────────────────


class ValidationFailedError(MetricError):
    """Saisie aberrante rejetée avant le stockage (`API-06`)."""

    code = "validation_error"
    status_code = 422
    message = "Les données envoyées sont invalides."


class NotFoundError(MetricError):
    """Ressource métier inexistante."""

    code = "not_found"
    status_code = 404
    message = "Cette ressource n'existe pas."


# ── Couche IA (`IA-03`, `IA-07`) ──────────────────────
# Déclarés ici pour que le catalogue soit complet et lisible d'un seul endroit ;
# la couche IA qui les lève est construite au lot L12.


class AiUnavailableError(MetricError):
    """Aucun modèle exploitable, ou aucune clé configurée (`IA-07`)."""

    code = "ai_unavailable"
    status_code = 503
    message = "L'assistance IA est indisponible. La saisie manuelle reste possible."


class AiQuotaError(MetricError):
    """Tous les modèles gratuits ont répondu `429` (`IA-03`)."""

    code = "ai_quota"
    status_code = 503
    message = "Quota des modèles gratuits épuisé. Réessaie plus tard."


class AiUnreadableError(MetricError):
    """Le modèle a répondu, mais l'image ne portait pas ce qu'on y cherchait (`IMP-06`).

    Distinct de `ai_unavailable` : la chaîne a fonctionné de bout en bout, c'est la
    **capture** qui ne convient pas. La conduite à tenir n'est donc pas d'attendre mais de
    refaire la capture — ou de saisir à la main, ce qui reste toujours possible.

    `422` et non `503` : rien n'est en panne, l'entrée ne convient pas.
    """

    code = "ai_unreadable"
    status_code = 422
    message = (
        "Cette capture n'a pas pu être lue. Réessaie avec une capture entière de l'écran "
        "de résumé, ou saisis les valeurs à la main."
    )
