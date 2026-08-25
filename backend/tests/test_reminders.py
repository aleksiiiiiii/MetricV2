"""Ce qu'un rappel dit, et quand il part (`NOT-02`, `NOT-03`, `L15-06`).

Deux batteries dans ce fichier, et la frontière est celle du code :

* **le module pur** — `reminders.py` — se vérifie sur des valeurs fixes, sans application,
  sans fichier, sans horloge. C'est là que vit la règle qui gouverne le lot ;
* **l'ordonnanceur** — `scheduler.py` — se vérifie contre le faux WebDAV et le faux service
  push, avec une horloge fournie. Il ne dort jamais : `tick()` fait une passe.

Le test le plus important du fichier est `test_un_rappel_ne_dit_jamais_ce_qui_na_pas_ete_fait`.
Les autres décrivent le mécanisme ; celui-là garde l'invariant.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.domains.notifications.reminders import (
    GRACE,
    LEAD,
    PRAISE_CAP,
    Checkpoint,
    DaySnapshot,
    Reminder,
    ReminderKind,
    compose,
    due,
    parse_slot,
    parse_slots,
    pending,
)


def pour(kind: ReminderKind, heure: str = "12:00") -> Checkpoint:
    """Un contrôle, pour composer un message hors de tout ordonnanceur.

    L'heure ne compte que pour `WORKOUT_SOON`, qui nomme la séance qui commence quinze
    minutes plus tard. Les autres types l'ignorent, et un défaut évite de la répéter
    trente fois.
    """
    lu = parse_slot(heure)
    assert lu is not None
    return Checkpoint(kind=kind, at=lu)


PARIS = ZoneInfo("Europe/Paris")


def moment(hour: int, minute: int = 0, day: date | None = None) -> datetime:
    return datetime.combine(day or date(2026, 8, 13), time(hour, minute), tzinfo=PARIS)


def slots(**kwargs: str | None) -> dict[ReminderKind, tuple[time, ...]]:
    """Créneaux, écrits en `HH:MM` comme dans `settings.csv`.

    Une **liste** par type depuis N2 : l'hydratation en porte trois, les autres un. La
    forme est la même pour tous, il n'y a pas deux façons de lire un réglage.
    """
    return {kind: parse_slots(kwargs.get(kind.value) or "") for kind in ReminderKind}


def sent(kind: ReminderKind, heure: str) -> Checkpoint:
    """Un contrôle déjà parti, tel que `sent.csv` le rend."""
    lu = parse_slot(heure)
    assert lu is not None
    return Checkpoint(kind=kind, at=lu)


# ═══ Ce qu'un rappel a le droit de dire ═══════════════


class TestCeQuUnRappelDit:
    """La règle du lot : **ce qui n'est pas noté**, jamais ce qui n'a pas été fait."""

    #: Formes qui affirment quelque chose sur l'utilisateur. Aucune ne doit apparaître,
    #: dans aucun rappel, quel que soit l'état du jour.
    INTERDITS = (
        "tu n'as pas",
        "tu as oublié",
        "tu as sauté",
        "tu n'as rien",
        "raté",
        "manqué",
        "oubli",
    )

    @pytest.mark.parametrize(
        "kind,snapshot",
        [
            (
                ReminderKind.SUPPLEMENTS,
                DaySnapshot(supplements_pending=("créatine", "whey")),
            ),
            (ReminderKind.HYDRATION, DaySnapshot(hydration_ml=0, hydration_target_ml=2000)),
            (ReminderKind.HYDRATION, DaySnapshot(hydration_ml=750, hydration_target_ml=2000)),
            (ReminderKind.MEALS, DaySnapshot(meals_logged=0)),
            (ReminderKind.WORKOUT, DaySnapshot(workouts_planned=1, workouts_logged=0)),
        ],
    )
    def test_un_rappel_ne_dit_jamais_ce_qui_na_pas_ete_fait(
        self, kind: ReminderKind, snapshot: DaySnapshot
    ) -> None:
        """« Tu n'as pas bu aujourd'hui » est une **affirmation fausse**.

        L'application sait seulement que rien n'a été consigné. C'est « aucune valeur
        inventée à l'écran » appliqué à une notification — et le cas difficile, parce
        qu'une notification est lue en trois mots sur un écran verrouillé.
        """
        reminder = compose(pour(kind), snapshot)
        assert reminder is not None

        texte = f"{reminder.title} {reminder.body}".lower()
        for interdit in self.INTERDITS:
            assert interdit not in texte, f"« {interdit} » dans : {reminder.body}"

    def test_le_vocabulaire_est_celui_du_relevé(self) -> None:
        """Chaque rappel parle de ce qui est **noté**, dans ces mots-là."""
        for kind, snapshot in (
            (ReminderKind.HYDRATION, DaySnapshot(hydration_target_ml=2000)),
            (ReminderKind.MEALS, DaySnapshot()),
            (ReminderKind.WORKOUT, DaySnapshot(workouts_planned=1)),
        ):
            reminder = compose(pour(kind), snapshot)
            assert reminder is not None
            assert "not" in reminder.body.lower(), reminder.body

    def test_un_chiffre_relevé_se_cite_tel_quel(self) -> None:
        """750 ml **notés** est une mesure : elle est vraie, et elle est utile.

        C'est l'absence qu'on n'a pas le droit d'affirmer, pas le relevé.
        """
        reminder = compose(
            pour(ReminderKind.HYDRATION), DaySnapshot(hydration_ml=750, hydration_target_ml=2000)
        )
        assert reminder is not None
        assert "750" in reminder.body
        assert "2000" in reminder.body

    def test_les_suppléments_ne_citent_que_ce_qui_reste(self) -> None:
        """`SupplementService.checklist` sait déjà ce qui est pris.

        Le rappel ne nomme donc que ce qui n'est pas noté — citer la créatine déjà cochée
        serait faux, et suffirait à faire désinstaller le rappel.
        """
        reminder = compose(
            pour(ReminderKind.SUPPLEMENTS), DaySnapshot(supplements_pending=("whey", "magnésium"))
        )
        assert reminder is not None
        assert "whey" in reminder.body
        assert "magnésium" in reminder.body
        assert "créatine" not in reminder.body

    def test_une_longue_liste_est_bornée(self) -> None:
        """Une notification tronquée à quelques mots n'apprend rien de plus avec huit noms."""
        reminder = compose(
            pour(ReminderKind.SUPPLEMENTS),
            DaySnapshot(supplements_pending=("a", "b", "c", "d", "e")),
        )
        assert reminder is not None
        assert "et 2 autres" in reminder.body


