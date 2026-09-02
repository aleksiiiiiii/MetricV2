"""Ce que l'assistant reçoit vraiment — les tranches de contexte (`IA-09`, `IA-16`).

Ce fichier vérifie **ce qui part au modèle**, pas ce qu'un service a calculé. C'est la
différence entre « le backend sait » et « l'assistant peut répondre », et c'est exactement
l'écart que le lot vient combler : `/activity/progress` existait depuis longtemps, aucune
tranche ne le servait, et l'assistant ne pouvait pas dire quoi charger lundi.

Trois familles :

1. **Ce qui est servi.** Charges, séries, totaux, hydratation — présents et lisibles.
2. **Ce qui n'est pas inventé.** Une allure absente ne devient pas zéro, et une charge à
   zéro est le poids du corps (`ACT-07`) et non une absence.
3. **La règle du lot.** Toute action d'écriture a sa tranche de lecture, et c'est un test
   structurel plutôt qu'une intention.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from app.core.dates import today_local, tz
from app.domains.activity.models import CircuitExerciseRow, CircuitRow
from app.domains.activity.schemas import (
    ExerciseEntryPayload,
    ExercisePayload,
    RunPayload,
    WorkoutPayload,
)
from app.domains.activity.service import (
    CircuitSessionService,
    ExerciseService,
    RunService,
    WorkoutService,
)
from app.domains.assistant import context, profile
from app.domains.assistant.actions import Level, catalogue
from app.domains.assistant.conversation import Need
from app.domains.body.schemas import WeightPayload
from app.domains.body.service import WeightService
from app.domains.hydration.schemas import IntakePayload
from app.domains.hydration.service import HydrationService
from app.domains.nutrition.service import NutritionService
from app.domains.planning.schemas import AdherenceView, PlanPayload
from app.domains.planning.service import PlanningService
from app.storage.files import FileStore

TODAY = today_local()

#: Un écart plan/réalisé vide. `build` le reçoit **fourni** et ne le recalcule jamais
#: (`PLAN-06`), donc les tests d'ici n'ont pas de planning à monter.
_AUCUN_PLAN = AdherenceView(weeks=[], planned=0, honoured=0, rate=None)
HIER = TODAY - timedelta(days=1)
AVANT_HIER = TODAY - timedelta(days=2)
DEMAIN = TODAY + timedelta(days=1)


async def _exercice(store: FileStore, nom: str, groupe: str = "pectoraux") -> str:
    created = await ExerciseService(store).create(ExercisePayload(name=nom, muscle_group=groupe))
    return created.exercise_id


async def _seance(
    store: FileStore, jour: date, exercise_id: str, *, charge: float, series: int, reps: int
) -> None:
    await WorkoutService(store).create(
        WorkoutPayload(
            date=jour,
            type="muscu",
            duration_min=60,
            rpe=7,
            exercises=[
                ExerciseEntryPayload(
                    exercise_id=exercise_id, weight_kg=charge, sets=series, reps=reps
                )
            ],
        )
    )


async def _tabata(
    store: FileStore,
    jour: date,
    *,
    nom: str = "Haut du corps",
    exercices: Sequence[tuple[str, str]] = (),
    rounds: int = 4,
    reps: int = 8,
    duree: float = 60,
    rpe: int | None = 7,
) -> None:
    """Un circuit **déclaré fait**, écrit par le vrai chemin.

    `_seance` reste au-dessus et sert les deux tranches encore branchées sur l'ancien
    monde — `progression_charges` et `detail_seances`, que la phase 5 supprimera. Tout ce
    qui compte une séance lit celui-ci depuis le rebranchement
    (`docs/refonte-activite.md` §4).
    """
    await CircuitSessionService(store).record(
        CircuitRow(id="c1", name=nom),
        [
            CircuitExerciseRow(
                circuit_id="c1", position=index, name=exo, muscle_group=groupe, reps=reps
            )
            for index, (exo, groupe) in enumerate(exercices, start=1)
        ],
        day=jour,
        rounds=rounds,
        duration_min=duree,
        rpe=rpe,
    )


async def _materiel(store: FileStore, *valeurs: str) -> None:
    """Coche du matériel au profil, par le vrai chemin d'écriture."""
    from app.domains.app_settings.service import SettingsService

    reglages = SettingsService(store)
    await reglages.update_keys({profile.EQUIPMENT: ",".join(valeurs)}, await reglages.token())


async def _rendu(
    store: FileStore, nom: str, *, jour: date | None = None, semaine: bool = False
) -> str:
    """Une tranche, mise à plat — c'est sous cette forme qu'elle atteint le modèle."""
    besoin = Need(nom, jour, semaine)
    return "\n".join(await context.slices(store, [besoin], today=TODAY))


# ── Ce qui est servi ──────────────────────────────────


async def test_la_progression_des_charges_porte_charge_ecart_et_record(store: FileStore) -> None:
    """Le trou du lot : sans ces chiffres, aucune réponse à « je charge combien lundi ? »."""
    exercise_id = await _exercice(store, "Développé couché")
    await _seance(store, AVANT_HIER, exercise_id, charge=60, series=3, reps=8)
    await _seance(store, HIER, exercise_id, charge=62.5, series=3, reps=8)

    rendu = await _rendu(store, "progression_charges")

    assert "Développé couché" in rendu
    assert "62,5 kg" in rendu
    assert "+2.5 kg depuis la fois d'avant" in rendu
    assert "record 62,5 kg" in rendu
    assert "charges par séance : 60 kg, 62,5 kg" in rendu
    # L'identifiant permet d'enchaîner sur une action ; sans lui la tranche informe sans
    # rendre agissable.
    assert f"exercise_id={exercise_id}" in rendu


async def test_le_detail_des_seances_porte_series_repetitions_et_volume(
    store: FileStore,
) -> None:
    exercise_id = await _exercice(store, "Squat", groupe="jambes")
    await _seance(store, HIER, exercise_id, charge=90, series=4, reps=6)

    rendu = await _rendu(store, "detail_seances")

    assert f"Séance du {HIER:%d/%m/%Y}" in rendu
    assert "Squat 4×6 à 90 kg" in rendu
    assert "volume 2160 kg" in rendu


