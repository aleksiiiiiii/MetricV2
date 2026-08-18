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
    pec = await _exercice(store, "Développé couché", "pectoraux")
    tri = await _exercice(store, "Extensions", "triceps")
    await WorkoutService(store).create(
        WorkoutPayload(
            date=HIER,
            type="muscu",
            duration_min=45,
            rpe=7,
            exercises=[
                ExerciseEntryPayload(exercise_id=pec, weight_kg=65, sets=3, reps=7),
                ExerciseEntryPayload(exercise_id=tri, weight_kg=25, sets=3, reps=12),
            ],
        )
    )

    lignes = await context.week_lines(store, TODAY)

    assert any("pectoraux, triceps" in ligne for ligne in lignes)


async def test_les_groupes_suivent_l_ordre_de_la_seance(store: FileStore) -> None:
    """L'ordre d'apparition plutôt que l'alphabétique : « pectoraux, triceps » dit qu'on a
    poussé avant de finir sur les bras, et un coach lit ça."""
    jambes = await _exercice(store, "Squat", "jambes")
    dos = await _exercice(store, "Tractions", "dos")
    await WorkoutService(store).create(
        WorkoutPayload(
            date=HIER,
            type="muscu",
            duration_min=50,
            exercises=[
                ExerciseEntryPayload(exercise_id=jambes, weight_kg=90, sets=4, reps=6),
                ExerciseEntryPayload(exercise_id=dos, weight_kg=0, sets=4, reps=8),
            ],
        )
    )

    lignes = await context.week_lines(store, TODAY)

    assert any("jambes, dos" in ligne for ligne in lignes)


async def test_une_seance_sans_serie_ne_recoit_pas_un_tiret_vide(store: FileStore) -> None:
    """Une séance typée sans exercice est une possibilité normale — un footing noté
    « autre ». Lui coller un « — » suivi de rien serait une ponctuation qui ment."""
    await WorkoutService(store).create(
        WorkoutPayload(date=HIER, type="autre", duration_min=30, exercises=[])
    )

    lignes = await context.week_lines(store, TODAY)

    assert any("autre, 30 min" in ligne for ligne in lignes)
    assert not any(ligne.rstrip().endswith("—") for ligne in lignes)