class TestQuandIlNyARienADire:
    """Un rappel qui part tous les jours cesse d'être lu — et emporte les autres."""

    def test_tous_les_suppléments_notés_ne_déclenchent_rien(self) -> None:
        assert compose(pour(ReminderKind.SUPPLEMENTS), DaySnapshot(supplements_pending=())) is None

    def test_objectif_dhydratation_atteint_ne_déclenche_rien(self) -> None:
        snapshot = DaySnapshot(hydration_ml=2000, hydration_target_ml=2000)
        assert compose(pour(ReminderKind.HYDRATION), snapshot) is None

    def test_un_repas_noté_suffit(self) -> None:
        assert compose(pour(ReminderKind.MEALS), DaySnapshot(meals_logged=1)) is None

    def test_aucun_rappel_de_séance_sans_séance_prévue(self) -> None:
        """C'est la cadence `conditional` de `HEAT-12`, appliquée à un rappel.

        Rappeler une séance un jour de repos est exactement le rappel qu'on désinstalle.
        """
        assert compose(pour(ReminderKind.WORKOUT), DaySnapshot(workouts_planned=0)) is None
        assert (
            compose(pour(ReminderKind.WORKOUT), DaySnapshot(workouts_planned=0, workouts_logged=0))
            is None
        )

    def test_une_séance_notée_ferme_le_rappel(self) -> None:
        snapshot = DaySnapshot(workouts_planned=1, workouts_logged=1)
        assert compose(pour(ReminderKind.WORKOUT), snapshot) is None


# ═══ Les créneaux ═════════════════════════════════════


