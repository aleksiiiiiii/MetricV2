"""Consigne et relecture de la lecture du jour.

Module **pur**, comme `goals/weekly.py` et `assistant/conversation.py` : une consigne à
assembler, une réponse à relire. Il ne lit aucun fichier, ne connaît ni l'horloge ni le
modèle, et n'écrit rien. Chaque cas se vérifie sur des valeurs fixes, sans monter
d'application.

## Une carte, pas un bilan

Le bilan hebdomadaire demande trois rubriques — progrès, décrochages, action — parce qu'on
le relit dans six mois et qu'elles ne se lisent pas de la même façon. Une lecture du jour
se lit **en dix secondes, au réveil, sur un téléphone** : elle tient en un paragraphe et
n'a qu'un seul travail, dire ce qui est acquis et ce qui vient.

C'est pour cela que la réponse attendue n'a qu'un champ. Trois rubriques sur une carte
d'accueil auraient reproduit, en plus long, ce que les chiffres juste au-dessous disent
déjà mieux.

## Le gras est demandé, et il compte

Les chiffres sont marqués `**ainsi**` et rendus par le composant `Markdown` — c'est la
forme que la charte donne à cette carte (`GuidelinesUI.html` §10, « Lecture assistée »),
où les chiffres d'un texte assisté sont en gras. Sans la consigne, un modèle sur deux rend
un paragraphe plat et la carte perd ce qui la rendait lisible d'un coup d'œil.

## Ce que la consigne interdit, et pourquoi ici plus qu'ailleurs

**Aucun chiffre qui ne soit pas dans le condensé.** C'est l'invariant « aucune valeur
inventée » appliqué à un texte : une phrase est le seul endroit de l'application où un
nombre faux passe inaperçu, parce qu'il n'a pas d'unité affichée à côté de lui ni de
tiret pour dire qu'il manque.

**Aucun compliment sans chiffre.** La règle est déjà dans la consigne de l'assistant, et
elle vaut doublement sur un écran d'accueil : « belle semaine » affiché tous les matins
cesse d'être lu au troisième jour, et emporte avec lui les fois où c'était vrai.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.domains.brief.models import MAX_MESSAGE

#: Les jours, en français. Un modèle n'a pas de calendrier : « mercredi » lui est donné,
#: il ne le déduit pas d'une date ISO — c'est la même règle que dans `assistant/context`.
WEEKDAYS = (
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
)

INSTRUCTION = (
    "Tu es le coach personnel de cette application de suivi sportif. Tu réponds "
    "uniquement par un objet JSON, sans phrase avant ni après, sans bloc de code."
)

_TEMPLATE = """Écris la lecture du jour — {weekday} {day}.

## Ce que disent les données

{context}

## Réponse attendue

{{"message": "…"}}

- Deux à quatre phrases, adressées à moi, au présent. Un seul paragraphe.
- Ouvre sur ce qui est **acquis** — aujourd'hui ou cette semaine — en citant un chiffre.
- Enchaîne sur ce qui vient : le geste le plus utile d'ici ce soir, un seul.
- Mets les chiffres en gras, avec des doubles astérisques : **2,4 séances**.

Règles :
- N'écris aucun chiffre qui ne soit pas ci-dessus. Pas d'estimation, pas de moyenne
  refaite, pas d'arrondi inventé.
- Ne félicite que sur un chiffre qui t'a été donné, et cite-le. Sinon, n'en parle pas.
- Tiens compte de l'heure : une journée entamée ne se juge pas comme une journée finie.
- Pas de liste, pas de titre, pas de question en retour.
- Tu n'es pas médecin : aucun diagnostic, aucun traitement, aucune interprétation de
  symptôme. Devant une douleur, tu renvoies vers un professionnel de santé.
"""


def build_prompt(*, day: dt.date, context: list[str]) -> str:
    """Assemble la consigne à partir du condensé factuel.

    Le condensé est **fourni** — `assistant.context.build` en détient l'unique
    implémentation, et en écrire une seconde ici donnerait deux versions des mêmes faits
    qui divergeraient au premier ajout de ligne. C'est l'argument déjà écrit dans
    `goals/service.py`, et il vaut mot pour mot.
    """
    return _TEMPLATE.format(
        weekday=WEEKDAYS[day.weekday()],
        day=f"{day:%d/%m/%Y}",
        context="\n".join(f"- {line}" for line in context) or "- Aucune donnée relevée.",
    )


def read_message(payload: dict[str, Any]) -> str:
    """Relit la réponse et rend le message, ou `""` s'il n'y a rien d'exploitable.

    Deux formes sont acceptées, et ce n'est pas de la complaisance : les modèles gratuits
    alternent entre `{"message": "…"}` et `{"message": ["…", "…"]}` pour la même consigne.
    Refuser la seconde coûterait une lecture sur deux ; l'accepter coûte trois lignes.

    Le service décide plus haut ce qu'il fait d'un message vide — ce module ne lève pas :
    il ne sait pas si l'appelant a un repli.
    """
    raw = payload.get("message")

    if isinstance(raw, str):
        text = raw.strip()
    elif isinstance(raw, list):
        # Une liste de fragments se recolle ; ses éléments non textuels sont écartés
        # plutôt que convertis — « 0 » recollé au milieu d'une phrase serait un chiffre
        # inventé, et c'est exactement ce que la consigne interdit au modèle.
        text = " ".join(item.strip() for item in raw if isinstance(item, str) and item.strip())
    else:
        # Ni chaîne ni liste : le modèle n'a pas répondu à la consigne. Un nombre nu, un
        # booléen ou un objet ne se rattrapent pas en les convertissant — `str(0)` rendrait
        # « 0 », qui s'afficherait comme une lecture.
        text = ""

    # Les repères d'un « rien » rendu en toutes lettres. Le même filtre que `weekly._text`,
    # pour que « null » n'arrive jamais à l'écran comme une lecture du jour.
    if text.lower() in {"", "null", "none", "n/a", "na", "-", "—", "--"}:
        return ""
    return text[:MAX_MESSAGE]


__all__ = ["INSTRUCTION", "WEEKDAYS", "build_prompt", "read_message"]
