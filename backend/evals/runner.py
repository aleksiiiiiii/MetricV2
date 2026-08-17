"""L'exécuteur — joue les cas, vérifie, rend un rapport comparable.

## Il ne cascade pas, et c'est le point

`AiService.ask_json` essaie jusqu'à cinq modèles et rend le premier résultat exploitable.
C'est le bon comportement en production — `IA-03` promet qu'un quota n'immobilise pas
l'application. Ce serait le pire ici : on mesurerait « un modèle parmi cinq » au lieu du
modèle nommé, et deux exécutions ne compareraient plus rien.

L'exécuteur poste donc lui-même, sur le modèle demandé et lui seul. Un échec est un échec :
il se lit dans le rapport au lieu d'être rattrapé.

Le corps posté est celui que l'application construit — `OpenRouterClient.build_body`, sans
rien redéfinir. Deux corps différents donneraient deux mesures pour la même consigne. Poster
soi-même donne en prime la charge utile complète, donc les jetons consommés, que `complete`
ne rend pas.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2

from app.config import get_settings
from app.domains.ai.client import OpenRouterClient
from app.domains.ai.extract import first_json_object
from app.domains.assistant import actions as catalogue
from app.domains.assistant import context, conversation
from evals import fixtures
from evals.cases import CAS, Cas
from evals.checks import Constat, Reponse

#: Large, parce qu'une réponse tronquée fausserait la mesure au lieu de la révéler. La
#: production tient à 1 600 (mesuré au jalon 1) ; ici on veut voir ce que le modèle **veut**
#: dire, pas ce que le plafond lui laisse dire.
MAX_TOKENS = 8000

#: Deux passes au plus, comme la production. Le lot 4 relèvera les deux ensemble.
MAX_PASSES = 2


@dataclass(slots=True)
class Resultat:
    cas: Cas
    constats: list[Constat] = field(default_factory=list)
    reponse: Reponse | None = None
    erreur: str | None = None
    jetons_entree: int = 0
    jetons_sortie: int = 0
    cout: float = 0.0
    secondes: float = 0.0

    @property
    def ok(self) -> bool:
        return self.erreur is None and all(c.ok for c in self.constats)

    @property
    def echecs(self) -> list[Constat]:
        return [c for c in self.constats if not c.ok]


async def _poster(
    http: httpx2.AsyncClient, corps: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Poste et rend `(charge utile, usage)`. Lève sur toute réponse inexploitable."""
    reponse = await http.post("/chat/completions", json=corps)
    if reponse.status_code >= 400:
        raise RuntimeError(f"HTTP {reponse.status_code} : {reponse.text[:200]}")

    charge = reponse.json()
    if not isinstance(charge, dict):
        raise RuntimeError("réponse de forme inattendue")
    if isinstance(charge.get("error"), dict):
        raise RuntimeError(str(charge["error"].get("message") or "erreur du fournisseur"))

    choix = charge.get("choices")
    if not isinstance(choix, list) or not choix:
        raise RuntimeError("aucune réponse")
    texte = (choix[0].get("message") or {}).get("content")
    if not isinstance(texte, str) or not texte.strip():
        raise RuntimeError("réponse vide")

    objet = first_json_object(texte)
    if objet is None:
        raise RuntimeError(f"aucun JSON exploitable : {texte[:120]!r}")
    return objet, charge.get("usage") or {}


