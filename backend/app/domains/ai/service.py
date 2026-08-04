"""Cascade multi-modèles et cycle de vie de la couche IA (`IA-02` → `IA-04`, `IA-07`).

Ce module est le seul endroit du projet qui décide **quel** modèle interroger et **quand
renoncer**. Les domaines qui s'en servent — nutrition, import — lui passent une consigne et
reçoivent un dictionnaire ; ils ne savent rien des modèles, des quotas ni des cascades.

Trois règles y sont écrites une fois pour toutes.

**Le catalogue gratuit est relu, pas codé.** Les modèles à coût nul d'OpenRouter changent
de semaine en semaine : une liste écrite en dur serait fausse au premier mois. Elle est
donc découverte, filtrée, classée, et **mémorisée une heure** (`IA-02`) — assez pour qu'un
écran ne la redemande pas à chaque photo, assez peu pour suivre le catalogue réel.

**Une image ne va qu'aux modèles vision** (`IA-04`). Envoyer une capture à un modèle qui ne
lit que du texte produit soit un refus, soit — pire — une réponse inventée à partir du seul
énoncé. La cascade n'y descend jamais.

**La cascade est bornée.** Trois tentatives, pas plus. Un utilisateur qui photographie son
assiette n'attend pas trois minutes qu'une file de douze modèles gratuits ait fini de
saturer ; il préfère un refus clair et sa saisie manuelle, ce que `IA-07` promet.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from app.config import Settings
from app.core.exceptions import AiQuotaError, AiUnavailableError
from app.domains.ai.client import (
    ModelInfo,
    ModelQuotaError,
    ModelUnusableError,
    OpenRouterClient,
)
from app.domains.ai.extract import first_json_object

#: Durée de mémorisation du catalogue (`IA-02`).
CATALOGUE_TTL = 3600.0

#: Modèles interrogés au maximum pour une même demande.
MAX_ATTEMPTS = 3


class ModelCatalogue:
    """Modèles gratuits découverts, filtrés, classés et mémorisés une heure (`IA-02`).

    L'horloge est **monotone** et non l'heure du mur : un changement d'heure ou une
    resynchronisation NTP ne doit pas rendre le cache éternel ni le périmer d'un coup.
    """

    def __init__(
        self,
        client: OpenRouterClient,
        *,
        ttl: float = CATALOGUE_TTL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._ttl = ttl
        self._clock = clock
        self._models: list[ModelInfo] = []
        self._fetched_at: float | None = None
        # Deux écrans qui déclenchent une analyse en même temps ne doivent pas provoquer
        # deux découvertes : la seconde attend la première et lit son résultat.
        self._lock = asyncio.Lock()

    def _is_fresh(self) -> bool:
        """Fraîcheur du cache, en méthode et non en propriété.

        La double vérification autour du verrou en dépend : une propriété serait tenue
        pour constante d'une ligne à l'autre — par le vérificateur de types comme par le
        lecteur — alors que sa valeur peut précisément changer pendant l'attente.
        """
        return self._fetched_at is not None and self._clock() - self._fetched_at < self._ttl

    @property
    def fresh(self) -> bool:
        return self._is_fresh()

    async def all(self) -> list[ModelInfo]:
        """Catalogue courant, relu s'il a plus d'une heure."""
        if self._is_fresh():
            return self._models

        async with self._lock:
            if self._is_fresh():  # une autre tâche vient de le rafraîchir
                return self._models
            self._models = await self._client.free_models()
            self._fetched_at = self._clock()
            return self._models

    async def usable(self, *, vision: bool) -> list[ModelInfo]:
        """Modèles retenus pour une demande donnée (`IA-04`)."""
        models = await self.all()
        return [model for model in models if model.vision] if vision else models


class AiService:
    """Interroge les modèles jusqu'à obtenir un objet JSON exploitable."""

    def __init__(
        self,
        client: OpenRouterClient,
        catalogue: ModelCatalogue,
        *,
        preferred: str = "",
    ) -> None:
        self._client = client
        self._catalogue = catalogue
        self._preferred = preferred.strip()

    async def candidates(self, *, vision: bool) -> list[ModelInfo]:
        """Modèles à tenter, dans l'ordre, le modèle configuré en tête (`IA-01`).

        Un catalogue injoignable ne fait pas échouer l'appel quand un modèle est
        configuré : c'est justement le cas où ce réglage sert à quelque chose.
        """
        try:
            listed = await self._catalogue.usable(vision=vision)
        except (ModelQuotaError, ModelUnusableError):
            listed = []

        if not self._preferred:
            return listed

        known = next((model for model in listed if model.id == self._preferred), None)
        if known is not None:
            return [known, *(model for model in listed if model.id != self._preferred)]

        # Modèle configuré absent du catalogue gratuit : soit il est payant — auquel cas
        # l'utilisateur l'a choisi en connaissance de cause — soit le catalogue n'a pas
        # répondu. Pour un appel sur image, on ne peut pas savoir s'il lit les images ;
        # on le tente quand même, son refus coûte un aller-retour et la cascade suit.
        declared = ModelInfo(
            id=self._preferred,
            name=self._preferred,
            context_length=0,
            vision=vision,
            params_b=None,
        )
        return [declared, *listed]

    async def ask_json(
        self,
        *,
        instruction: str,
        prompt: str,
        image_url: str | None = None,
        max_tokens: int = 900,
    ) -> dict[str, Any]:
        """Rend le premier objet JSON exploitable obtenu, ou lève (`IA-03`).

        `AiQuotaError` quand **tout** ce qui a été tenté a répondu « quota » : cela se
        résout en attendant. `AiUnavailableError` sinon : attendre n'y changera rien. Les
        deux portent un code distinct (`API-07`), et l'écran n'a pas le même conseil à
        donner.
        """
        models = await self.candidates(vision=image_url is not None)
        if not models:
            raise AiUnavailableError(
                "Aucun modèle gratuit n'est disponible pour l'instant. "
                "La saisie manuelle reste possible."
            )

        quota_only = True
        attempted = 0

        for model in models[:MAX_ATTEMPTS]:
            attempted += 1
            try:
                raw = await self._client.complete(
                    model.id,
                    instruction=instruction,
                    prompt=prompt,
                    image_url=image_url,
                    max_tokens=max_tokens,
                )
            except ModelQuotaError:
                continue
            except ModelUnusableError:
                quota_only = False
                continue

            parsed = first_json_object(raw)
            if parsed is not None:
                return parsed
            # Réponse reçue mais inexploitable — bavarde sans JSON, ou tronquée en plein
            # objet. Ce n'est pas une question de quota : insister plus tard ne changerait
            # rien à ce que ce modèle sait faire.
            quota_only = False

        if quota_only and attempted:
            raise AiQuotaError
        raise AiUnavailableError(
            "Les modèles disponibles n'ont rien rendu d'exploitable. "
            "Saisis les valeurs à la main, ou réessaie."
        )