async def test_l_hydratation_du_jour_est_servie_avec_sa_cible(store: FileStore) -> None:
    """`water.add` était au catalogue sans tranche : on écrivait dans l'illisible."""
    await HydrationService(store).create(IntakePayload(volume_ml=500))
    await HydrationService(store).create(IntakePayload(volume_ml=750))

    rendu = await _rendu(store, "hydratation_du_jour")

    assert "1250 ml" in rendu
    assert "cible" in rendu
    # Le restant est **servi**, pas laissé à soustraire. Sans lui, le jeu d'évaluation a
    # mesuré que tout modèle calcule l'écart lui-même — un chiffre qu'aucun service n'a
    # produit, donc invérifiable.
    assert "il reste" in rendu
    # Les prises portent de quoi en corriger une, comme les autres tranches.
    assert "row_id=" in rendu and "token=" in rendu


async def test_un_restant_ne_descend_jamais_sous_zero(store: FileStore) -> None:
    """Cible dépassée : le restant vaut zéro, pas un nombre négatif.

    « Il te reste -500 ml à boire » ne veut rien dire. Le dépassement reste lisible dans le
    volume du jour, comme pour le ratio.
    """
    await HydrationService(store).create(IntakePayload(volume_ml=4000))

    rendu = await _rendu(store, "hydratation_du_jour")

    assert "il reste 0 ml" in rendu
    assert "-" not in rendu.split("il reste")[1][:12]


async def test_les_repas_du_jour_portent_les_totaux_pas_seulement_les_identifiants(
    store: FileStore,
) -> None:
    await NutritionService(store).create(
        meal_type="dejeuner",
        comment=None,
        photo=None,
        protein_g=42.0,
        added_sugar_g=None,
        calories=680,
    )

    rendu = await _rendu(store, "repas_du_jour")

    assert "42 g de protéines" in rendu
    assert "il reste" in rendu
    assert "680 kcal" in rendu
    assert "Repas dejeuner" in rendu


async def test_une_course_porte_son_allure_et_sa_cardio(store: FileStore) -> None:
    await RunService(store).create(
        RunPayload(date=HIER, duration_min=45, distance_km=9.0, avg_hr=148, elevation_m=120)
    )

    rendu = await _rendu(store, "activites_recentes")

    assert "9 km" in rendu
    assert "45 min" in rendu
    assert "FC moyenne 148" in rendu
    assert "dénivelé 120 m" in rendu


async def test_une_seance_porte_son_effort_percu(store: FileStore) -> None:
    """Le RPE se disait « transmis à l'IA » sans l'être. Il l'est, et depuis
    `circuit_sessions.csv` où la déclaration le pose."""
    await _tabata(store, HIER, exercices=[("Tractions", "dos")])

    assert "effort perçu 7/10" in await _rendu(store, "activites_recentes")


# ── Ce qui n'est pas inventé ──────────────────────────


async def test_une_charge_nulle_est_le_poids_du_corps_et_non_une_absence(
    store: FileStore,
) -> None:
    """`ACT-07` : `weight_kg = 0` est une valeur légitime.

    Rendre « 0 kg » inviterait le modèle à lire une charge nulle là où il y a eu des
    tractions — et à conseiller « augmente la charge » sur un exercice qui n'en porte pas.
    """
    exercise_id = await _exercice(store, "Tractions", groupe="dos")
    await _seance(store, HIER, exercise_id, charge=0, series=4, reps=8)

    rendu = await _rendu(store, "progression_charges") + await _rendu(store, "detail_seances")

    assert "poids du corps" in rendu
    assert "0 kg" not in rendu


async def test_un_detail_non_releve_ne_devient_pas_zero(store: FileStore) -> None:
    """Une allure absente ne s'écrit pas — elle ne vaut pas zéro."""
    await RunService(store).create(RunPayload(date=HIER, duration_min=30, distance_km=5.0))

    rendu = await _rendu(store, "activites_recentes")

    assert "5 km" in rendu
    assert "FC moyenne" not in rendu
    assert "dénivelé" not in rendu
    assert "cadence" not in rendu


async def test_les_tranches_vides_disent_l_absence_sans_chiffre_invente(
    store: FileStore,
) -> None:
    assert "aucun exercice relevé" in await _rendu(store, "progression_charges")
    assert "aucune série relevée" in await _rendu(store, "detail_seances")
    assert "Prises du" in await _rendu(store, "hydratation_du_jour")
    assert "aucun" in await _rendu(store, "repas_du_jour")


# ── La règle du lot ───────────────────────────────────

#: **Toute action d'écriture a sa tranche de lecture.** Le lot est né de trois violations :
#: `water.add` sans hydratation lisible, `meal.add` sans les macros, `workout.add` sans les
#: charges. Cette table rend la règle vérifiable — une action ajoutée sans sa tranche fait
#: échouer le test suivant plutôt que de rouvrir l'angle mort en silence.
LECTURE_PAR_ECRITURE = {
    "weight.add": "pesees_recentes",
    "weight.delete": "pesees_recentes",
    "water.add": "hydratation_du_jour",
    "meal.add": "repas_du_jour",
    "meal.delete": "repas_du_jour",
    "run.add": "activites_recentes",
    "run.delete": "activites_recentes",
    "workout.add": "activites_recentes",
    "workout.delete": "activites_recentes",
    "exercise.create": "exercices",
    # Sa tranche porte deux choses : les séances déjà enregistrées, et les 35 noms qui
    # affichent une illustration dans Cadence. Sans elle, un modèle inventerait « Pompes »
    # — qui tourne, mais sans image — ou pire « Push-Ups », qui en affiche une fausse.
    "circuit.create": "seances_cadence",
    "supplement.take": "supplements_du_jour",
    "plan.add": "planning_a_venir",
    "plan.delete": "planning_a_venir",
}


