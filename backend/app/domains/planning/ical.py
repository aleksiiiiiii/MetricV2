"""Sérialisation iCalendar du planning (`PLAN-05`, RFC 5545).

Un module à part, sans dépôt ni HTTP : on lui passe des séances, il rend du texte. C'est
la même frontière que celle du moteur d'assiduité, et pour la même raison — la justesse
d'un format se vérifie en dix lignes quand rien n'a besoin d'être monté autour.

Quatre règles du format méritent d'être nommées, parce que chacune casse silencieusement
si on l'oublie et qu'aucune ne se voit dans un éditeur de texte.

**Les lignes se terminent par CRLF** (§3.1). Un flux en LF est accepté par certains
clients et rejeté par d'autres ; le symptôme est un calendrier vide sans message.

**Une ligne dépassant 75 octets se plie** (§3.1), et le compte est en **octets, pas en
caractères** : « Épaules » pèse huit octets pour sept caractères. Plier au mauvais endroit
coupe un caractère UTF-8 en deux et rend le fichier illisible. La continuation commence
par une espace, qui ne fait pas partie de la valeur.

**Quatre caractères s'échappent** dans un texte (§3.3.11) : la barre oblique inverse, le
point-virgule, la virgule et le saut de ligne. Une note contenant « série 3, 4, 5 »
produirait sinon trois paramètres là où il n'y en a qu'un.

**Les heures partent en UTC**, avec le `Z` final. L'alternative — une heure locale
accompagnée d'un composant `VTIMEZONE` — demanderait d'embarquer les règles de changement
d'heure d'Europe/Paris dans le flux. Convertir chaque séance depuis son fuseau local est
plus court et tout aussi juste : chaque évènement porte une date concrète, donc un
décalage connu.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.domains.planning.schemas import PlannedSession

#: Identifiant du produit (§3.7.3). La forme est libre ; celle-ci suit la convention
#: `-//organisation//produit//langue`.
PRODID = "-//Metric//Planning sport//FR"

#: Longueur maximale d'une ligne, **en octets**, continuation comprise (§3.1).
LINE_OCTETS = 75

#: Intervalle de rafraîchissement suggéré aux clients abonnés.
#:
#: Deux propriétés pour la même idée : `REFRESH-INTERVAL` est celle de la RFC 7986,
#: `X-PUBLISHED-TTL` est l'extension qu'Outlook et de vieux clients lisent encore. Les
#: écrire toutes les deux coûte deux lignes et évite un calendrier qui ne se met à jour
#: qu'une fois par jour.
REFRESH = "PT1H"

#: Libellés des natures de séance, pour le titre et les catégories.
KIND_LABELS = {"course": "Course", "muscu": "Muscu", "autre": "Séance"}


def escape_text(value: str) -> str:
    """Échappe une valeur textuelle (§3.3.11).

    L'ordre compte : la barre oblique inverse d'abord, sinon on échapperait celles qu'on
    vient d'introduire.
    """
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def fold(line: str) -> list[str]:
    """Découpe une ligne à 75 octets, sans jamais couper un caractère en deux (§3.1).

    On mesure en octets et on découpe en caractères — c'est tout le piège. Un compte en
    caractères laisserait passer des lignes trop longues dès qu'un accent apparaît, et un
    découpage en octets produirait des séquences UTF-8 invalides.
    """
    if len(line.encode("utf-8")) <= LINE_OCTETS:
        return [line]

    pieces: list[str] = []
    current = ""
    # La première ligne dispose des 75 octets ; les suivantes en perdent un pour
    # l'espace de continuation.
    budget = LINE_OCTETS

    for char in line:
        width = len(char.encode("utf-8"))
        if len(current.encode("utf-8")) + width > budget:
            pieces.append(current)
            current = ""
            budget = LINE_OCTETS - 1
        current += char

    if current:
        pieces.append(current)
    return [pieces[0], *(f" {piece}" for piece in pieces[1:])]


def _property(name: str, value: str, *, params: str = "") -> list[str]:
    return fold(f"{name}{params}:{value}")


def _utc(moment: datetime) -> str:
    """Horodatage UTC à la forme `AAAAMMJJTHHMMSSZ` (§3.3.5)."""
    return moment.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")


def _day(value: date) -> str:
    return value.strftime("%Y%m%d")


def _read_time(raw: str | None) -> time | None:
    """Lit `HH:MM`, ou rend `None`.

    Rendre `None` plutôt que lever : une cellule `time` abîmée doit coûter l'heure de sa
    séance, pas le flux entier. C'est la règle de la famille *planning* appliquée au
    format de sortie.
    """
    if not raw:
        return None
    try:
        hours, _, minutes = raw.strip().partition(":")
        return time(int(hours), int(minutes))
    except ValueError:
        return None


def _summary(session: PlannedSession) -> str:
    label = KIND_LABELS.get(session.kind, KIND_LABELS["autre"])
    title = session.title.strip()
    if not title:
        return label
    # Le préfixe rend l'évènement lisible dans une liste où le planning se mélange à
    # tout le reste de l'agenda — c'est justement ce qu'un abonnement produit.
    return title if title.lower().startswith(label.lower()) else f"{label} · {title}"


def event_lines(session: PlannedSession, *, stamp: datetime, tz: ZoneInfo) -> list[str]:
    """Un `VEVENT` (§3.6.1)."""
    lines = ["BEGIN:VEVENT"]

    # L'`UID` est l'identifiant **stable** de la séance, jamais sa position dans le
    # fichier : un calendrier abonné reconnaît un évènement à son `UID`, et le voir
    # changer lui ferait recréer toutes les séances suivantes à chaque suppression.
    lines += _property("UID", f"{session.session_id}@metric")
    lines += _property("DTSTAMP", _utc(stamp))

    moment = _read_time(session.time)
    if moment is None:
        # Séance sans heure : évènement « toute la journée ». `DTEND` est **exclusif**
        # (§3.6.1), d'où le lendemain — sans quoi la séance occuperait deux jours.
        lines += _property("DTSTART", _day(session.date), params=";VALUE=DATE")
        lines += _property("DTEND", _day(session.date + timedelta(days=1)), params=";VALUE=DATE")
    else:
        start = datetime.combine(session.date, moment, tzinfo=tz)
        lines += _property("DTSTART", _utc(start))
        if session.duration_min > 0:
            lines += _property("DTEND", _utc(start + timedelta(minutes=session.duration_min)))
        # Durée inconnue — ce que seule une édition à la main du CSV peut produire : on
        # dit quand la séance commence et rien d'autre. La RFC l'autorise (§3.6.1), et
        # inventer une heure de fin serait inventer une donnée.

    lines += _property("SUMMARY", escape_text(_summary(session)))
    if session.note:
        lines += _property("DESCRIPTION", escape_text(session.note))
    if session.workout_url:
        # `URL` est une propriété standard d'un `VEVENT` (§3.8.4.6), et les calendriers
        # l'affichent en lien ouvrable. Conséquence concrète : une séance prévue s'ouvre
        # dans Cadence **depuis le calendrier iOS**, sans passer par Metric — c'est
        # probablement le chemin le plus emprunté du lot, pour une ligne.
        #
        # Elle n'est pas échappée comme du texte : la RFC la type `URI`, où le
        # point-virgule et la virgule ne sont pas des séparateurs.
        lines += _property("URL", session.workout_url)
    lines += _property("CATEGORIES", escape_text(KIND_LABELS.get(session.kind, "Séance")))
    # Une séance planifiée n'occupe pas l'agenda comme un rendez-vous professionnel :
    # `TRANSP:TRANSPARENT` évite qu'elle fasse apparaître la journée comme indisponible.
    lines.append("TRANSP:TRANSPARENT")

    lines.append("END:VEVENT")
    return lines


def render(
    sessions: Iterable[PlannedSession],
    *,
    stamp: datetime,
    tz: ZoneInfo,
    name: str = "Metric — Planning",
) -> str:
    """Rend un calendrier complet, prêt à être servi.

    `stamp` et `tz` sont passés plutôt que lus : ce module ne connaît ni horloge ni
    configuration, ce qui le rend vérifiable sur des valeurs fixes.
    """
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        *_property("X-WR-CALNAME", escape_text(name)),
        *_property("NAME", escape_text(name)),
        f"X-PUBLISHED-TTL:{REFRESH}",
        f"REFRESH-INTERVAL;VALUE=DURATION:{REFRESH}",
    ]

    for session in sessions:
        lines += event_lines(session, stamp=stamp, tz=tz)

    lines.append("END:VCALENDAR")
    # CRLF partout, y compris à la toute fin : un flux qui ne se termine pas par une fin
    # de ligne est un flux tronqué pour un analyseur strict.
    return "\r\n".join(lines) + "\r\n"
