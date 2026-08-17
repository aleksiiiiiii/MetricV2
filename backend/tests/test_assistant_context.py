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

from datetime import date, timedelta

from app.core.dates import today_local
from app.domains.activity.schemas import (
    ExerciseEntryPayload,
    ExercisePayload,
    RunPayload,
    WorkoutPayload,
)
from app.domains.activity.service import ExerciseService, RunService, WorkoutService
from app.domains.assistant import context
from app.domains.assistant.actions import Level, catalogue
from app.domains.assistant.conversation import Need
from app.domains.hydration.schemas import IntakePayload
from app.domains.hydration.service import HydrationService
from app.domains.nutrition.service import NutritionService
from app.domains.planning.schemas import AdherenceView
from app.storage.files import FileStore

TODAY = today_local()

#: Un écart plan/réalisé vide. `build` le reçoit **fourni** et ne le recalcule jamais
#: (`PLAN-06`), donc les tests d'ici n'ont pas de planning à monter.
_AUCUN_PLAN = AdherenceView(weeks=[], planned=0, honoured=0, rate=None)
HIER = TODAY - timedelta(days=1)
AVANT_HIER = TODAY - timedelta(days=2)


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
    """`WorkoutRow.rpe` se disait « transmis à l'IA » sans l'être."""
    exercise_id = await _exercice(store, "Tractions", groupe="dos")
    await _seance(store, HIER, exercise_id, charge=0, series=4, reps=8)

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


async def test_les_exercices_du_jour_partent_avec_leurs_charges(store: FileStore) -> None:
    """« Les exos » de la demande, et rendus **exactement** comme `detail_seances` les rend.

    Deux formulations pour la même chose finiraient par diverger, et un coach lirait deux
    charges différentes selon la rubrique qu'il regarde.
    """
    exercise_id = await _exercice(store, "Développé couché")
    await _seance(store, TODAY, exercise_id, charge=65, series=3, reps=7)

    rendu = await _aujourdhui(store)

    assert "séance : muscu" in rendu
    assert "Développé couché 3×7 à 65 kg" in rendu


async def test_une_seance_d_hier_ne_passe_pas_pour_celle_du_jour(store: FileStore) -> None:
    """Sans le filtre par date, le bloc dirait « aujourd'hui » sur la séance d'avant-hier —
    et un coach conseillerait du repos à quelqu'un qui n'a rien fait."""
    exercise_id = await _exercice(store, "Squat", "jambes")
    await _seance(store, HIER, exercise_id, charge=90, series=4, reps=6)

    rendu = await _aujourdhui(store)

    assert "Squat" not in rendu


async def test_le_poids_du_corps_reste_le_poids_du_corps(store: FileStore) -> None:
    """`ACT-07` : « 0 » n'est pas une charge nulle. Rendre « 0 kg » inviterait le modèle à
    conseiller d'augmenter une charge qui n'existe pas."""
    exercise_id = await _exercice(store, "Tractions", "dos")
    await _seance(store, TODAY, exercise_id, charge=0, series=4, reps=8)

    rendu = await _aujourdhui(store)

    assert "Tractions 4×8 à poids du corps" in rendu
    assert "0 kg" not in rendu


async def test_le_condense_nomme_demain(store: FileStore) -> None:
    """La date seule obligeait le modèle à dériver le lendemain.

    « Je charge combien demain ? » est une des questions les plus fréquentes, et ce qui se
    dérive se sert — c'est la règle appliquée partout ailleurs dans ce module.
    """
    lines = await context.build(store, adherence=_AUCUN_PLAN, today=date(2026, 8, 17))

    assert "lundi 17/08/2026" in lines[0]
    assert "demain sera le mardi 18/08/2026" in lines[0]


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
    for _ in range(30):
        await HydrationService(store).create(IntakePayload(volume_ml=100))

    rendu = await _rendu(store, "hydratation_du_jour", jour=TODAY, semaine=True)

    assert len(rendu.splitlines()) <= context.MAX_PERIOD_LINES + 1
    assert "non montrées" in rendu