def test_toute_action_du_catalogue_a_sa_tranche_de_lecture() -> None:
    manquantes = sorted(set(catalogue()) - set(LECTURE_PAR_ECRITURE))
    assert not manquantes, f"actions sans tranche de lecture déclarée : {manquantes}"

    inconnues = sorted(set(LECTURE_PAR_ECRITURE.values()) - set(context.SLICES))
    assert not inconnues, f"tranches déclarées mais absentes de SLICES : {inconnues}"


def test_une_suppression_lit_la_tranche_qui_porte_les_jetons() -> None:
    """Une suppression exige un jeton (`STO-05`), et le jeton vient d'une tranche.

    C'est la boucle que `context.py` referme en commentaire : « il ne peut donc pas effacer
    une ligne qu'il n'a pas lue ». Sans tranche associée, l'action serait indemandable.
    """
    for nom, spec in catalogue().items():
        if spec.level is Level.CHANGE:
            assert LECTURE_PAR_ECRITURE[nom] in context.SLICES


# ── Le bloc « aujourd'hui », servi d'office (lot 12.A) ──
#
# Il était une tranche à la demande : « j'ai assez bu ? » coûtait une seconde passe, donc
# un appel modèle entier, sur la question la plus banale de l'application.


async def _aujourdhui(store: FileStore) -> str:
    return "\n".join(await context.today_lines(store, TODAY))


async def test_un_jour_vide_ne_rend_aucun_zero_qui_passerait_pour_une_mesure(
    store: FileStore,
) -> None:
    """L'invariant du dépôt, appliqué au prompt.

    Un zéro affiché pour une mesure absente est ce que « aucune valeur inventée » interdit,
    et il s'attrape **moins bien** ici qu'à l'écran : personne ne relit une consigne.
    """
    rendu = await _aujourdhui(store)

    assert "rien de noté" in rendu
    assert "aucun repas noté" in rendu
    assert "0 ml sur une cible" not in rendu
    assert "0 g de protéines sur" not in rendu


async def test_un_jour_vide_rappelle_quand_meme_les_cibles(store: FileStore) -> None:
    """Dire « rien de noté » sans dire ce qui est visé n'aide pas un coach à conseiller.

    C'est la même règle que l'état vide d'un écran : il dit ce que coûte le prochain
    geste, il ne se contente pas d'annoncer l'absence.
    """
    rendu = await _aujourdhui(store)

    assert "cible" in rendu
    assert "cibles" in rendu


async def test_l_eau_du_jour_part_sans_qu_on_la_demande(store: FileStore) -> None:
    await HydrationService(store).create(IntakePayload(volume_ml=600))

    rendu = await _aujourdhui(store)

    assert "hydratation : 600 ml" in rendu
    assert "il reste" in rendu


async def test_les_exercices_du_jour_partent_avec_leurs_series(store: FileStore) -> None:
    """« Les exos » de la demande : ce que la séance a contenu, exercice par exercice.

    **Sans charge**, et c'est une décision (**C4**) : `circuit_session_sets.csv` n'en porte
    pas, et aller chercher celle de `circuit_loads.csv` l'annoncerait comme la charge de ce
    jour-là — or une charge se corrige, une séance passée non.
    """
    await _tabata(store, TODAY, exercices=[("Développé couché", "pectoraux")], rounds=3, reps=7)

    rendu = await _aujourdhui(store)

    assert "séance : Haut du corps" in rendu
    assert "Développé couché 3×7" in rendu


async def test_une_seance_d_hier_ne_passe_pas_pour_celle_du_jour(store: FileStore) -> None:
    """Sans le filtre par date, le bloc dirait « aujourd'hui » sur la séance d'avant-hier —
    et un coach conseillerait du repos à quelqu'un qui n'a rien fait."""
    await _tabata(store, HIER, exercices=[("Squat", "jambes")])

    rendu = await _aujourdhui(store)

    assert "Squat" not in rendu


async def test_les_exercices_du_jour_ne_portent_aucune_charge(store: FileStore) -> None:
    """La question « 0 kg ou poids du corps ? » ne se pose plus ici : il n'y a **pas de
    colonne de charge** dans le monde tabata (**C4**).

    `ACT-07` continue de valoir là où une charge s'écrit — `progression_charges` et
    `detail_seances` le vérifient encore. Ce qui est vérifié ici est l'autre moitié : que
    rien ne vienne en poser une pour meubler.
    """
    await _tabata(store, TODAY, exercices=[("Tractions", "dos")])

    exercices = next(
        ligne for ligne in await context.today_lines(store, TODAY) if "exercices" in ligne
    )

    assert "Tractions 4×8" in exercices
    assert "kg" not in exercices


async def test_le_condense_nomme_demain(store: FileStore) -> None:
    """La date seule obligeait le modèle à dériver le lendemain.

    « Je charge combien demain ? » est une des questions les plus fréquentes, et ce qui se
    dérive se sert — c'est la règle appliquée partout ailleurs dans ce module.
    """
    lines = await context.build(store, adherence=_AUCUN_PLAN, today=date(2026, 8, 17))

    assert "lundi 17/08/2026" in lines[0]
    assert "demain sera le mardi 18/08/2026" in lines[0]


async def test_le_condense_donne_l_heure(store: FileStore) -> None:
    """La moitié des conseils dépendent de l'heure, pas seulement du jour.

    « J'ai assez bu ? » n'appelle pas la même réponse à 9 h et à 22 h : 750 ml est en
    avance le matin et très en retard le soir. Sans heure, le modèle jugeait une journée
    en cours comme si elle était déjà finie.
    """
    lines = await context.build(
        store,
        adherence=_AUCUN_PLAN,
        now=datetime(2026, 8, 19, 12, 40, tzinfo=tz()),
    )

    assert "mercredi 19/08/2026" in lines[0]
    assert "il est 12h40" in lines[0]


