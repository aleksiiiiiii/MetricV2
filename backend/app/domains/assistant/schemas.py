"""Formes échangées par l'assistant (`IA-09` → `IA-12`).

Trois familles, et leur séparation porte les garanties du lot :

* **la conversation** (`ChatRequest`, `ChatReply`) — elle ne désigne rien dans aucun
  fichier, et n'en crée aucun. Le fil vit dans l'écran ; le serveur ne se souvient de rien
  entre deux questions, c'est le client qui lui rend l'historique.
* **la note proposée** (`ProposedMemory`) — ce que le modèle suggère de retenir et que
  **personne n'a encore validé** (`IA-10`). Pas de jeton, pas d'identifiant : elle ne
  désigne aucune ligne, puisqu'il n'en existe encore aucune. Même forme que
  `ProposedSession` et `ProposedGoal` — le projet n'a qu'une façon de dire « pas encore
  validé ».
* **la note écrite** (`MemoryEntry`) — ce que le client reçoit, avec `id` et `token`.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domains.assistant.models import MAX_CONTENT, MAX_NOTE, MAX_TITLE, MAX_TOPIC

#: Longueur d'une question. Généreuse — on décrit parfois une situation en un paragraphe —
#: mais bornée : au-delà, ce n'est plus une question, et le coût de l'appel suit.
MAX_QUESTION = 1000

#: Tours d'historique renvoyés au modèle.
#:
#: Six échanges, soit douze messages. Assez pour qu'un « et pourquoi ? » ait un sens, assez
#: peu pour que la consigne ne double pas de taille au dixième tour — le condensé, lui, est
#: renvoyé **entier** à chaque fois, parce qu'il est recalculé et que le modèle doit
#: répondre sur les chiffres du moment, pas sur ceux d'il y a dix minutes.
MAX_HISTORY = 12

#: Notes proposées au maximum en une réponse. Une conversation ne révèle pas cinq faits
#: durables d'un coup ; au-delà, le modèle a compris qu'on lui demandait de résumer.
MAX_PROPOSED = 3


class Message(BaseModel):
    """Un tour de conversation, tel que l'écran le renvoie."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_QUESTION)


class ChatRequest(BaseModel):
    """Une question, dans un fil.

    L'historique n'est plus rendu par le client : il est **lu dans le fil**. Un client
    pouvait envoyer ce qu'il voulait comme passé, ce qui était sans conséquence tant que
    rien ne s'écrivait — ça n'en a plus dès lors qu'une réponse peut agir sur les données.
    """

    #: Un champ inconnu **échoue** au lieu d'être ignoré. C'est la seule requête du
    #: projet qui déclenche des écritures : si le client en envoie un que le serveur ne
    #: connaît pas, les deux ne parlent pas du même contrat, et le découvrir tôt vaut
    #: mieux que de l'ignorer en silence — c'est ainsi qu'un `history` fabriqué par un
    #: client resterait sans effet *sans qu'on sache* qu'il a été envoyé.
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION)
    #: Le fil où poser la question. Absent, un fil est ouvert et son identifiant est rendu
    #: avec la réponse.
    thread_id: str | None = Field(default=None, max_length=32)


class ProposedMemory(BaseModel):
    """Ce que le modèle suggère de retenir. **Rien n'est écrit** (`IA-10`)."""

    topic: str = Field(max_length=MAX_TOPIC)
    note: str = Field(min_length=1, max_length=MAX_NOTE)


class ChatReply(BaseModel):
    """Ce que la conversation rend."""

    #: Le fil, ouvert ou poursuivi. L'écran s'en sert pour la question suivante.
    thread_id: str
    title: str = ""
    reply: str
    #: Ce qui mérite d'être retenu, en attente de validation.
    remember: list[ProposedMemory] = Field(default_factory=list)
    #: Le condensé factuel réellement envoyé au modèle, ligne par ligne (`IA-09`).
    #:
    #: Publié pour la même raison qu'à `GOAL-02`, et elle vaut ici avec plus de force :
    #: une conversation invite à tout envoyer « au cas où ». L'afficher est ce qui rend la
    #: promesse vérifiable plutôt que déclarative.
    context: list[str] = Field(default_factory=list)


class MemoryPayload(BaseModel):
    """Une note à écrire ou à corriger (`IA-11`)."""

    topic: str = Field(default="autre", max_length=MAX_TOPIC)
    note: str = Field(min_length=1, max_length=MAX_NOTE)


class MemoryEntry(BaseModel):
    """Une note retenue, telle que le client la reçoit."""

    id: int
    token: str
    memory_id: str
    created: dt.date | None = None
    topic: str
    note: str
    #: `ai` ou `manual` — d'où vient la ligne, pas ce qu'elle vaut.
    source: str


class AssistantView(BaseModel):
    """Tout l'écran en une requête.

    Le carnet et les sujets suggérés arrivent ensemble : l'écran ne sait rien afficher
    tant qu'il n'a pas les deux, et les demander séparément coûterait deux allers-retours.
    """

    memories: list[MemoryEntry] = Field(default_factory=list)
    #: Sujets les plus fréquents, offerts en un appui. La colonne reste libre.
    topics: list[str] = Field(default_factory=list)
    #: Aujourd'hui **selon le serveur** : l'écran ne calcule pas sa propre date.
    today: dt.date


# ── Les fils de discussion ────────────────────────────


class ThreadSummary(BaseModel):
    """Un fil dans la liste. Sans ses messages — la liste s'affiche sans les charger."""

    thread_id: str
    title: str
    created: dt.datetime | None = None
    #: Bougé à chaque message : c'est sur lui que la liste est triée, pour qu'un fil
    #: rouvert remonte.
    updated: dt.datetime | None = None
    messages: int = 0


class ThreadMessage(BaseModel):
    """Un tour de conversation, tel qu'il a été écrit."""

    seq: int
    role: Literal["user", "assistant"]
    content: str = Field(max_length=MAX_CONTENT)
    created: dt.datetime | None = None


class ThreadDetail(BaseModel):
    """Un fil et tout son contenu."""

    thread_id: str
    title: str = Field(max_length=MAX_TITLE)
    created: dt.datetime | None = None
    updated: dt.datetime | None = None
    messages: list[ThreadMessage] = Field(default_factory=list)


class ThreadList(BaseModel):
    """Les fils, du plus récemment actif au plus ancien."""

    threads: list[ThreadSummary] = Field(default_factory=list)