class AiProvider:
    """Détient le client OpenRouter et son catalogue, pour toute la vie du processus.

    Même forme que `StorageProvider`, et pour la même raison : le client porte un pool de
    connexions, il doit naître dans la boucle d'événements et être relâché à l'arrêt. Sans
    clé, le fournisseur reste **inerte** — l'application démarre, tous les écrans
    fonctionnent, et seule une demande d'assistance dit ce qui manque (`IA-07`).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: OpenRouterClient | None = None
        self._catalogue: ModelCatalogue | None = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @property
    def message(self) -> str:
        """Ce qu'il y a à dire à l'écran sur l'état de l'assistance."""
        if self.enabled:
            return "L'assistance IA est disponible. Ce qu'elle propose reste à valider."
        return (
            "Aucune clé OpenRouter n'est configurée : les estimations automatiques sont "
            "hors service. Tout se saisit à la main, sans rien perdre."
        )

    async def start(self) -> None:
        if not self._settings.ai_enabled:
            return
        self._client = OpenRouterClient(
            api_key=self._settings.openrouter_api_key,
            base_url=self._settings.openrouter_base_url,
        )
        self._catalogue = ModelCatalogue(self._client)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None
        self._catalogue = None

    @property
    def service(self) -> AiService:
        """Service prêt à l'emploi, ou `AiUnavailableError` si aucune clé (`IA-07`)."""
        if self._client is None or self._catalogue is None:
            raise AiUnavailableError(self.message)
        return AiService(self._client, self._catalogue, preferred=self._settings.openrouter_model)

    @property
    def catalogue(self) -> ModelCatalogue:
        if self._catalogue is None:
            raise AiUnavailableError(self.message)
        return self._catalogue

    def use(self, client: OpenRouterClient, *, catalogue: ModelCatalogue | None = None) -> None:
        """Injecte un client déjà construit — utilisé par les tests."""
        self._client = client
        self._catalogue = catalogue or ModelCatalogue(client)