async def test_l_heure_et_la_date_parlent_du_meme_jour(store: FileStore) -> None:
    """Un jour épinglé sans instant ne doit pas mélanger deux journées.

    L'appelant qui donne `today` sans `now` — c'est le cas de tout ce fichier — obtiendrait
    sinon la date d'un jour et l'heure de l'horloge d'un autre, dans la même phrase.
    """
    lines = await context.build(store, adherence=_AUCUN_PLAN, today=date(2026, 8, 17))

    assert "lundi 17/08/2026" in lines[0]
    assert re.search(r"il est \d{2}h\d{2}", lines[0]) is not None


async def test_les_chiffres_du_jour_sont_dans_le_condense_de_base(store: FileStore) -> None:
    """Le cœur du lot : plus aucune seconde passe pour « j'ai assez bu ? »."""
    await HydrationService(store).create(IntakePayload(volume_ml=750))

    lines = await context.build(store, adherence=_AUCUN_PLAN, today=TODAY)

    assert any("Aujourd'hui — hydratation : 750 ml" in line for line in lines)


async def test_les_tranches_du_jour_survivent_car_elles_seules_portent_les_jetons(
    store: FileStore,
) -> None:
    """Le condensé sert les **chiffres**, la tranche sert les **identifiants et jetons**.

    Supprimer le repas de midi continue d'exiger la tranche — c'est `STO-05`, et le bloc
    « aujourd'hui » ne l'assouplit pas. Deux rubriques, deux usages.
    """
    await HydrationService(store).create(IntakePayload(volume_ml=500))

    base = await _aujourdhui(store)
    tranche = await _rendu(store, "hydratation_du_jour")

    assert "token=" not in base
    assert "token=" in tranche


# ── Les périodes (lot 12.B) ───────────────────────────


async def test_une_tranche_datee_porte_le_jour_demande_et_pas_aujourd_hui(
    store: FileStore,
) -> None:
    """Le cœur du lot : « et mardi dernier ? » devient une question qui a une réponse."""
    await HydrationService(store).create(IntakePayload(volume_ml=600))

    hier = await _rendu(store, "hydratation_du_jour", jour=HIER)

    assert f"Hydratation du {HIER:%d/%m/%Y}" in hier
    assert "600 ml sur une cible" not in hier


async def test_une_tranche_datee_nomme_la_date_qu_elle_couvre(store: FileStore) -> None:
    """**Le piège de ce lot.** Les tranches disaient « du jour » sans nommer la date.

    Servies pour le 15/08, elles auraient attribué à cette date des mesures qui n'y ont pas
    eu lieu — une valeur inventée, en pire, puisqu'elle est datée.
    """
    rendu = await _rendu(store, "repas_du_jour", jour=date(2026, 8, 15))

    assert "15/08/2026" in rendu
    assert "du jour" not in rendu


async def test_une_semaine_sert_ses_sept_jours(store: FileStore) -> None:
    """Sept journées servies telles quelles, et **aucun agrégat fabriqué**.

    Une moyenne hebdomadaire calculée ici serait le plus sûr moyen que l'assistant annonce
    un chiffre que `/activite` contredit. La règle du module ne se suspend pas pour une
    semaine.
    """
    lundi = date(2026, 8, 10)

    rendu = await _rendu(store, "hydratation_du_jour", jour=lundi, semaine=True)

    for offset in range(7):
        jour = lundi + timedelta(days=offset)
        assert f"Hydratation du {jour:%d/%m/%Y}" in rendu


async def test_une_semaine_part_de_son_lundi_quel_que_soit_le_jour_nomme(
    store: FileStore,
) -> None:
    """N'importe quelle date de la semaine désigne la semaine — c'est ce que la consigne
    promet au modèle, et `week_start` en décide, pas ce module."""
    jeudi = date(2026, 8, 13)

    rendu = await _rendu(store, "hydratation_du_jour", jour=jeudi, semaine=True)

    assert "Hydratation du 10/08/2026" in rendu
    assert "Hydratation du 16/08/2026" in rendu


async def test_la_consigne_apprend_la_syntaxe_des_periodes_au_modele() -> None:
    """**Sans description, la capacité n'existe pas.**

    Le code sait lire `repas_du_jour@2026-08-15` ; un modèle à qui personne ne l'a dit ne
    l'écrira jamais. C'est le même constat qu'au lot où le catalogue d'actions a été généré
    depuis les schémas : une possibilité non décrite est une possibilité morte.
    """
    from app.domains.assistant.conversation import build_prompt

    text = build_prompt(
        question="Et mardi dernier ?",
        context=["Poids : 80,4 kg"],
        memory=[],
        actions=["meal.add — noter un repas"],
        slices=["repas_du_jour"],
    )

    assert "repas_du_jour@2026-08-15" in text
    assert "semaine-" in text
    assert "elle ne retombe pas sur aujourd'hui" in text


async def test_une_phrase_qui_ne_depend_pas_du_jour_n_arrive_qu_une_fois(
    store: FileStore,
) -> None:
    """Vu en regardant le rendu, et aucun test ne l'aurait montré.

    Les chargeurs ajoutent des faits qui ne dépendent pas du jour rendu — « Moyenne
    d'hydratation sur 7 jours » arrivait **sept fois à l'identique** sur une semaine. Le
    doublon se retire dans `slices`, parce qu'aucun chargeur ne sait qu'il est déroulé.
    """
    rendu = await _rendu(store, "hydratation_du_jour", jour=date(2026, 8, 10), semaine=True)

    assert rendu.count("Moyenne d'hydratation sur 7 jours") == 1


