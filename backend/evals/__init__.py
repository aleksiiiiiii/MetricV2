"""Le jeu d'évaluation de l'assistant — ce que `make check` ne saura jamais dire.

1 120 tests vérifient la relecture, les filtres et les bornes. **Aucun ne vérifie qu'une
réponse est bonne.** C'est le même angle mort que pour les écrans, où `CLAUDE.md` note que
« sur les cinq derniers lots, la moitié des défauts sont sortis en regardant la page, et
zéro de la batterie ». Ici la page à regarder est la réponse.

## Ce que ce paquet mesure, et ce qu'il ne mesure pas

Il mesure **la consigne, le modèle et la relecture** — le triplet qui décide de ce que
l'assistant dit. Il ne mesure ni le stockage, ni les services de domaine, ni les tranches :
tout ce qui entre est figé dans [`fixtures.py`](fixtures.py).

C'est délibéré, et c'est ce qui rend le résultat comparable d'un mois sur l'autre. Un
condensé lu sur les vraies données changerait tous les jours ; deux exécutions ne
mesureraient plus la même chose, et une régression serait indiscernable d'une journée sans
séance.

## Rien n'est écrit, nulle part

**Le jeu n'appelle jamais `AssistantService.ask`.** Cette méthode écrit — le carnet
(`remember`), les fils, les messages — et la lancer contre le vrai stockage polluerait des
données de santé réelles avec deux douzaines de conversations fictives.

Il appelle donc directement `build_prompt`, puis `read_reply` / `read_actions` / `read_need`
sur ce que le modèle rend. C'est possible parce que `conversation.py` est un **module pur**,
et son en-tête le revendique : « chaque cas se vérifie sur des valeurs fixes, sans monter
d'application ». Le jeu d'évaluation est exactement l'usage que cette propriété rendait
possible.

Le catalogue d'actions, lui, est le **vrai** : `describe_catalogue()`. Renommer une action
sans toucher aux cas fera donc bouger la mesure, ce qui est le comportement voulu.

## Pourquoi ce n'est pas dans `make check`

Un test qui appelle un modèle payant n'a rien à faire dans une batterie qui doit être verte
avant chaque commit : il coûte, il dépend du réseau, et il n'est pas déterministe. Le
`testpaths = ["tests"]` du `pyproject.toml` garde ce paquet hors de la collecte pytest.

Il se lance à part, avant et après tout changement de modèle ou de consigne :

    make eval                                   # le modèle du .env
    make eval ARGS="--model anthropic/claude-opus-5 --reflexion"
    make eval ARGS="--comparer eval-origine.json"
"""

from evals.cases import CAS, Cas
from evals.checks import Constat, Reponse, Verification

__all__ = ["CAS", "Cas", "Constat", "Reponse", "Verification"]