class TestLesCréneaux:
    def test_un_horaire_illisible_vaut_éteint(self) -> None:
        """Le seul repli acceptable : une valeur par défaut réveillerait quelqu'un."""
        for brut in ("", "   ", "vingt heures", "25:00", "20h00", "-1:00", "20:99"):
            assert parse_slot(brut) is None, brut

    def test_un_horaire_lisible_est_lu_à_la_minute(self) -> None:
        assert parse_slot("20:00") == time(20, 0)
        assert parse_slot(" 07:05 ") == time(7, 5)
        # Les secondes n'ont pas de sens dans un créneau et fausseraient le retard.
        assert parse_slot("20:00:45") == time(20, 0)

    def test_rien_nest_dû_avant_lheure(self) -> None:
        assert (
            pending(slots=slots(hydration="20:00"), now=moment(19, 59), already_sent=frozenset())
            == []
        )

    def test_le_créneau_est_dû_à_lheure_pile(self) -> None:
        attendus = pending(
            slots=slots(hydration="20:00"), now=moment(20, 0), already_sent=frozenset()
        )
        assert attendus == [sent(ReminderKind.HYDRATION, "20:00")]

    def test_un_redémarrage_dans_lheure_rattrape(self) -> None:
        """Un serveur relancé à 20 h 05 délivre le rappel de 20 h."""
        attendus = pending(
            slots=slots(hydration="20:00"), now=moment(20, 59), already_sent=frozenset()
        )
        assert attendus == [sent(ReminderKind.HYDRATION, "20:00")]

    def test_au_delà_dune_heure_le_rappel_est_abandonné(self) -> None:
        """Perdre un rappel coûte moins qu'en recevoir un au coucher."""
        attendus = pending(
            slots=slots(hydration="20:00"), now=moment(21, 0), already_sent=frozenset()
        )
        assert attendus == []

    def test_on_ne_rattrape_pas_la_nuit(self) -> None:
        """Un créneau de 23 h 30 vu à 00 h 10 le lendemain n'est pas dû.

        Le créneau est situé dans le jour de `now` : il y tombe donc *dans le futur*, ce
        qui est exactement le comportement voulu.
        """
        attendus = pending(
            slots=slots(hydration="23:30"),
            now=moment(0, 10, day=date(2026, 8, 14)),
            already_sent=frozenset(),
        )
        assert attendus == []

    def test_un_créneau_éteint_nest_jamais_dû(self) -> None:
        assert pending(slots=slots(), now=moment(20, 0), already_sent=frozenset()) == []

    def test_ce_qui_est_déjà_parti_ne_repart_pas(self) -> None:
        """C'est ce qui rend un redémarrage sans effet — la mémoire est un fichier."""
        attendus = pending(
            slots=slots(hydration="20:00"),
            now=moment(20, 5),
            already_sent=frozenset({sent(ReminderKind.HYDRATION, "20:00")}),
        )
        assert attendus == []

    def test_la_fenêtre_est_bien_dune_heure(self) -> None:
        assert GRACE.total_seconds() == 3600


class TestDue:
    """`due` = l'heure est venue **et** il y a quelque chose à dire."""

    def test_lheure_venue_sans_rien_à_dire_ne_produit_rien(self) -> None:
        rappels = due(
            slots=slots(meals="12:00"),
            now=moment(12, 0),
            snapshot=DaySnapshot(meals_logged=3),
            already_sent=frozenset(),
        )
        assert rappels == []

    def test_deux_créneaux_simultanés_partent_tous_les_deux(self) -> None:
        rappels = due(
            slots=slots(meals="12:00", hydration="12:00"),
            now=moment(12, 0),
            snapshot=DaySnapshot(meals_logged=0, hydration_target_ml=2000),
            already_sent=frozenset(),
        )
        assert {r.kind for r in rappels} == {ReminderKind.MEALS, ReminderKind.HYDRATION}

    def test_la_charge_utile_porte_un_tag_par_type(self) -> None:
        """Deux rappels du même type se remplacent au lieu de s'empiler."""
        rappels = due(
            slots=slots(meals="12:00"),
            now=moment(12, 0),
            snapshot=DaySnapshot(meals_logged=0),
            already_sent=frozenset(),
        )
        assert rappels[0].payload()["tag"] == "meals"