async def test_une_periode_ne_peut_pas_manger_la_consigne(store: FileStore) -> None:
    """Sept jours détaillés dépassent à eux seuls tout le reste du condensé.

    La coupe est **annoncée** : un contexte tronqué en silence ferait conclure le modèle
    sur une semaine dont il n'a vu que le début.
    """
    # Sur **un seul jour**, et non une semaine : depuis la garde sur les dates futures,
    # une semaine entamée rend une ligne courte par jour à venir et n'atteint plus le
    # plafond. C'est le bon comportement, mais ce n'est plus ce que ce test mesure.
    for _ in range(45):
        await HydrationService(store).create(IntakePayload(volume_ml=100))

    rendu = await _rendu(store, "hydratation_du_jour", jour=TODAY)

    assert len(rendu.splitlines()) <= context.MAX_PERIOD_LINES + 1
    assert "non montrées" in rendu


# ── Les trous comblés (lot 12.C) ──────────────────────


async def test_les_tendances_situent_une_metrique_sur_trois_mois(store: FileStore) -> None:
    """**La tranche qui débloque la comparaison.**

    « Compare ma progression au développé couché avec mon sommeil » n'avait aucune donnée
    pour se poser. Elle rend les *stats* et non les points : quatre-vingt-dix nombres par
    métrique noieraient la consigne, et un modèle n'en tire pas une corrélation qu'on
    pourrait croire.
    """
    for offset, kg in enumerate([82.0, 81.0, 80.0]):
        await WeightService(store).create(
            WeightPayload(date=TODAY - timedelta(days=offset * 7), weight_kg=kg)
        )

    rendu = await _rendu(store, "tendances")

    assert "Tendance Poids sur trois mois" in rendu
    assert "moyenne 81 kg" in rendu
    assert "3 relevé(s)" in rendu


async def test_les_metriques_muettes_tiennent_en_une_ligne(store: FileStore) -> None:
    """Vu en regardant le rendu : onze lignes sur treize disaient « rien relevé ».

    Six mensurations que presque personne ne relève noyaient les deux métriques qui
    parlent. C'est le volume que `IA-09` interdit, obtenu par accident plutôt que par excès
    de zèle. L'absence reste dite — un coach doit savoir ce qui n'est pas suivi — mais en
    une ligne.
    """
    rendu = await _rendu(store, "tendances")

    assert rendu.count("Rien relevé sur trois mois") == 1
    assert "Masse grasse" in rendu


async def test_les_jours_suivis_disent_quoi_et_quand_pas_seulement_combien(
    store: FileStore,
) -> None:
    """Le condensé donne le **compteur** d'assiduité, pas ce qui a été relevé.

    Un mois où seule l'hydratation est notée et un mois complet donnent la même série, et
    la différence change tout ce qu'un coach en conclut.
    """
    await HydrationService(store).create(IntakePayload(volume_ml=500))

    rendu = await _rendu(store, "jours_suivis")

    assert "Suivi de l'hydratation" in rendu
    assert f"{TODAY:%d/%m}" in rendu


async def test_les_sources_sont_nommees_en_francais(store: FileStore) -> None:
    """Leurs clés sont techniques et anglaises ; la consigne est française de bout en bout.

    Un modèle qui lit « workouts » au milieu de phrases françaises le recopie tel quel dans
    sa réponse.
    """
    rendu = await _rendu(store, "jours_suivis")

    for anglais in ("workouts", "meals", "runs", "hydration", "measurements"):
        assert anglais not in rendu


async def test_les_bilans_hebdomadaires_vont_au_dela_des_deux_du_condense(
    store: FileStore,
) -> None:
    """Deux suffisent à situer une tendance, d'où la borne du condensé ; une question sur
    un trimestre en demande davantage, et c'est ce qu'une tranche existe pour servir."""
    rendu = await _rendu(store, "bilans_hebdomadaires")

    assert "aucun enregistré" in rendu
    assert context.MAX_REVIEWS > context.RECENT_INSIGHTS


# ── Ce que la séance de débogage a corrigé ────────────


async def test_un_jour_futur_ne_rend_pas_un_deficit_invente(store: FileStore) -> None:
    """**Trouvé en sondant des dates aberrantes, pas par un test.**

    `hydratation_du_jour@2030-01-01` rendait « 0 ml sur une cible de 2000 ml, il reste
    2000 ml à boire » — un déficit annoncé sur une journée qui n'a pas eu lieu, qu'un
    modèle lit comme un retard. Un jour à venir n'a pas de relevé, et le dire est la seule
    réponse juste.
    """
    demain = TODAY + timedelta(days=1)

    rendu = await _rendu(store, "hydratation_du_jour", jour=demain)

    assert "n'a pas encore eu lieu" in rendu
    assert "il reste" not in rendu


async def test_le_planning_regarde_devant_et_garde_le_droit_au_futur(
    store: FileStore,
) -> None:
    """Le défaut inverse serait aussi grave : une séance prévue jeudi prochain **est** une
    donnée, et la refuser priverait le coach de ce qui vient."""
    demain = TODAY + timedelta(days=1)

    rendu = await _rendu(store, "planning_a_venir", jour=demain)

    assert "n'a pas encore eu lieu" not in rendu


async def test_le_passe_lointain_reste_servi_car_il_dit_vrai(store: FileStore) -> None:
    """L'antériorité **n'est pas** bornée, et la sonde a montré pourquoi elle n'a pas à
    l'être : « aucune prise le 04/03/2019 » est exact, pas coûteux, et informatif."""
    rendu = await _rendu(store, "hydratation_du_jour", jour=date(2019, 3, 4))

    assert "04/03/2019" in rendu
    assert "n'a pas encore eu lieu" not in rendu


def test_toute_tranche_dit_au_modele_ce_qu_elle_rend() -> None:
    """**Une possibilité non décrite est une possibilité morte.**

    Les tranches étaient listées en noms nus, quand les actions portaient leurs arguments
    depuis longtemps — l'asymétrie n'avait aucune raison d'être. Personne ne devine ce que
    `jours_suivis` contient, ni ce qui distingue `progression_charges` de `detail_seances`.

    Structurel plutôt que déclaratif : une tranche ajoutée sans description fait échouer la
    batterie au lieu d'arriver muette chez le modèle.
    """
    muettes = [nom for nom, tranche in context.SLICES.items() if not tranche.describes.strip()]

    assert not muettes, f"tranches sans description : {muettes}"


