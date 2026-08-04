"""Client OpenRouter, unique pour toutes les fonctions IA (`IA-01`).

OpenRouter expose l'API de complétion d'OpenAI : un seul `POST /chat/completions` sert
l'analyse d'un repas, l'import d'une capture, et demain le planning et le bilan
hebdomadaire. Un client par fonction aurait multiplié les réglages de délai, les en-têtes
et les façons de lire une réponse.

Deux distinctions structurent tout le module, et elles portent la valeur de `IA-03` :

* **`ModelQuotaError` — le modèle est saturé.** `429`, ou une réponse dont le message dit
  la limite atteinte. Cela se résout **en attendant**, ou en changeant de modèle.
* **`ModelUnusableError` — le modèle n'a rien donné d'exploitable.** Panne, réponse vide,
  contenu que l'on ne sait pas lire. Attendre n'y changera rien.

Les deux mènent à essayer le modèle suivant, mais l'utilisateur n'a pas la même conduite à
tenir quand tout a échoué — d'où deux exceptions, et non un booléen dans une seule.

Comme le client WebDAV, celui-ci accepte un **transport injectable** : la batterie de tests
scénarise un `429` en cascade ou un JSON tronqué sans toucher au vrai service.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import httpx2

#: Un appel vision sur un modèle gratuit met couramment dix à trente secondes. Le délai de
#: lecture est donc large — mais borné : au-delà, l'écran attendrait sans rien dire, et
#: `IA-07` promet que l'IA n'immobilise jamais l'application.
READ_TIMEOUT = 60.0

#: Formes de « taille » lisibles dans un identifiant de modèle : `…-70b-…`, `…-27b`, `8x7b`.
_PARAMS = re.compile(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)\s*b(?![a-z0-9])", re.IGNORECASE)

#: Familles qui ne répondent pas à une consigne : modération, plongements, synthèse vocale.
#: Elles apparaissent dans le catalogue gratuit et échoueraient une par une dans la
#: cascade, en consommant du temps à chaque fois.
_EXCLUDED = ("embed", "moderation", "guard", "rerank", "tts", "whisper", "stt", "transcribe")


class ModelQuotaError(Exception):
    """Modèle saturé — `429`, ou limite annoncée dans le corps de la réponse."""


class ModelUnusableError(Exception):
    """Modèle en panne, muet, ou dont la réponse n'est pas exploitable."""


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Un modèle du catalogue OpenRouter, réduit à ce dont la cascade a besoin."""

    id: str
    name: str
    context_length: int
    #: Accepte une image en entrée (`IA-04`).
    vision: bool
    #: Milliards de paramètres, lus dans l'identifiant. `None` quand il ne les annonce pas.
    params_b: float | None

    @property
    def rank(self) -> tuple[float, int, str]:
        """Clé de classement : taille, puis fenêtre de contexte, puis identifiant.

        Les deux premières sont des **approximations assumées** — OpenRouter ne publie pas
        le nombre de paramètres, et l'identifiant ne le porte pas toujours. Un modèle qui
        se tait sur sa taille passe après ceux qui l'annoncent, sans être écarté : c'est
        un ordre de préférence, pas un filtre. L'identifiant final rend le tri **stable**,
        donc la cascade reproductible d'un appel à l'autre.
        """
        return (-(self.params_b or 0.0), -self.context_length, self.id)


def _read_params(identifier: str) -> float | None:
    """Taille annoncée dans l'identifiant. `8x7b` compte pour 7, pas pour 56."""
    found = _PARAMS.findall(identifier)
    return max(float(value) for value in found) if found else None


def _is_free(pricing: dict[str, Any]) -> bool:
    """Vrai quand jeton d'entrée **et** de sortie coûtent exactement zéro.

    Les prix arrivent en chaînes (`"0"`, `"0.00000015"`) : c'est la forme du fournisseur,
    et les comparer en flottant évite de dépendre du nombre de zéros écrits.

    **Un prix négatif n'est pas un prix nul.** `openrouter/auto` annonce `"-1"`, qui veut
    dire « variable, décidé par le routage » : il facture le tarif du modèle vers lequel il
    route. Un test « pas strictement positif » le faisait entrer dans le catalogue gratuit,
    et la cascade aurait fini par y descendre — en facturant sans l'avoir dit.

    Le cas n'a été trouvé qu'en interrogeant le vrai catalogue : aucune entrée simulée
    n'aurait eu l'idée d'un prix négatif.
    """
    for key in ("prompt", "completion"):
        try:
            if float(pricing.get(key, "1")) != 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def parse_models(payload: dict[str, Any]) -> list[ModelInfo]:
    """Lit le catalogue publié par OpenRouter et n'en garde que les modèles utilisables.

    Filtrage en trois temps (`IA-02`) : coût nul, capable de rendre du texte, et pas d'une
    famille qui ne suit pas de consigne. Une entrée mal formée est **ignorée**, jamais
    fatale — le catalogue est un fichier distant que personne ici ne contrôle.
    """
    models: list[ModelInfo] = []

    for entry in payload.get("data", []):
        if not isinstance(entry, dict):
            continue
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not identifier:
            continue
        if not _is_free(entry.get("pricing") or {}):
            continue

        lowered = identifier.lower()
        if any(word in lowered for word in _EXCLUDED):
            continue

        architecture = entry.get("architecture") or {}
        inputs = architecture.get("input_modalities") or []
        outputs = architecture.get("output_modalities") or ["text"]
        # **Du texte, et rien d'autre.** Un modèle qui rend aussi de l'audio ou des images
        # est un générateur, pas un lecteur de consigne : `google/lyria-3-*` annonce
        # `["text", "audio"]` et compose de la musique. Un test « text est parmi les
        # sorties » le laissait entrer — trouvé sur le vrai catalogue, pas en simulation.
        if set(outputs) != {"text"}:
            continue

        context = entry.get("context_length")
        models.append(
            ModelInfo(
                id=identifier,
                name=str(entry.get("name") or identifier),
                context_length=int(context) if isinstance(context, (int, float)) else 0,
                vision="image" in inputs,
                params_b=_read_params(identifier),
            )
        )

    models.sort(key=lambda model: model.rank)
    return models


