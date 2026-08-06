"""Le condensé envoyé à l'assistant (`IA-09`).

**Ce module est la promesse du lot.** « Récupérer toutes les infos » ne veut pas dire
envoyer les fichiers : cela veut dire rassembler, en une trentaine de lignes, tout ce qui
permet de répondre — et rien de plus. La règle vient de `GOAL-02` et elle vaut ici avec
plus de force, parce qu'une conversation invite à tout joindre « au cas où ».

Rien n'est calculé ici. Chaque ligne vient du service qui détient sa règle : les cinq
métriques et leurs fenêtres du domaine Objectifs, la série d'assiduité de `AGG-03`, le
respect du planning de `PLAN-06`. Recalculer une moyenne à cet endroit serait le plus sûr
moyen que l'assistant annonce un chiffre que l'écran d'à côté contredit.

Le condensé est **publié** avec la réponse (`ChatReply.context`) : c'est ce qui rend la
promesse vérifiable à l'écran plutôt que déclarative dans un commentaire.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from app.core.dates import today_local
from app.domains.aggregates.service import DashboardService
from app.domains.goals.progress import fr
from app.domains.goals.service import GoalService, WeeklyInsightService
from app.storage.files import FileStore

if TYPE_CHECKING:  # pragma: no cover - import de typage seulement
    # Même arrangement qu'au lot L14, et pour la même raison : importer quoi que ce soit
    # de `app.domains.planning` exécute le `__init__` du paquet, donc son routeur. Le taux
    # de respect arrive **construit par le routeur**, jamais recalculé (`PLAN-06`).
    from app.domains.planning.schemas import AdherenceView

#: Bilans hebdomadaires rappelés. Deux suffisent à situer une tendance ; au-delà, ils
#: prennent la place des chiffres qu'ils commentaient.
RECENT_INSIGHTS = 2

#: Notes de mémoire envoyées au maximum. Le carnet part **entier** dans chaque question :
#: c'est ce qui rend l'assistant utile au dixième tour, et ce qui impose une borne.
MAX_MEMORY_LINES = 40

_WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


async def build(
    store: FileStore, *, adherence: AdherenceView, today: date | None = None
) -> list[str]:
    """Rassemble le condensé. `adherence` est **fourni**, jamais recalculé.

    L'ordre des lignes n'est pas indifférent : la date d'abord — un modèle n'a pas de
    calendrier et « cette semaine » ne veut rien dire sans elle —, puis ce qu'on vise, puis
    ce qu'on fait, puis ce qu'on a dit de la semaine passée.
    """
    current = today or today_local()
    goals = GoalService(store)

    lines: list[str] = [f"Nous sommes le {_WEEKDAYS[current.weekday()]} {current:%d/%m/%Y}"]

    view = await goals.view(today=current)
    if view.active is not None:
        active = view.active
        progress = active.progress
        share = "" if progress.ratio is None else f", {fr(progress.ratio * 100)} % du chemin"
        lines.append(
            f"Objectif en cours : {active.goal.title} — {progress.summary}{share} "
            f"({progress.basis}), échéance dans {active.days_left} jour(s)"
        )
    else:
        lines.append("Objectif en cours : aucun")

    # Les cinq métriques, leurs fenêtres, l'amplitude du poids, les cibles réglées et les
    # suppléments suivis — le même condensé que celui d'une proposition d'objectif, à la
    # ligne près. Deux versions divergeraient au premier ajout.
    facts, _ = await goals.summary_lines(current)
    lines.extend(facts)

    streak = await DashboardService(store).streak(current)
    lines.append(
        f"Assiduité de suivi : {streak.current} jour(s) d'affilée, "
        f"record {streak.longest}, {streak.active_days} jour(s) relevés au total"
    )

    if adherence.planned:
        share = "" if adherence.rate is None else f" ({fr(adherence.rate * 100)} %)"
        lines.append(
            f"Respect du planning sur {len(adherence.weeks)} semaines : "
            f"{adherence.honoured} séance(s) honorée(s) sur {adherence.planned} prévue(s){share}"
        )
    else:
        lines.append("Respect du planning : rien n'était prévu sur la période")

    weekly = await WeeklyInsightService(store).view(today=current)
    for entry in weekly.entries[:RECENT_INSIGHTS]:
        lines.append(f"Bilan de la semaine du {entry.week:%d/%m} : {entry.summary}")

    if len(view.history) > 0:
        outcomes = ", ".join(
            f"« {item.title} » {item.outcome_label or 'sans résultat noté'}"
            for item in view.history[:3]
        )
        lines.append(f"Objectifs passés : {outcomes}")

    return lines


def memory_lines(entries: list[tuple[str, str]]) -> list[str]:
    """Le carnet, mis en phrases. `(sujet, note)` → « sujet — note ».

    Séparé du condensé de données, et pas seulement pour la mise en page : ce sont deux
    natures d'information. Le condensé est **mesuré** et recalculé à chaque question ; le
    carnet est **dit** et ne change que lorsqu'on le corrige. Les mélanger inviterait le
    modèle à traiter une phrase de mars comme un chiffre d'aujourd'hui.
    """
    return [f"{topic} — {note}" for topic, note in entries[:MAX_MEMORY_LINES]]


__all__ = ["MAX_MEMORY_LINES", "RECENT_INSIGHTS", "build", "memory_lines"]