def test_les_descriptions_partent_dans_la_consigne_avec_leur_nom() -> None:
    """Rendues depuis `SLICES` et non recopiées à côté : deux listes divergeraient au
    premier ajout, et c'est la règle que le catalogue d'actions suit déjà."""
    rendu = context.describe_slices()

    assert len(rendu) == len(context.SLICES)
    for nom in context.SLICES:
        assert any(ligne.startswith(f"{nom} — ") for ligne in rendu)


async def test_la_semaine_ecoulee_part_sans_qu_on_la_demande(store: FileStore) -> None:
    """**Le défaut le plus grave relevé en usage.**

    Sur « j'ai des courbatures de ma course d'hier », l'assistant a répondu « cette course
    n'apparaît pas encore dans ton suivi ». Elle y était. Relancé deux fois, il n'a jamais
    réclamé `activites_recentes`. La consigne peut inviter à demander ; elle ne peut pas
    garantir qu'il le fasse. Ce qu'on ne peut pas obliger un modèle à chercher, on le lui
    donne.
    """
    # Sans allure dans la charge utile : le service dérive la distance de durée × allure
    # quand les deux sont données, et le test mesurerait alors cette dérivation plutôt que
    # ce qu'il vise.
    await RunService(store).create(RunPayload(date=HIER, distance_km=6.1, duration_min=29))

    lignes = await context.week_lines(store, TODAY)

    assert any(f"Course du {HIER:%d/%m}" in ligne for ligne in lignes)
    assert any("6,1 km" in ligne for ligne in lignes)


async def test_aujourd_hui_n_est_pas_compte_deux_fois(store: FileStore) -> None:
    """`today_lines` porte déjà le jour, avec ses exercices en prime. Le répéter ferait
    lire deux fois la même séance à un coach qui compte le volume."""
    await RunService(store).create(RunPayload(date=TODAY, distance_km=5, duration_min=25))

    semaine = await context.week_lines(store, TODAY)

    assert not any(f"Course du {TODAY:%d/%m}" in ligne for ligne in semaine)


async def test_une_semaine_creuse_le_dit_sans_conclure(store: FileStore) -> None:
    """« Rien depuis sept jours » est vrai et utile. « Tu ne t'entraînes pas » serait une
    conclusion qui n'est pas la nôtre à tirer."""
    lignes = await context.week_lines(store, TODAY)

    assert lignes == ["Les sept jours précédents : aucune séance ni course notée"]


async def test_une_course_d_il_y_a_trois_semaines_ne_passe_pas_pour_recente(
    store: FileStore,
) -> None:
    await RunService(store).create(
        RunPayload(date=TODAY - timedelta(days=21), distance_km=9, duration_min=50)
    )

    lignes = await context.week_lines(store, TODAY)

    assert lignes == ["Les sept jours précédents : aucune séance ni course notée"]


async def test_le_planning_de_la_semaine_part_sans_qu_on_le_demande(
    store: FileStore,
) -> None:
    """Le même angle mort que la semaine écoulée, dans l'autre sens.

    Le condensé porte le **taux** de respect du planning. Un taux dit si l'on tient ses
    rendez-vous ; il ne dit jamais lequel est mardi. « Je fais quoi ce soir ? » retombait
    donc dans le piège qui a fait dire « cette course n'apparaît pas dans ton suivi ».
    """
    await PlanningService(store).create(
        PlanPayload(date=DEMAIN, time="19:00", kind="muscu", title="Haut du corps", duration_min=45)
    )

    lignes = await context.plan_lines(store, TODAY)

    assert any("Haut du corps" in ligne for ligne in lignes)
    assert any("19:00" in ligne for ligne in lignes)


async def test_une_seance_prevue_aujourd_hui_se_dit_aujourd_hui(store: FileStore) -> None:
    """« Prévu le 18/08 » quand on est le 18/08 oblige le modèle à comparer deux dates
    pour comprendre que c'est ce soir. Ce qui se dérive se sert."""
    await PlanningService(store).create(
        PlanPayload(date=TODAY, time="19:00", kind="muscu", title="Jambes", duration_min=60)
    )

    lignes = await context.plan_lines(store, TODAY)

    assert any("Prévu aujourd'hui à 19:00" in ligne for ligne in lignes)


async def test_une_seance_sans_creneau_n_en_recoit_pas_un(store: FileStore) -> None:
    """L'heure est facultative dans `plan.csv` — une séance sans créneau est une
    possibilité normale, et lui en inventer un la daterait faussement."""
    await PlanningService(store).create(
        PlanPayload(date=DEMAIN, kind="autre", title="Mobilité", duration_min=20)
    )

    lignes = await context.plan_lines(store, TODAY)

    assert any("Mobilité" in ligne for ligne in lignes)
    assert not any(" à  :" in ligne or " à :" in ligne for ligne in lignes)


async def test_un_planning_vide_le_dit(store: FileStore) -> None:
    assert await context.plan_lines(store, TODAY) == ["Rien de prévu d'ici 7 jours"]


async def test_le_condense_ne_donne_pas_les_jetons_du_planning(store: FileStore) -> None:
    """Le partage tenu partout : le condensé sert les **faits**, la tranche sert de quoi
    **agir**. Retirer une séance prévue continue d'exiger `planning_a_venir` — `STO-05` ne
    s'assouplit pas parce qu'une information est devenue plus facile à lire."""
    await PlanningService(store).create(
        PlanPayload(date=DEMAIN, time="19:00", kind="muscu", title="Haut du corps", duration_min=45)
    )

    base = "\n".join(await context.plan_lines(store, TODAY))
    tranche = await _rendu(store, "planning_a_venir")

    assert "token=" not in base
    assert "token=" in tranche