# ═══ Une séance annoncée un quart d'heure avant (**N3**) ═══


class TestSeanceImminente:
    """Le déclencheur ne vient plus des réglages mais du **planning** : c'est l'heure
    qu'on a posée au calendrier, et elle change d'un jour à l'autre."""

    ETAT = DaySnapshot(
        workouts_planned=1,
        workouts_logged=0,
        sessions_at=((time(18, 0), "Haut du corps", ""),),
    )

    def test_elle_nomme_la_séance_et_son_heure(self) -> None:
        """Le titre tel qu'il est au planning : c'est ce que l'utilisateur a écrit, et il
        le reconnaît. Rien n'est ajouté."""
        rappel = compose(pour(ReminderKind.WORKOUT_SOON, "17:45"), self.ETAT)

        assert rappel is not None
        assert rappel.title == "Séance dans 15 min"
        assert rappel.body == "Haut du corps · 18:00."

    def test_deux_séances_le_même_jour_ne_se_confondent_pas(self) -> None:
        """**Le test qui justifie que `compose` prenne le contrôle et non le type.** Sans
        l'heure, le rappel de 17 h 45 pourrait nommer la séance de 20 h."""
        etat = DaySnapshot(
            workouts_planned=2,
            workouts_logged=0,
            sessions_at=((time(18, 0), "Haut du corps", ""), (time(20, 0), "Gainage", "")),
        )

        premier = compose(pour(ReminderKind.WORKOUT_SOON, "17:45"), etat)
        second = compose(pour(ReminderKind.WORKOUT_SOON, "19:45"), etat)

        assert premier is not None and "Haut du corps" in premier.body
        assert second is not None and "Gainage" in second.body

    def test_une_séance_retirée_du_planning_se_tait(self) -> None:
        """Elle a pu être supprimée entre la construction du contrôle et l'envoi. On
        n'annonce pas une séance qui n'est plus prévue."""
        assert compose(pour(ReminderKind.WORKOUT_SOON, "17:45"), DaySnapshot()) is None

    def test_une_séance_déjà_notée_ne_sannonce_pas(self) -> None:
        """On n'annonce pas ce qui vient d'être fait — le cas de qui s'entraîne en avance
        et note tout de suite."""
        etat = DaySnapshot(
            workouts_planned=1,
            workouts_logged=1,
            sessions_at=((time(18, 0), "Haut du corps", ""),),
        )

        assert compose(pour(ReminderKind.WORKOUT_SOON, "17:45"), etat) is None

    def test_lavance_est_bien_dun_quart_dheure(self) -> None:
        """De quoi enfiler des chaussures, pas de quoi oublier entre la notification et la
        séance."""
        assert LEAD.total_seconds() == 900

    def test_une_séance_à_minuit_dix_sannonce_la_veille_au_soir(self) -> None:
        """Cas limite du recul d'un quart d'heure : le contrôle tombe le jour d'avant.

        Il n'est alors **jamais dû** — `pending` situe les créneaux dans le jour de `now`,
        et un contrôle à 23 h 55 vu à 00 h 10 tombe dans le futur. La séance de 00 h 10
        n'est pas annoncée, et c'est le comportement voulu : on ne notifie pas la nuit.
        """
        etat = DaySnapshot(workouts_planned=1, sessions_at=((time(0, 10), "Nuit blanche", ""),))

        rappel = compose(pour(ReminderKind.WORKOUT_SOON, "23:55"), etat)

        assert rappel is not None
        assert rappel.body == "Nuit blanche · 00:10."


# ═══ Le ton de fin de journée (**N4**) ════════════════