class OpenRouterClient:
    """Accès HTTP à OpenRouter. Ne connaît ni repas, ni course, ni cascade."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx2.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                # OpenRouter attribue les appels à une application par ces deux en-têtes.
                # Les renseigner nous identifie dans ses classements et, pour les modèles
                # gratuits, dans ses quotas — sans quoi nous partageons ceux de personne.
                "HTTP-Referer": "https://github.com/aleksi/metric",
                "X-Title": "Metric",
            },
            timeout=httpx2.Timeout(connect=10.0, read=READ_TIMEOUT, write=30.0, pool=10.0),
            limits=httpx2.Limits(max_connections=4, max_keepalive_connections=2),
            follow_redirects=True,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> OpenRouterClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ── Catalogue (`IA-02`) ───────────────────────────

    async def free_models(self) -> list[ModelInfo]:
        """Modèles à coût nul, filtrés et classés."""
        try:
            response = await self._client.get("/models")
        except httpx2.HTTPError as exc:
            raise ModelUnusableError(f"catalogue injoignable : {exc}") from exc

        if response.status_code == 429:
            raise ModelQuotaError("catalogue : quota atteint")
        if response.status_code >= 400:
            raise ModelUnusableError(f"catalogue : HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ModelUnusableError("catalogue illisible") from exc
        if not isinstance(payload, dict):
            raise ModelUnusableError("catalogue de forme inattendue")

        return parse_models(payload)

    # ── Complétion (`IA-01`) ──────────────────────────

    async def complete(
        self,
        model: str,
        *,
        instruction: str,
        prompt: str,
        image_url: str | None = None,
        max_tokens: int = 900,
    ) -> str:
        """Interroge un modèle et rend son texte brut.

        L'extraction du JSON n'est **pas** faite ici : elle vit dans `extract.py`, et la
        cascade veut pouvoir distinguer « le modèle n'a pas répondu » de « le modèle a
        répondu quelque chose d'inexploitable ».
        """
        content: list[dict[str, Any]] | str = prompt
        if image_url is not None:
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]

        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": content},
            ],
            # Une estimation doit être reproductible : la même photo ne doit pas rendre
            # 32 g de protéines puis 41 g selon l'humeur du tirage.
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }

        try:
            response = await self._client.post("/chat/completions", json=body)
        except httpx2.HTTPError as exc:
            raise ModelUnusableError(f"{model} injoignable : {exc}") from exc

        if response.status_code == 429:
            raise ModelQuotaError(f"{model} : quota atteint")
        if response.status_code >= 400:
            raise ModelUnusableError(f"{model} : HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ModelUnusableError(f"{model} : réponse non-JSON") from exc

        return _read_content(model, payload)


def _read_content(model: str, payload: Any) -> str:
    """Extrait le texte d'une réponse de complétion.

    Un `200` porteur d'une erreur est un cas **réel** chez OpenRouter : le routage a
    réussi, le fournisseur en aval a refusé. Le lire ici évite de traiter une saturation
    comme une panne définitive.
    """
    if not isinstance(payload, dict):
        raise ModelUnusableError(f"{model} : réponse de forme inattendue")

    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "")
        code = error.get("code")
        if code == 429 or "rate limit" in message.lower() or "quota" in message.lower():
            raise ModelQuotaError(f"{model} : {message or 'quota atteint'}")
        raise ModelUnusableError(f"{model} : {message or 'erreur du fournisseur'}")

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelUnusableError(f"{model} : aucune réponse")

    first = choices[0]
    message_body = first.get("message") if isinstance(first, dict) else None
    text = message_body.get("content") if isinstance(message_body, dict) else None

    if not isinstance(text, str) or not text.strip():
        # Certains modèles à raisonnement placent tout dans `reasoning` et laissent
        # `content` vide quand la limite de jetons tombe pendant le monologue.
        raise ModelUnusableError(f"{model} : réponse vide")
    return text
