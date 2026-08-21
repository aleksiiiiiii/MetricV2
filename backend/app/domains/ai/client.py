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

import json
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import httpx2

#: Un appel vision sur un modèle gratuit met couramment dix à trente secondes. Le délai de
#: lecture est donc large — mais borné : au-delà, l'écran attendrait sans rien dire, et
#: `IA-07` promet que l'IA n'immobilise jamais l'application.
READ_TIMEOUT = 60.0

#: Tirage d'une **extraction** : lire une photo d'assiette, une capture d'import, une note
#: de séance. La même photo ne doit pas rendre 32 g de protéines puis 41 g selon l'humeur du
#: tirage, et c'est le défaut par lequel ce champ est arrivé dans le corps de la requête.
#:
#: **Ce n'est pas le réglage d'une conversation**, et c'est pourquoi il se nomme. Un
#: assistant à `0,1` rend dix réponses quasi identiques à dix questions voisines ; la route
#: assistant passe donc `temperature=None`, qui retire le champ (lot 7 du plan de coaching).
#:
#: **La garantie ne vaut que pour les modèles qui acceptent le champ.** Anthropic a retiré
#: `temperature`, `top_p` et `top_k` de son API sur la famille Claude 5 : une requête qui les
#: porte y est refusée en `400`. OpenRouter les filtre avant de router — mesuré le
#: 2026-08-16 sur `claude-opus-5` et `claude-sonnet-5`, avec et sans le champ, quatre
#: réponses normales. Le réglage est donc **sans effet** sur le modèle configuré aujourd'hui,
#: et la reproductibilité d'une extraction y repose sur la consigne seule. Il reste envoyé
#: parce qu'il sert la cascade gratuite, qui l'accepte.
#:
#: Mais `openrouter_base_url` est un réglage : le pointer sur l'API Anthropic ferait tomber
#: chaque appel en `400`, que `_read` traduirait en `ModelUnusableError` — donc en descente
#: silencieuse vers un modèle gratuit, sans rien afficher. Le jour où ce chemin s'ouvre, ce
#: champ se conditionne au modèle, et `supported_parameters` du catalogue le dit sans
#: qu'on ait à deviner les noms des modèles à venir.
EXTRACTION_TEMPERATURE = 0.1

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
        images: Sequence[str] = (),
        max_tokens: int = 900,
        temperature: float | None = EXTRACTION_TEMPERATURE,
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Interroge un modèle et rend son texte brut.

        L'extraction du JSON n'est **pas** faite ici : elle vit dans `extract.py`, et la
        cascade veut pouvoir distinguer « le modèle n'a pas répondu » de « le modèle a
        répondu quelque chose d'inexploitable ».
        """
        body = self.build_body(
            model,
            instruction=instruction,
            prompt=prompt,
            images=images,
            max_tokens=max_tokens,
            temperature=temperature,
            extra=extra,
        )

        try:
            response = await self._client.post("/chat/completions", json=body)
        except httpx2.HTTPError as exc:
            raise ModelUnusableError(f"{model} injoignable : {exc}") from exc
        return self._read(model, response)

    def build_body(
        self,
        model: str,
        *,
        instruction: str,
        prompt: str,
        images: Sequence[str] = (),
        max_tokens: int = 900,
        temperature: float | None = EXTRACTION_TEMPERATURE,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Le corps de la requête, séparé pour être vérifiable sans réseau.

        `temperature` à `None` **retire le champ** du corps au lieu de l'envoyer à zéro —
        ce qui n'est pas la même chose, et c'est toute la raison du paramètre : `0` demande
        le tirage le plus déterministe possible, l'absence laisse au modèle le sien. Voir la
        constante `EXTRACTION_TEMPERATURE` pour ce que chaque appelant a à décider.

        `extra` est fusionné **par-dessus** le corps rendu. Il existe pour les champs qui
        dépendent du fournisseur et non de la fonction appelante — `reasoning` chez
        OpenRouter, par exemple, qui n'a d'équivalent ni dans l'API d'OpenAI ni dans celle
        d'Anthropic. Aucun appel du dépôt ne s'en sert : c'est le jeu d'évaluation qui
        compare deux réglages du même modèle sans que le client ait à connaître lequel.

        Il écrase ce qu'il recouvre, délibérément. Il ne sait toujours pas *retirer* un
        champ (`{"temperature": None}` l'enverrait à `null`) — c'est précisément pourquoi
        le réglage devenu permanent est passé dans la signature, comme le disait déjà cette
        page.
        """
        # Le texte d'abord, puis les images **dans l'ordre reçu**. L'ordre porte du sens
        # dès qu'il y en a plusieurs : le résumé d'une séance vient avant ses paliers, et
        # une consigne qui parle de « la première capture » doit désigner la même que
        # celle que l'appelant a mise en tête.
        content: list[dict[str, Any]] | str = prompt
        if images:
            content = [
                {"type": "text", "text": prompt},
                *({"type": "image_url", "image_url": {"url": url}} for url in images),
            ]

        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": content},
            ],
            "max_tokens": max_tokens,
            # **Le mode JSON du fournisseur**, et il a été ajouté sur constat.
            #
            # Les modèles gratuits du catalogue sont pour moitié des modèles de
            # raisonnement. Ils écrivent parfois leur réflexion en prose — « The user is
            # asking… » — et se font tronquer par `max_tokens` **avant d'avoir produit la
            # moindre accolade**. Relevé sur `nemotron-3-ultra` : 3 788 caractères de
            # raisonnement, aucun JSON, une tentative brûlée pour rien. Comme le défaut est
            # intermittent, il ne se voit qu'en production, un jour où les autres modèles
            # sont au quota.
            #
            # La consigne demandait déjà « uniquement un objet JSON » ; ce champ le dit au
            # fournisseur plutôt qu'au modèle. Vérifié sur les six candidats du jour :
            # cinq répondus, aucun refus — le sixième était au quota, pas en erreur.
            "response_format": {"type": "json_object"},
        }
        if temperature is not None:
            # Absent quand l'appelant n'en veut pas. Le champ n'est pas neutre : envoyé à
            # `0.1` sur une conversation, il rend dix réponses quasi identiques à dix
            # questions voisines.
            body["temperature"] = temperature
        return body | (extra or {})

    async def stream_complete(
        self,
        model: str,
        *,
        instruction: str,
        prompt: str,
        max_tokens: int = 900,
        temperature: float | None = EXTRACTION_TEMPERATURE,
        extra: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Interroge un modèle et rend son texte **par morceaux**, dans l'ordre d'arrivée.

        Même corps que `complete`, plus `stream: true`. Les erreurs sont les mêmes et
        portent le même sens : la cascade décide de la suite sans savoir si l'appel était
        diffusé ou non.

        **Ce qui sort est le texte brut du modèle**, pas la réponse de l'assistant : c'est
        du JSON qui s'écrit, accolades comprises, et parfois un monologue de raisonnement
        avant. Le tri est le travail de `ReplyStream`, en aval.

        Sans image : un appel vision ne se diffuse pas ici parce que rien n'en a besoin —
        une estimation d'assiette s'affiche d'un coup, et la retenir dans le client évite
        un chemin qui ne serait jamais éprouvé.
        """
        body = self.build_body(
            model,
            instruction=instruction,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            extra=extra,
        )
        body["stream"] = True

        try:
            async with self._client.stream("POST", "/chat/completions", json=body) as response:
                if response.status_code >= 400:
                    # Le corps n'a pas encore été lu : sans ce `aread`, le message
                    # d'erreur du fournisseur serait perdu et tout deviendrait « HTTP 400 ».
                    await response.aread()
                    self._raise_for(model, response)

                async for line in response.aiter_lines():
                    piece = _read_stream_line(model, line)
                    if piece is None:
                        return
                    if piece:
                        yield piece
        except httpx2.HTTPError as exc:
            raise ModelUnusableError(f"{model} injoignable : {exc}") from exc

    @staticmethod
    def _raise_for(model: str, response: httpx2.Response) -> None:
        """Traduit un statut d'erreur en refus nommé. Ne rend jamais la main sans lever."""
        if response.status_code == 429:
            raise ModelQuotaError(f"{model} : quota atteint")
        raise ModelUnusableError(f"{model} : HTTP {response.status_code}")

    @staticmethod
    def _read(model: str, response: httpx2.Response) -> str:
        """Traduit une réponse HTTP en texte, ou en refus nommé."""
        if response.status_code == 429:
            raise ModelQuotaError(f"{model} : quota atteint")
        if response.status_code >= 400:
            raise ModelUnusableError(f"{model} : HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ModelUnusableError(f"{model} : réponse non-JSON") from exc

        return _read_content(model, payload)


def _read_stream_line(model: str, line: str) -> str | None:
    """Un morceau de texte, `""` si la ligne n'en porte pas, `None` à la fin du flux.

    Trois formes traversent un `text/event-stream` d'OpenRouter et deux ne disent rien :
    les lignes vides qui séparent les événements, et les commentaires `: OPENROUTER
    PROCESSING` qu'il envoie pour tenir la connexion ouverte pendant qu'un modèle démarre.
    Les prendre pour des données ferait échouer l'analyse à intervalles réguliers.

    Un `error` **dans** le flux garde le sens qu'il a ailleurs (`IA-03`) : un quota se
    réessaie sur le modèle suivant, une panne aussi mais sans le même conseil à l'écran.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith(":"):
        return ""
    if not stripped.startswith("data:"):
        return ""

    data = stripped[len("data:") :].strip()
    if data == "[DONE]":
        return None

    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        # Une ligne illisible au milieu d'un flux n'est pas une panne du modèle : on la
        # saute. Ce qui compte est ce qui arrive à écrire, et la relecture finale tranchera.
        return ""

    if not isinstance(payload, dict):
        return ""

    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "")
        if error.get("code") == 429 or "rate limit" in message.lower():
            raise ModelQuotaError(f"{model} : {message or 'quota atteint'}")
        raise ModelUnusableError(f"{model} : {message or 'erreur du fournisseur'}")

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    delta = first.get("delta") if isinstance(first, dict) else None
    content = delta.get("content") if isinstance(delta, dict) else None
    return content if isinstance(content, str) else ""


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