class TestSeanceNonNotee:
    """Ferme, et chaque mot vrai. « Tu as sauté ta séance » resterait faux à 21 h :
    l'application sait seulement que rien n'est noté."""

    def test_elle_cite_lheure_prévue(self) -> None:
        etat = DaySnapshot(
            workouts_planned=1,
            workouts_logged=0,
            sessions_at=((time(18, 0), "Haut du corps", ""),),
        )

        rappel = compose(pour(ReminderKind.WORKOUT), etat)

        assert rappel is not None
        assert rappel.body == "Séance de 18:00 : toujours rien de noté. Il te reste la soirée."

    def test_sans_heure_elle_reste_juste(self) -> None:
        """Une séance sans heure au planning est un cas courant (`PLAN-02`)."""
        rappel = compose(pour(ReminderKind.WORKOUT), DaySnapshot(workouts_planned=1))

        assert rappel is not None
        assert rappel.body == "Séance prévue : toujours rien de noté. Il te reste la soirée."

    def test_le_mot_qui_la_rend_vraie_est_là(self) -> None:
        """« toujours rien » se lirait comme « tu n'as rien fait ». « toujours rien **de
        noté** » dit la même chose sans affirmer."""
        rappel = compose(pour(ReminderKind.WORKOUT), DaySnapshot(workouts_planned=1))

        assert rappel is not None
        assert "de noté" in rappel.body


# ═══ Où mène chaque notification (**N6**) ═════════════


class TestDestinations:
    """Toutes ouvraient l'accueil : taper « Suppléments — pas encore noté : créatine » y
    menait, et il restait deux gestes pour arriver là où l'on note la prise."""

    def test_chaque_type_mène_à_son_écran(self) -> None:
        attendus = {
            ReminderKind.SUPPLEMENTS: "/routine",
            ReminderKind.HYDRATION: "/routine",
            ReminderKind.MEALS: "/nutrition",
            ReminderKind.PROTEIN: "/nutrition",
            ReminderKind.WORKOUT: "/activite",
        }
        for kind, ecran in attendus.items():
            rappel = Reminder(kind=kind, title="x", body="y")
            assert rappel.payload()["url"] == ecran, kind

    def test_aucun_type_noublie_sa_destination(self) -> None:
        """Le repli sur l'accueil existe pour le jour où l'on ajoute un type sans y
        penser — il ne doit servir à aucun type d'aujourd'hui."""
        for kind in ReminderKind:
            assert Reminder(kind=kind, title="x", body="y").payload()["url"] != "/"

    def test_une_séance_avec_lien_ouvre_la_séance(self) -> None:
        """**Le seul rappel qui remplace toute la navigation.**"""
        lien = "https://cadence.exemple.fr?w=Gainage~2~60~Plank:60s:30"
        etat = DaySnapshot(workouts_planned=1, sessions_at=((time(18, 0), "Gainage", lien),))

        rappel = compose(pour(ReminderKind.WORKOUT_SOON, "17:45"), etat)

        assert rappel is not None
        assert rappel.payload()["url"] == lien

    def test_une_séance_sans_lien_ouvre_lactivité(self) -> None:
        etat = DaySnapshot(workouts_planned=1, sessions_at=((time(18, 0), "Gainage", ""),))

        rappel = compose(pour(ReminderKind.WORKOUT_SOON, "17:45"), etat)

        assert rappel is not None
        assert rappel.payload()["url"] == "/activite"


# ═══ Les félicitations (**N5**) ═══════════════════════


class TestFelicitations:
    """Sur un fait chiffré, jamais sur un compliment."""

    def test_elle_dit_le_fait_tel_quel(self) -> None:
        etat = DaySnapshot(feats=("12,4 km — ta plus longue sortie.",))

        rappel = compose(pour(ReminderKind.PRAISE), etat)

        assert rappel is not None
        assert rappel.title == "Bravo"
        assert rappel.body == "12,4 km — ta plus longue sortie."

    def test_sans_fait_elle_se_tait(self) -> None:
        """« Bravo pour ta performance » cesse d'être lu en trois jours et emporte avec
        lui les fois où c'était mérité."""
        assert compose(pour(ReminderKind.PRAISE), DaySnapshot()) is None

    def test_le_plus_fort_part_et_les_autres_se_taisent(self) -> None:
        """Une félicitation en retard d'un jour ne félicite plus rien : les suivantes ne
        sont pas reportées, elles disparaissent."""
        etat = DaySnapshot(feats=("Le plus fort.", "Le second.", "Le troisième."))

        rappel = compose(pour(ReminderKind.PRAISE), etat)

        assert rappel is not None
        assert rappel.body == "Le plus fort."

    def test_le_plafond_est_de_quatre_par_semaine(self) -> None:
        assert PRAISE_CAP == 4