async def test_une_seance_dit_les_groupes_musculaires_travailles(store: FileStore) -> None:
    """« muscu, 45 min » ne dit pas si les jambes ont été touchées cette semaine — or
    c'est exactement ce qu'un coach doit savoir avant de proposer la suivante.

    C'est une **lecture** : `muscle_group` est une colonne d'`exercise_log`, recopiée du
    catalogue à l'écriture. Les lister ne dérive rien.
    """
    await _tabata(
        store,
        HIER,
        exercices=[("Développé couché", "pectoraux"), ("Extensions", "triceps")],
        duree=45,
    )

    lignes = await context.week_lines(store, TODAY)

    assert any("pectoraux, triceps" in ligne for ligne in lignes)


async def test_les_groupes_suivent_l_ordre_de_la_seance(store: FileStore) -> None:
    """L'ordre d'apparition plutôt que l'alphabétique : « pectoraux, triceps » dit qu'on a
    poussé avant de finir sur les bras, et un coach lit ça."""
    await _tabata(store, HIER, exercices=[("Squat", "jambes"), ("Tractions", "dos")], duree=50)

    lignes = await context.week_lines(store, TODAY)

    assert any("jambes, dos" in ligne for ligne in lignes)


async def test_une_seance_sans_serie_ne_recoit_pas_un_tiret_vide(store: FileStore) -> None:
    """Une séance sans exercice est une possibilité normale — un circuit corrigé à la
    main, ou vidé de ses lignes. Lui coller un « — » suivi de rien serait une ponctuation
    qui ment."""
    await _tabata(store, HIER, nom="Sortie libre", exercices=[], duree=30, rpe=None)

    lignes = await context.week_lines(store, TODAY)

    assert any("Sortie libre, 30 min" in ligne for ligne in lignes)
    assert not any(ligne.rstrip().endswith("—") for ligne in lignes)


# ── Le coach sur le monde tabata (§5 bis) ─────────────


async def _circuit(store: FileStore, *exercices: tuple[str, str]) -> None:
    """Un circuit enregistré. **La page Charges — et donc la tranche — ne montre que ce
    qui est constitutif d'une séance tabata** : sans circuit, un exercice n'a pas de carte,
    même s'il porte une charge et un historique."""
    from app.domains.activity.schemas import CircuitExercisePayload, CircuitPayload
    from app.domains.activity.service import CircuitService

    await CircuitService(store).create(
        CircuitPayload(
            name="Haut du corps",
            rounds=4,
            round_rest_s=60,
            exercises=[
                CircuitExercisePayload(name=nom, muscle_group=groupe, reps=12)
                for nom, groupe in exercices
            ],
        )
    )


async def _charge(store: FileStore, nom: str, kg: float) -> None:
    """Déclare une charge par le vrai chemin — donc en écrivant au journal (**C2**)."""
    from app.domains.activity.schemas import LoadPayload
    from app.domains.activity.service import CircuitLoadService

    await CircuitLoadService(store).create(LoadPayload(name=nom, weight_kg=kg))


async def test_la_progression_tabata_dit_la_charge_et_ce_qu_elle_a_tenu(
    store: FileStore,
) -> None:
    """Les deux chiffres qui manquaient : depuis quand la charge n'a pas bougé, et combien
    de séances elle a tenu. Le constat, pas la conclusion (**R10**)."""
    await _circuit(store, ("Rowing", "dos"))
    await _tabata(store, TODAY, exercices=[("Rowing", "dos")])
    await _charge(store, "Rowing", 12)

    rendu = await _rendu(store, "progression_tabata")

    assert "Rowing : 12 kg" in rendu
    assert "dernier changement il y a 0 jour(s)" in rendu
    assert "1 séance(s) tenue(s) depuis" in rendu


async def test_la_progression_tabata_n_estime_aucun_maximum(store: FileStore) -> None:
    """**Ni 1RM ni record**, contrairement à `progression_charges`.

    Un tabata au poids du corps ou à répétitions n'a pas de charge maximale lisible, et
    l'estimer depuis quinze répétitions à 10 kg serait une valeur inventée que le modèle
    prendrait au sérieux (§5 bis).
    """
    await _circuit(store, ("Rowing", "dos"))
    await _tabata(store, TODAY, exercices=[("Rowing", "dos")])
    await _charge(store, "Rowing", 12)

    rendu = await _rendu(store, "progression_tabata")

    assert "1RM" not in rendu
    assert "record" not in rendu.lower()


async def test_la_progression_tabata_porte_les_groupes_negliges(store: FileStore) -> None:
    """L'autre moitié de la question : quoi travailler, et pas seulement à quelle charge.

    Lus chez `ActivityStats`, où `ACT-16` vit déjà — « jamais travaillé » rend `None` et
    non un nombre géant, et deux implémentations finiraient par répondre autrement.
    """
    await _tabata(store, HIER, exercices=[("Rowing", "dos")])

    rendu = await _rendu(store, "progression_tabata")

    assert "dos : il y a 1 jour(s)" in rendu
    assert "jambes : jamais travaillé" in rendu


async def test_un_exercice_sans_charge_declaree_ne_fait_pas_de_ligne(store: FileStore) -> None:
    """Une ligne « — » par exercice du catalogue n'apprendrait rien et coûterait des jetons
    à chaque tour. L'absence de charge se dit une fois, pour toute la tranche."""
    await _circuit(store, ("Rowing", "dos"))
    await _tabata(store, TODAY, exercices=[("Rowing", "dos")])

    rendu = await _rendu(store, "progression_tabata")

    assert "Charges de tabata : aucune déclarée" in rendu


# ── La tranche cherchée : les noms exacts de Cadence ──


async def test_le_catalogue_cadence_ne_se_liste_pas_sans_mot_cle(store: FileStore) -> None:
    """1324 exercices ne rentrent pas dans une consigne, et un extrait arbitraire ferait
    croire au modèle qu'il a vu le catalogue. La tranche dit quoi demander."""
    lines = await context.slices(store, [Need("exercices_cadence")])

    assert len(lines) == 1
    assert "mot-clé" in lines[0]
    assert "anglais" in lines[0]


