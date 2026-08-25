"""Ce qui est dû, et ce que ça dit (`NOT-02`, `NOT-03`).

**Ce module est pur.** Ni fichier, ni HTTP, ni horloge : on lui passe des créneaux, un
instant, un état du jour et ce qui a déjà été envoyé ; il rend une liste de rappels. C'est
le même découpage que `heatmap/engine.py`, et pour la même raison — ce qui juge se vérifie
sur des valeurs fixes, en dix lignes, sans monter d'application.

`scheduler.py` **coud** : il lit les fichiers, appelle ce module, envoie, et consigne.
Aucune règle n'y vit. Une règle écrite là échapperait à cette batterie.

── La règle qui gouverne tout le fichier ─────────────────────────────────────

> **Un rappel dit ce qui n'est pas noté, pas ce qui n'a pas été fait.**

« Tu n'as pas bu aujourd'hui » est une **affirmation fausse** : l'application sait
seulement que rien n'a été consigné. Peut-être que la bouteille est vide et que personne
n'a ouvert l'écran. C'est « aucune valeur inventée à l'écran » appliqué à une
notification, et c'est le cas **difficile** — une notification est lue en trois mots, sur
un écran verrouillé, sans contexte et sans moyen de vérifier.

| Interdit | Retenu |
|---|---|
| « Tu n'as pas bu aujourd'hui » | « Hydratation — rien de noté » |
| « Tu as sauté ta séance » | « Séance prévue — rien de noté » |
| « Tu as oublié la créatine » | « Suppléments — pas encore noté : créatine » |

Un chiffre **relevé** se cite tel quel : « 750 ml notés sur 2000 » est une mesure, elle est
vraie, et elle est utile. C'est l'**absence** qu'on n'a pas le droit de transformer en
affirmation sur ce que quelqu'un a fait de sa journée.

── Le corollaire de conception ───────────────────────────────────────────────

Un rappel qui arrive au mauvais moment se désinstalle en un geste et ne revient jamais.
C'est la fonctionnalité la plus facile à rendre nuisible du projet entier. D'où trois
règles, ici et pas dans l'intention :

1. **On ne rappelle que ce qui a quelque chose à dire.** Tout noté, rien n'est envoyé —
   `compose` rend `None`. Un rappel quotidien qui félicite finit par être ignoré, et
   emporte avec lui ceux qui comptaient.
2. **Aucun rappel de séance sans séance prévue.** C'est la cadence `conditional` de
   `HEAT-12` : attendu seulement si un déclencheur est vrai. Rappeler une séance un jour
   de repos est exactement le rappel qu'on désinstalle.
3. **Une fenêtre de rattrapage bornée.** Un serveur redémarré à 20 h 05 délivre le rappel
   de 20 h ; redémarré à 23 h, il ne le délivre pas. Perdre un rappel coûte moins qu'en
   recevoir un la nuit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum

#: Au-delà de ce retard, un créneau manqué est **abandonné**, pas rattrapé.
#:
#: Une heure : assez pour couvrir un redémarrage, une coupure réseau ou une lecture
#: Nextcloud qui traîne ; trop peu pour qu'un rappel de 20 h arrive au coucher. Le
#: paramètre est ouvert pour les tests, mais sa valeur est une décision, pas un réglage.
GRACE = timedelta(minutes=60)


#: Plafond quotidien, tous types confondus.
#:
#: Dix. Il ne sert pas à brider les rappels prévus — il y en a moins — mais à **borner ce
#: qu'une règle mal écrite pourrait produire**. Un déclencheur réactif se déclenche sur un
#: état, et un état peut rester vrai toute la journée : sans plafond, la faute ne se voit
#: qu'au téléphone de quelqu'un, et elle s'y voit une fois.
DAILY_CAP = 10

#: Délai minimum entre deux notifications, tous types confondus.
#:
#: Quinze minutes. Le problème n'est pas le nombre mais le **groupement** : 18 h 30
#: protéines, 19 h séance et 19 h 05 hydratation arrivent en grappe et se balayent d'un
#: seul geste — les trois, y compris celle qui comptait.
#:
#: Ce qui est repoussé n'est pas perdu : il redevient dû à la passe suivante, tant que
#: `GRACE` n'est pas dépassée. C'est la même mécanique que le rattrapage d'un redémarrage.
SPACING = timedelta(minutes=15)

#: En deçà de quoi un écart ne mérite pas d'être signalé, en part de la cible.
#:
#: **C'est le seuil qui rend un rappel « réactif ».** Sans lui, un contrôle à 14 h partirait
#: qu'on soit à 300 ml ou à 1 900 sur 2 000 — c'est-à-dire à l'heure, ce que N2 remplace.
#:
#: Un quart : sur une cible de 2 000 ml, c'est 500 ml, un écart réel et rattrapable à
#: n'importe quelle heure. En dessous, on y est essentiellement, et la notification devient
#: le bruit qu'on désinstalle.
#:
#: **Une part et non un nombre absolu** : le seuil suit la cible. Quelqu'un qui vise 3 L
#: n'a pas le même « il te reste beaucoup » que quelqu'un qui vise 1,5 L, et un seuil en
#: millilitres ferait mentir l'un des deux.
GAP_SHARE = 0.25


def gap_matters(done: float, target: float, share: float = GAP_SHARE) -> bool:
    """L'écart à la cible mérite-t-il qu'on en parle ?

    Sans cible réglée, la réponse est **non** : comparer à zéro rendrait tout écart
    infini, et le rappel partirait tous les jours pour dire un chiffre sans référence.
    C'est « aucune valeur inventée » — une cible absente n'est pas une cible de zéro.
    """
    if target <= 0:
        return False
    return (target - done) / target >= share


def allowed(
    *,
    now: datetime,
    sent_today: int,
    last_sent: datetime | None,
    cap: int = DAILY_CAP,
    spacing: timedelta = SPACING,
) -> bool:
    """Le budget du jour permet-il d'envoyer **maintenant** ?

    Séparé de `due` à dessein : `due` répond « y a-t-il quelque chose à dire », celle-ci
    répond « a-t-on le droit de le dire tout de suite ». Les mélanger rendrait impossible
    de distinguer un rappel qui n'avait rien à dire — définitivement clos pour la journée —
    d'un rappel repoussé de quinze minutes, qui doit revenir.

    Un `last_sent` d'un autre jour ne bloque rien : `sent_today` est compté sur le jour
    local, et la comparaison d'espacement porte sur un instant, pas sur une date. Une
    notification de 23 h 55 espace donc bien celle de 00 h 05, ce qui est voulu — le
    téléphone, lui, ne change pas de journée à minuit.
    """
    if sent_today >= cap:
        return False
    return last_sent is None or now - last_sent >= spacing


class ReminderKind(StrEnum):
    """Les quatre types de rappel de `NOT-02`.

    Les valeurs sont celles des clés `reminders_*` de `settings.csv` et de la colonne
    `kind` de `notifications/sent.csv`. Les trois doivent s'écrire pareil, sinon un
    redémarrage ne reconnaît plus ce qu'il a envoyé.
    """

    SUPPLEMENTS = "supplements"
    HYDRATION = "hydration"
    MEALS = "meals"
    WORKOUT = "workout"
    #: L'écart aux protéines, au dernier moment où un repas peut le combler (**N2**).
    PROTEIN = "protein"


@dataclass(frozen=True)
class DaySnapshot:
    """Ce que l'application **sait** du jour.

    Chaque champ dit ce qui est *consigné*, jamais ce qui a été *fait*. Le nom des champs
    porte cette distinction, et c'est délibéré : `meals_logged` ne se lit pas comme
    « repas pris ». Un jour sans donnée est un jour sans donnée.
    """

    #: Noms des suppléments dus aujourd'hui dont la prise n'est pas notée. Vient de
    #: `SupplementService.checklist(day)`, qui sait déjà résoudre les cadences.
    supplements_pending: tuple[str, ...] = ()
    #: Volume noté aujourd'hui, en millilitres.
    hydration_ml: int = 0
    #: Objectif du jour, lu dans les réglages. Zéro s'il n'est pas renseigné.
    hydration_target_ml: int = 0
    #: Nombre de repas notés aujourd'hui.
    meals_logged: int = 0
    #: Protéines notées aujourd'hui, en grammes.
    protein_g: float = 0.0
    #: Cible quotidienne, lue dans les réglages. Zéro si elle n'est pas renseignée.
    protein_target_g: float = 0.0
    #: Séances **prévues** au planning aujourd'hui (`PLAN-01`).
    workouts_planned: int = 0
    #: Séances et courses notées aujourd'hui.
    workouts_logged: int = 0


@dataclass(frozen=True)
class Reminder:
    """Un rappel prêt à partir. Le titre cadre, le corps détaille."""

    kind: ReminderKind
    title: str
    body: str

    def payload(self) -> dict[str, str]:
        """Ce que le service worker recevra.

        `tag` vaut le type : deux rappels de suppléments à deux jours d'intervalle
        remplacent l'un l'autre au lieu d'empiler deux lignes dans le centre de
        notifications.
        """
        return {"title": self.title, "body": self.body, "tag": self.kind.value, "url": "/"}


@dataclass(frozen=True)
class Checkpoint:
    """Un **contrôle** : un type de rappel, à une heure donnée.

    Un type n'a plus forcément un créneau et un seul. L'hydratation en a trois — 14 h,
    18 h, 22 h 30 — parce que l'écart se lit à plusieurs moments de la journée et qu'un
    seul contrôle obligerait à choisir entre « trop tôt pour savoir » et « trop tard pour
    agir ».

    C'est ce couple, et non le type seul, qui est consigné dans `sent.csv` : sans l'heure,
    le premier contrôle de la journée éteindrait les deux autres.
    """

    kind: ReminderKind
    at: time


def parse_slot(raw: str) -> time | None:
    """Lit un créneau `HH:MM`, ou rend `None`.

    **Illisible vaut éteint**, et c'est le seul repli acceptable : une valeur par défaut
    réveillerait quelqu'un. C'est la règle « un fichier de configuration ne fait jamais
    tomber un écran » poussée d'un cran — ici, une cellule abîmée ne doit pas seulement
    éviter de casser, elle ne doit surtout pas déclencher.
    """
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = time.fromisoformat(text)
    except ValueError:
        return None
    # Une seconde ou une microseconde dans un créneau n'a pas de sens et fausserait la
    # comparaison au retard : on ne garde que l'heure et la minute.
    return time(hour=parsed.hour, minute=parsed.minute)


def _enumerate(names: tuple[str, ...]) -> str:
    """Énumération française — « a, b et c ».

    Bornée à trois noms suivis d'un décompte : une notification lue sur un écran
    verrouillé est tronquée à quelques mots, et une liste de huit compléments n'y
    apprendrait rien de plus qu'« il y en a huit ».
    """
    if len(names) <= 3:
        head, *tail = names
        return head if not tail else f"{', '.join(names[:-1])} et {names[-1]}"
    return f"{', '.join(names[:3])} et {len(names) - 3} autre" + ("s" if len(names) > 4 else "")


def compose(kind: ReminderKind, snapshot: DaySnapshot) -> Reminder | None:
    """Le texte d'un rappel, ou `None` s'il n'y a rien à dire.

    Rendre `None` est le cas normal, pas une erreur : c'est ce qui fait qu'un rappel
    quotidien reste un signal. Un rappel qui part tous les jours, y compris quand tout est
    noté, cesse en trois semaines d'être lu — et emporte avec lui ceux qui comptaient.
    """
    match kind:
        case ReminderKind.SUPPLEMENTS:
            if not snapshot.supplements_pending:
                return None
            return Reminder(
                kind=kind,
                title="Suppléments",
                # « Pas encore noté : » et non « tu n'as pas pris » — la formule évite
                # l'accord sur des noms libres *et* l'affirmation sur ce qui a été fait.
                body=f"Pas encore noté : {_enumerate(snapshot.supplements_pending)}.",
            )

        case ReminderKind.HYDRATION:
            # **C'est l'écart qui décide, plus l'heure seule** (**N2**). À 1 400 sur 2 000
            # il n'y a rien à dire : le contrôle passe et se tait.
            if not gap_matters(snapshot.hydration_ml, snapshot.hydration_target_ml):
                return None
            if snapshot.hydration_ml == 0:
                return Reminder(
                    kind=kind,
                    title="Hydratation",
                    body=f"Rien de noté · cible {snapshot.hydration_target_ml} ml.",
                )
            # Un chiffre relevé se cite : il est vrai, et il dit où l'on en est. C'est
            # l'absence qu'on ne transforme pas en affirmation — et l'urgence reste dans
            # les chiffres, sans qu'on juge.
            return Reminder(
                kind=kind,
                title="Hydratation",
                body=(
                    f"{snapshot.hydration_ml} ml notés sur "
                    f"{snapshot.hydration_target_ml} · il reste "
                    f"{snapshot.hydration_target_ml - snapshot.hydration_ml} ml."
                ),
            )

        case ReminderKind.PROTEIN:
            # Le dernier moment où un repas peut combler l'écart. Même règle qu'au-dessus :
            # sans écart, rien ne part.
            if not gap_matters(snapshot.protein_g, snapshot.protein_target_g):
                return None
            reste = round(snapshot.protein_target_g - snapshot.protein_g)
            return Reminder(
                kind=kind,
                title="Protéines",
                body=(
                    f"{round(snapshot.protein_g)} g notés sur "
                    f"{round(snapshot.protein_target_g)} · il reste {reste} g."
                ),
            )

        case ReminderKind.MEALS:
            if snapshot.meals_logged:
                return None
            return Reminder(kind=kind, title="Repas", body="Rien de noté aujourd'hui.")

        case ReminderKind.WORKOUT:
            # Aucune séance prévue : aucun rappel. C'est `HEAT-12` — attendu seulement si
            # un déclencheur est vrai — et c'est ce qui empêche le rappel du jour de repos.
            if snapshot.workouts_planned == 0:
                return None
            if snapshot.workouts_logged >= snapshot.workouts_planned:
                return None
            return Reminder(kind=kind, title="Séance prévue", body="Rien de noté aujourd'hui.")


def parse_slots(raw: str) -> tuple[time, ...]:
    """Lit une liste de créneaux `HH:MM`, séparés par des virgules.

    Le même format que `hydration_presets_ml`, et pour la même raison : un réglage qui
    porte plusieurs valeurs se lit et se corrige dans un tableur sans connaître le schéma.
    Les horaires illisibles sont **écartés un par un** — une virgule en trop ne doit pas
    éteindre les contrôles qui, eux, sont corrects.

    Le tri n'est pas cosmétique : `pending` rend les contrôles dans l'ordre du fichier, et
    un réglage écrit « 22:30,14:00 » ferait examiner la fin de journée en premier.
    """
    lus = [parse_slot(chunk) for chunk in raw.split(",")]
    return tuple(sorted(moment for moment in lus if moment is not None))


def pending(
    *,
    slots: Mapping[ReminderKind, tuple[time, ...]],
    now: datetime,
    already_sent: frozenset[Checkpoint],
    grace: timedelta = GRACE,
) -> list[Checkpoint]:
    """Les contrôles dont **l'heure est venue**, sans regarder ce qu'il y aurait à dire.

    Séparé de `due` pour une raison de coût, et elle est mesurable : composer un rappel
    demande de savoir ce qui est noté, donc de lire cinq domaines — à ~180 ms
    l'aller-retour WebDAV. Une passe par minute qui les lirait toutes ferait mille quatre
    cents lectures par jour pour n'envoyer qu'une poignée de notifications. L'ordonnanceur
    appelle donc `pending` d'abord, et ne va chercher l'état du jour que s'il y a quelque
    chose à examiner.

    `now` est un instant **local** — il vient de `app.core.dates.now_local`, jamais d'UTC.
    Le jour d'un rappel est celui qu'affiche l'horloge de l'utilisateur, comme pour une
    prise à 23 h 30 (`HEAT-32`).

    `already_sent` porte les **contrôles** déjà partis ce jour-là, lus dans
    `notifications/sent.csv`. C'est ce qui rend un redémarrage sans effet. Le couple et non
    le type seul : sinon le contrôle d'hydratation de 14 h éteindrait ceux de 18 h et de
    22 h 30.
    """
    ready: list[Checkpoint] = []

    for kind, heures in slots.items():
        for heure in heures:
            checkpoint = Checkpoint(kind=kind, at=heure)
            if checkpoint in already_sent:
                continue

            # Le créneau est situé dans le jour de `now`, donc dans son fuseau. Un créneau
            # de 23 h 30 vu à 00 h 10 le lendemain tombe ainsi *dans le futur* du jour
            # courant et n'est pas dû — ce qui est le comportement voulu : on ne rattrape
            # pas la nuit.
            moment = datetime.combine(now.date(), heure, tzinfo=now.tzinfo)
            retard = now - moment
            if retard < timedelta(0) or retard >= grace:
                continue

            ready.append(checkpoint)

    return ready


def due(
    *,
    slots: Mapping[ReminderKind, tuple[time, ...]],
    now: datetime,
    snapshot: DaySnapshot,
    already_sent: frozenset[Checkpoint],
    grace: timedelta = GRACE,
) -> list[Reminder]:
    """Les rappels à envoyer maintenant : l'heure est venue **et** il y a quelque chose à dire."""
    ready = []
    for checkpoint in pending(slots=slots, now=now, already_sent=already_sent, grace=grace):
        reminder = compose(checkpoint.kind, snapshot)
        if reminder is not None:
            ready.append(reminder)
    return ready


__all__ = [
    "DAILY_CAP",
    "GAP_SHARE",
    "GRACE",
    "SPACING",
    "Checkpoint",
    "DaySnapshot",
    "Reminder",
    "ReminderKind",
    "allowed",
    "compose",
    "due",
    "gap_matters",
    "parse_slot",
    "parse_slots",
    "pending",
]