async def jouer(
    http: httpx2.AsyncClient,
    client: OpenRouterClient,
    cas: Cas,
    *,
    model: str,
    extra: dict[str, Any] | None,
) -> Resultat:
    """Joue un cas de bout en bout, seconde passe comprise."""
    resultat = Resultat(cas=cas)
    debut = time.monotonic()

    # Le catalogue est le **vrai** : renommer une action fera bouger la mesure.
    lignes_actions = catalogue.describe_catalogue()
    disponibles = list(fixtures.TRANCHES)
    condense = list(cas.condense)

    try:
        for passe in range(1, MAX_PASSES + 1):
            prompt = conversation.build_prompt(
                question=cas.question,
                context=condense,
                memory=context.memory_lines(cas.carnet),
                actions=lignes_actions,
                slices=disponibles,
                naming=True,
            )
            corps = client.build_body(
                model,
                instruction=conversation.INSTRUCTION,
                prompt=prompt,
                max_tokens=MAX_TOKENS,
                # Comme la route assistant, et pour la même raison qu'elle : le jeu doit
                # envoyer ce que la production envoie, sinon il mesure autre chose. Depuis
                # le lot 7, ni l'une ni l'autre ne porte `temperature` — ce qui rend aussi
                # les exécutions un peu moins reproductibles entre elles, et c'est le prix
                # assumé d'une mesure fidèle. Les deux cas instables l'étaient déjà avant.
                temperature=None,
                extra=extra,
            )
            objet, usage = await _poster(http, corps)

            resultat.jetons_entree += int(usage.get("prompt_tokens") or 0)
            resultat.jetons_sortie += int(usage.get("completion_tokens") or 0)
            resultat.cout += float(usage.get("cost") or 0.0)

            reclamees = conversation.read_need(objet, available=disponibles)
            # On ne sert que ce que le cas a figé. Une tranche réclamée mais non prévue est
            # un signal en soi : le rapport la montrera dans `need`.
            a_servir = [n for n in reclamees if n in cas.tranches]
            if not a_servir or passe == MAX_PASSES:
                break
            for nom in a_servir:
                condense.extend(fixtures.TRANCHES[nom])

        # `known` porte les notes **brutes**, comme `AssistantService.ask` : c'est ce qui
        # permet à `_echoes` d'écarter une note qui redit le carnet.
        reply, retenues, _ = conversation.read_reply(
            objet, context=cas.condense, known=[entry.note for entry in cas.carnet]
        )
        resultat.reponse = Reponse(
            reply=reply,
            remember=retenues,
            actions=conversation.read_actions(objet),
            need=conversation.read_need(objet, available=disponibles),
            titre=conversation.read_title(objet, fallback=cas.question[:60]),
            condense=condense,
            passes=passe,
            brut=objet,
        )
        resultat.constats = [verifier(resultat.reponse) for verifier in cas.attendus]
    except (RuntimeError, httpx2.HTTPError) as erreur:
        resultat.erreur = str(erreur)

    resultat.secondes = time.monotonic() - debut
    return resultat


def rapport(resultats: list[Resultat], *, model: str, reflexion: bool) -> str:
    """Le rapport lisible. Une ligne par cas, le détail sous les échecs."""
    lignes = [
        "",
        f"  Modèle    {model}" + ("  (réflexion demandée)" if reflexion else ""),
        f"  Cas       {len(resultats)}",
        "",
    ]

    groupe_courant = ""
    for r in resultats:
        if r.cas.groupe != groupe_courant:
            groupe_courant = r.cas.groupe
            lignes.append(f"  ── {groupe_courant} ──")
        if r.erreur:
            marque = "!!"
        elif r.ok:
            marque = "ok"
        else:
            marque = "ÉC"
        temoin = " ⟳" if r.cas.bascule else ""
        lignes.append(f"  {marque}  {r.cas.nom:<24}{temoin}  {r.secondes:>5.1f}s")
        if r.erreur:
            lignes.append(f"        └─ {r.erreur}")
        for constat in r.echecs:
            fragile = " [FRAGILE]" if constat.fragile else ""
            lignes.append(f"        └─ {constat.nom}{fragile} : {constat.detail}")

    reussis = sum(1 for r in resultats if r.ok)
    erreurs = sum(1 for r in resultats if r.erreur)
    cout = sum(r.cout for r in resultats)
    entree = sum(r.jetons_entree for r in resultats)
    sortie = sum(r.jetons_sortie for r in resultats)
    temoins = sum(1 for r in resultats if r.cas.bascule)

    lignes += [
        "",
        f"  {reussis}/{len(resultats)} cas au vert"
        + (f", {erreurs} injoignable(s)" if erreurs else ""),
        f"  {entree} jetons en entrée, {sortie} en sortie — {cout:.4f} $",
        f"  dont {temoins} cas témoins (⟳), qui doivent basculer après les lots 1 et 2",
        "",
    ]
    return "\n".join(lignes)


def _instantane(resultats: list[Resultat], *, model: str, reflexion: bool) -> dict[str, Any]:
    """Ce qu'on écrit sur disque pour pouvoir comparer deux exécutions."""
    return {
        "modele": model,
        "reflexion": reflexion,
        "cas": {
            r.cas.nom: {
                "ok": r.ok,
                "erreur": r.erreur,
                "echecs": [c.nom for c in r.echecs],
                "reply": r.reponse.reply if r.reponse else "",
                "actions": [a.name for a in r.reponse.actions] if r.reponse else [],
                "need": r.reponse.need if r.reponse else [],
                "passes": r.reponse.passes if r.reponse else 0,
            }
            for r in resultats
        },
    }