async def test_un_mot_cle_rend_les_noms_exacts_du_catalogue(store: FileStore) -> None:
    """La raison d'être de la tranche : c'est l'orthographe **exacte** qui décide de la
    démonstration affichée pendant l'effort, et le modèle n'a aucun moyen de la deviner."""
    lines = await context.slices(store, [Need("exercices_cadence", query="push up")])

    assert len(lines) == 1
    assert "push-up" in lines[0]
    # Zone et matériel avec chaque nom : c'est ce qui permet de composer « haut du corps »
    # ou « je n'ai que des haltères » sans une seconde requête.
    assert "chest" in lines[0]
    assert "body weight" in lines[0]


async def test_le_francais_ne_trouve_rien_et_la_tranche_le_dit(store: FileStore) -> None:
    """Le catalogue est en anglais. Traduire mot à mot côté serveur serait une seconde
    implémentation du rapprochement de Cadence, celle que ce lot s'interdit — alors on le
    dit au modèle, qui sait traduire."""
    lines = await context.slices(store, [Need("exercices_cadence", query="pompes")])

    assert len(lines) == 1
    assert "aucun exercice" in lines[0].lower()
    # Et surtout : ce n'est pas une impasse. Un nom hors catalogue reste utilisable.
    assert "sans démonstration" in lines[0]


async def test_sans_materiel_declare_la_recherche_ne_filtre_rien(store: FileStore) -> None:
    """**Rien de déclaré n'est pas « aucun matériel » : c'est « on ne sait pas ».**

    Ce test remplace celui qui promettait l'inverse — « la recherche ne lit aucune donnée
    de l'utilisateur ». Ce n'est plus vrai depuis le réglage matériel (**R8**), et la
    signature de `Slice.search` le dit maintenant. Ce qui reste garanti est plus utile :
    un profil vide ne rétrécit pas le catalogue. Filtrer sur l'ensemble vide ne laisserait
    que le poids du corps, et l'assistant deviendrait plus pauvre pour n'avoir jamais été
    renseigné.
    """
    lines = await context.slices(store, [Need("exercices_cadence", query="burpee")])

    assert "burpee" in lines[0]
    assert "limité à ton matériel" not in lines[0]


async def test_le_materiel_declare_filtre_la_recherche(store: FileStore) -> None:
    """La raison d'être du réglage : proposer un développé couché à qui n'a ni banc ni
    barre est pire que de ne rien proposer (**R8**).

    Le poids du corps est toujours joint — 325 des 1324 exercices — sans quoi cocher
    « dumbbell » viderait le tabata de sa moitié la plus utile.
    """
    await _materiel(store, "dumbbell")

    lines = await context.slices(store, [Need("exercices_cadence", query="press")])

    assert "dumbbell" in lines[0]
    assert "barbell" not in lines[0]
    assert "cable" not in lines[0]
    # Le filtre est **annoncé** : un catalogue rétréci en silence ferait conclure au modèle
    # que Cadence ne connaît que ça, au lieu de demander une case de plus.
    assert "limité à ton matériel : dumbbell" in lines[0]


async def test_le_poids_du_corps_reste_toujours_faisable(store: FileStore) -> None:
    """Il ne se coche pas pour être disponible : on l'a sur soi."""
    await _materiel(store, "dumbbell")

    lines = await context.slices(store, [Need("exercices_cadence", query="push-up")])

    assert "body weight" in lines[0]


async def test_rien_avec_son_materiel_ne_se_dit_pas_comme_rien_du_tout(
    store: FileStore,
) -> None:
    """Deux absences, deux réponses.

    « Rien pour ce mot » se corrige en cherchant autrement ; « rien avec ton matériel » se
    corrige en cochant une case de plus. Les confondre enverrait le modèle chercher un
    synonyme qui n'existe pas, indéfiniment.
    """
    await _materiel(store, "body weight")

    lines = await context.slices(store, [Need("exercices_cadence", query="smith machine")])

    assert "aucun avec le matériel déclaré" in lines[0]
    assert "Réglages" in lines[0]


async def test_une_tranche_cherchee_ne_se_deroule_sur_aucune_periode(store: FileStore) -> None:
    """Une semaine de recherche n'aurait aucun sens : le catalogue n'est pas daté. Le
    mot-clé l'emporte, et rien n'est servi sept fois."""
    lines = await context.slices(
        store, [Need("exercices_cadence", date(2026, 8, 12), True, "jump rope")]
    )

    assert len(lines) == 1
    assert "jump rope" in lines[0]


async def test_la_langue_des_noms_est_dite_partout_pareil(store: FileStore) -> None:
    """**Deux consignes qui se contredisent valent moins qu'une seule.**

    Ce test existe parce que la contradiction a eu lieu : en retirant la liste des 35 noms,
    la tranche disait « écris-les naturellement, en français si tu veux » pendant que la
    recherche du catalogue répondait en anglais et rien qu'en anglais. Le modèle lit les
    deux dans la même consigne.

    La règle tient en une phrase — **noms d'exercices en anglais, tout le reste en
    français** — et elle est vérifiée aux deux endroits où le modèle la lit : la ligne de
    l'action, lue à chaque tour, et celle de la tranche, lue au moment de choisir.
    """
    from app.domains.assistant.actions import catalogue as actions_catalogue

    action = actions_catalogue()["circuit.create"].describe
    tranche = context.SLICES["exercices_cadence"].describes

    assert "anglais" in action
    assert "français" in action
    assert "anglais" in tranche
    assert "français" in tranche
    # La tranche annonce aussi son filtre : la description que le modèle lit doit venir de
    # la même source que le comportement, sinon elle finit par mentir.
    assert "matériel" in tranche

    # Et la tranche des séances ne dit plus le contraire.
    lines = await context.slices(store, [Need("seances_cadence")])
    naming = next(line for line in lines if line.startswith("Noms d'exercices"))
    assert "anglais" in naming
    assert "en français si tu veux" not in naming
