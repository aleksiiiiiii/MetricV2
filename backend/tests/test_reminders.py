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
    DaySnapshot,
    ReminderKind,
    compose,
    due,
    parse_slot,
    pending,
)

PARIS = ZoneInfo("Europe/Paris")


def moment(hour: int, minute: int = 0, day: date | None = None) -> datetime:
    return datetime.combine(day or date(2026, 8, 13), time(hour, minute), tzinfo=PARIS)


def slots(**kwargs: str | None) -> dict[ReminderKind, time | None]:
    """Créneaux, écrits en `HH:MM` comme dans `settings.csv`."""
    return {kind: parse_slot(kwargs.get(kind.value) or "") for kind in ReminderKind}


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
        reminder = compose(kind, snapshot)
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
            reminder = compose(kind, snapshot)
            assert reminder is not None
            assert "not" in reminder.body.lower(), reminder.body

    def test_un_chiffre_relevé_se_cite_tel_quel(self) -> None:
        """750 ml **notés** est une mesure : elle est vraie, et elle est utile.

        C'est l'absence qu'on n'a pas le droit d'affirmer, pas le relevé.
        """
        reminder = compose(
            ReminderKind.HYDRATION, DaySnapshot(hydration_ml=750, hydration_target_ml=2000)
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
            ReminderKind.SUPPLEMENTS, DaySnapshot(supplements_pending=("whey", "magnésium"))
        )
        assert reminder is not None
        assert "whey" in reminder.body
        assert "magnésium" in reminder.body
        assert "créatine" not in reminder.body

    def test_une_longue_liste_est_bornée(self) -> None:
        """Une notification tronquée à quelques mots n'apprend rien de plus avec huit noms."""
        reminder = compose(
            ReminderKind.SUPPLEMENTS,
            DaySnapshot(supplements_pending=("a", "b", "c", "d", "e")),
        )
        assert reminder is not None
        assert "et 2 autres" in reminder.body


class TestQuandIlNyARienADire:
    """Un rappel qui part tous les jours cesse d'être lu — et emporte les autres."""

    def test_tous_les_suppléments_notés_ne_déclenchent_rien(self) -> None:
        assert compose(ReminderKind.SUPPLEMENTS, DaySnapshot(supplements_pending=())) is None

    def test_objectif_dhydratation_atteint_ne_déclenche_rien(self) -> None:
        snapshot = DaySnapshot(hydration_ml=2000, hydration_target_ml=2000)
        assert compose(ReminderKind.HYDRATION, snapshot) is None

    def test_un_repas_noté_suffit(self) -> None:
        assert compose(ReminderKind.MEALS, DaySnapshot(meals_logged=1)) is None

    def test_aucun_rappel_de_séance_sans_séance_prévue(self) -> None:
        """C'est la cadence `conditional` de `HEAT-12`, appliquée à un rappel.

        Rappeler une séance un jour de repos est exactement le rappel qu'on désinstalle.
        """
        assert compose(ReminderKind.WORKOUT, DaySnapshot(workouts_planned=0)) is None
        assert (
            compose(ReminderKind.WORKOUT, DaySnapshot(workouts_planned=0, workouts_logged=0))
            is None
        )

    def test_une_séance_notée_ferme_le_rappel(self) -> None:
        snapshot = DaySnapshot(workouts_planned=1, workouts_logged=1)
        assert compose(ReminderKind.WORKOUT, snapshot) is None


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
        assert attendus == [ReminderKind.HYDRATION]

    def test_un_redémarrage_dans_lheure_rattrape(self) -> None:
        """Un serveur relancé à 20 h 05 délivre le rappel de 20 h."""
        attendus = pending(
            slots=slots(hydration="20:00"), now=moment(20, 59), already_sent=frozenset()
        )
        assert attendus == [ReminderKind.HYDRATION]

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
            already_sent=frozenset({ReminderKind.HYDRATION}),
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