def comparer(avant: dict[str, Any], apres: dict[str, Any]) -> str:
    """Ce qui a changé entre deux exécutions — la seule sortie qui décide."""
    lignes = [
        "",
        f"  {avant['modele']}  →  {apres['modele']}",
        "",
    ]
    gagnes, perdus = [], []
    for nom, apres_cas in apres["cas"].items():
        avant_cas = avant["cas"].get(nom)
        if avant_cas is None:
            continue
        if apres_cas["ok"] and not avant_cas["ok"]:
            gagnes.append(nom)
        elif avant_cas["ok"] and not apres_cas["ok"]:
            perdus.append(f"{nom} ({', '.join(apres_cas['echecs']) or apres_cas['erreur']})")

    lignes.append(f"  gagnés  {len(gagnes)}")
    lignes += [f"    + {n}" for n in gagnes]
    lignes.append(f"  perdus  {len(perdus)}")
    lignes += [f"    - {n}" for n in perdus]
    if not gagnes and not perdus:
        lignes.append("  (aucun changement de verdict)")
    lignes.append("")
    return "\n".join(lignes)


async def executer(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    reglages = get_settings()
    if not reglages.openrouter_api_key:
        print("Aucune clé OpenRouter configurée — rien à mesurer.")
        return 2, {}

    model = args.model or reglages.openrouter_model
    if not model:
        print("Aucun modèle : passer --model ou régler OPENROUTER_MODEL.")
        return 2, {}

    choisis = [c for c in CAS if not args.cas or args.cas in c.nom]
    if not choisis:
        print(f"Aucun cas ne correspond à « {args.cas} ».")
        return 2, {}

    extra = {"reasoning": {"enabled": True}} if args.reflexion else None
    client = OpenRouterClient(
        api_key=reglages.openrouter_api_key, base_url=reglages.openrouter_base_url
    )

    async with httpx2.AsyncClient(
        base_url=reglages.openrouter_base_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {reglages.openrouter_api_key}",
            "HTTP-Referer": "https://github.com/aleksi/metric",
            # Sans accent : un en-tête HTTP s'encode en ASCII, et « évaluation » y lève.
            "X-Title": "Metric (evaluation)",
        },
        timeout=httpx2.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0),
    ) as http:
        resultats: list[Resultat] = []
        for index, cas in enumerate(choisis, start=1):
            print(f"  [{index}/{len(choisis)}] {cas.nom}…", flush=True)
            resultats.append(await jouer(http, client, cas, model=model, extra=extra))

    await client.aclose()
    print(rapport(resultats, model=model, reflexion=args.reflexion))

    code = 0 if all(r.ok for r in resultats) else 1
    return code, _instantane(resultats, model=model, reflexion=args.reflexion)


def main() -> int:
    """Point d'entrée. **Les lectures et écritures de fichier vivent ici, pas dans la boucle
    asynchrone** — un `Path.write_text` dans une coroutine bloque la boucle d'événements, et
    `executer` en tient une ouverte sur le réseau."""
    analyseur = argparse.ArgumentParser(
        prog="python -m evals.runner",
        description="Joue le jeu d'évaluation de l'assistant contre un modèle réel.",
    )
    analyseur.add_argument("--model", help="identifiant OpenRouter ; défaut : OPENROUTER_MODEL")
    analyseur.add_argument(
        "--reflexion", action="store_true", help="demande `reasoning` au fournisseur"
    )
    analyseur.add_argument("--cas", help="ne joue que les cas dont le nom contient ce fragment")
    analyseur.add_argument("--sortie", help="écrit l'instantané JSON dans ce fichier")
    analyseur.add_argument("--comparer", help="compare le résultat à un instantané précédent")
    args = analyseur.parse_args()

    code, instantane = asyncio.run(executer(args))
    if instantane and args.sortie:
        Path(args.sortie).write_text(
            json.dumps(instantane, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  Instantané écrit dans {args.sortie}\n")
    if instantane and args.comparer:
        avant = json.loads(Path(args.comparer).read_text(encoding="utf-8"))
        print(comparer(avant, instantane))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
