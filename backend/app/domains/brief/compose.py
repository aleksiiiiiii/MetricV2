"""Consigne et relecture de la lecture du jour.

Module **pur**, comme `goals/weekly.py` et `assistant/conversation.py` : une consigne à
assembler, une réponse à relire. Il ne lit aucun fichier, ne connaît ni l'horloge ni le
modèle, et n'écrit rien. Chaque cas se vérifie sur des valeurs fixes, sans monter
d'application.

## Trois lectures, trois questions

Une seule par jour ne pouvait dire qu'une chose. Le même paragraphe servi au réveil, à midi
et le soir serait lu une fois puis ignoré — c'est le sort de « belle semaine » affiché tous
les matins, et la consigne l'interdit déjà pour les compliments. `SLOT_BRIEFS` donne à
chaque créneau un travail que les deux autres ne font pas ; le reste de la consigne, lui,
ne bouge pas, parce que les interdits ne dépendent pas de l'heure.

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

from app.domains.brief.models import DEFAULT_SLOT, MAX_MESSAGE, normalise_slot

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

#: Ce que chaque créneau demande, et ce qui le distingue des deux autres.
#:
#: **Trois moments, trois questions.** Le même paragraphe servi trois fois par jour serait
#: lu une fois puis ignoré — c'est le sort de « belle semaine » affiché tous les matins, et
#: la consigne l'interdit déjà pour les compliments. Chaque créneau a donc un travail que
#: les deux autres ne font pas :
#:
#: * **matin** — la journée n'a rien produit encore. On regarde en arrière (hier) et on
#:   pose ce qui vient. C'est le seul créneau qui a le droit de commenter la veille : le
#:   faire à midi reviendrait à ressasser.
#: * **midi** — la journée est entamée et rien n'est joué. On dit où en est ce qui se suit
#:   dans la journée — ce qui a été mangé, bu —, et on encourage sur la séance qui reste à
#:   faire. Pas de bilan : il est trop tôt, et un bilan de mi-journée se lit comme un
#:   jugement.
#: * **soir** — la journée est presque close. On récapitule ce qu'elle a produit, et on
#:   nomme **ce qui se rattrape encore ce soir** — un verre d'eau, dix minutes de gainage,
#:   une pesée. C'est le seul créneau où « il reste » a un sens.
SLOT_BRIEFS: dict[str, str] = {
    "matin": """- Deux à quatre phrases, adressées à moi, au présent. Un seul paragraphe.
- Ouvre sur **hier** : ce qui a été fait, en citant un chiffre. Si hier est vide, dis-le
  sans le commenter — une journée sans relevé n'est pas une journée ratée.
- Enchaîne sur **aujourd'hui** : ce qui est prévu, et le geste le plus utile de la journée.
  Un seul.
- Mets les chiffres en gras, avec des doubles astérisques : **2,4 séances**.""",
    "midi": """- Deux à quatre phrases, adressées à moi, au présent. Un seul paragraphe.
- Dis où en est la journée sur ce qui se suit au fil des heures — repas, protéines, eau —
  en citant un chiffre et ce qu'il reste à la cible.
- Encourage sur la **séance** : celle qui est prévue, ou celle que le déséquilibre par
  groupe musculaire appelle. Nomme-la.
- **Ne fais aucun bilan de la journée** : elle n'est pas finie, et un bilan à midi se lit
  comme un jugement sur ce qui peut encore changer.
- Mets les chiffres en gras, avec des doubles astérisques : **86 g de protéines**.""",
    "soir": """- Deux à quatre phrases, adressées à moi, au présent. Un seul paragraphe.
- Récapitule ce que la journée a produit, en citant un chiffre.
- Finis sur **ce qui se rattrape encore ce soir** — un verre d'eau, dix minutes, une
  pesée. Un seul geste, et seulement s'il en reste un qui tienne avant la nuit.
- Si la journée est déjà pleine, dis-le et n'invente pas un geste de plus : une journée
  tenue se referme, elle ne se rallonge pas.
- Mets les chiffres en gras, avec des doubles astérisques : **1,8 L**.""",
}

_TEMPLATE = """Écris la lecture {moment} — {weekday} {day}.

## Ce que disent les données

{context}

## Réponse attendue

{{"message": "…"}}

{brief}

Règles :
- N'écris aucun chiffre qui ne soit pas ci-dessus. Pas d'estimation, pas de moyenne
  refaite, pas d'arrondi inventé.
- Ne félicite que sur un chiffre qui t'a été donné, et cite-le. Sinon, n'en parle pas.
- Tiens compte de l'heure : une journée entamée ne se juge pas comme une journée finie.
- Pas de liste, pas de titre, pas de question en retour.
- Tu n'es pas médecin : aucun diagnostic, aucun traitement, aucune interprétation de
  symptôme. Devant une douleur, tu renvoies vers un professionnel de santé.
"""

#: Comment chaque créneau se nomme dans la première ligne de la consigne.
_MOMENTS: dict[str, str] = {
    "matin": "du matin",
    "midi": "de la mi-journée",
    "soir": "du soir",
}


def build_prompt(*, day: dt.date, context: list[str], slot: str = DEFAULT_SLOT) -> str:
    """Assemble la consigne du créneau à partir du condensé factuel.

    Le condensé est **fourni** — `assistant.context.build` en détient l'unique
    implémentation, et en écrire une seconde ici donnerait deux versions des mêmes faits
    qui divergeraient au premier ajout de ligne. C'est l'argument déjà écrit dans
    `goals/service.py`, et il vaut mot pour mot.

    Un créneau inconnu retombe sur `matin` par `normalise_slot`. Le repli est celui du
    fichier, et non un second : une cellule abîmée et un argument fautif ne doivent pas
    donner deux lectures différentes du même mot.
    """
    wanted = normalise_slot(slot)
    return _TEMPLATE.format(
        moment=_MOMENTS[wanted],
        weekday=WEEKDAYS[day.weekday()],
        day=f"{day:%d/%m/%Y}",
        context="\n".join(f"- {line}" for line in context) or "- Aucune donnée relevée.",
        brief=SLOT_BRIEFS[wanted],
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


__all__ = ["INSTRUCTION", "SLOT_BRIEFS", "WEEKDAYS", "build_prompt", "read_message"]
