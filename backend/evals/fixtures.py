"""Les données figées — condensés, carnets, tranches.

**Rien ici n'est lu depuis le stockage.** Chaque ligne reproduit la forme exacte que
`context.build` et `context.slices` rendent, à la ponctuation près, pour que le modèle
reçoive ce qu'il recevrait en production sans que rien ne dépende du jour où l'on mesure.

Le corollaire est une servitude : **quand une ligne du condensé change de forme dans
`context.py`, elle change ici aussi.** Sans quoi le jeu mesure une consigne que
l'application n'envoie plus. C'est le prix du gel, et il est assumé — l'alternative,
recalculer depuis les vraies données, rendrait deux exécutions incomparables.
"""

from __future__ import annotations

# ── Les condensés ─────────────────────────────────────
#
# Trois états, parce que les défauts ne sont pas les mêmes. Un historique fourni teste ce
# que le modèle fait des chiffres ; un historique vide teste ce qu'il fait de leur absence,
# et c'est là que « aucune valeur inventée » se joue.

#: Un suivi installé : des chiffres partout, un objectif en cours, des bilans.
RICHE = [
    "Nous sommes le lundi 16/08/2026",
    "Objectif en cours : Passer à 3 séances par semaine — 2,4 séances par semaine, "
    "68,0 % du chemin (cadence sur 4 semaines), échéance dans 26 jour(s)",
    "Poids : 78,6 kg (dernier relevé du 15/08/2026)",
    "Séances par semaine : 2,4 (cadence sur 4 semaines)",
    "Kilomètres courus par semaine : 18,2 (cadence sur 4 semaines)",
    "Protéines par jour : 112,0 g (cadence sur 14 jours)",
    "Hydratation par jour : 1850,0 ml (cadence sur 14 jours)",
    "Poids sur 90 jours : de 78,4 à 82,1 kg, 31 pesée(s)",
    "Cibles réglées : poids 76,0 kg, protéines 140,0 g par jour, hydratation 2500,0 ml par jour",
    "Suppléments suivis : Créatine, Vitamine D, Magnésium",
    "Assiduité de suivi : 12 jour(s) d'affilée, record 34, 187 jour(s) relevés au total",
    "Respect du planning sur 8 semaines : 17 séance(s) honorée(s) sur 24 prévue(s) (70,8 %)",
    "Bilan de la semaine du 04/08 : deux séances sur trois honorées, protéines en retrait",
    "Bilan de la semaine du 28/07 : trois séances, hydratation au-dessus de la cible",
    "Objectifs passés : « Descendre à 78 kg » atteint, « Courir 25 km par semaine » abandonné",
]

#: Le premier jour. Tout est absent, et c'est ce que l'écran comme le modèle doivent dire —
#: un tiret et le prochain geste, jamais un zéro qui passerait pour une mesure.
VIDE = [
    "Nous sommes le lundi 16/08/2026",
    "Objectif en cours : aucun",
    "Poids : jamais relevé",
    "Séances par semaine : jamais relevé",
    "Kilomètres courus par semaine : jamais relevé",
    "Protéines par jour : jamais relevé",
    "Hydratation par jour : jamais relevé",
    "Cibles réglées : poids 76,0 kg, protéines 140,0 g par jour, hydratation 2500,0 ml par jour",
    "Suppléments : aucun suivi",
    "Assiduité de suivi : 0 jour(s) d'affilée, record 0, 0 jour(s) relevés au total",
    "Respect du planning : rien n'était prévu sur la période",
]

#: Assez de données pour répondre, pas assez pour conclure. L'état le plus fréquent, et
#: celui où un modèle est le plus tenté de combler les trous.
MAIGRE = [
    "Nous sommes le lundi 16/08/2026",
    "Objectif en cours : aucun",
    "Poids : 81,2 kg (dernier relevé du 09/08/2026)",
    "Séances par semaine : 1,0 (cadence sur 4 semaines)",
    "Kilomètres courus par semaine : jamais relevé",
    "Protéines par jour : jamais relevé",
    "Hydratation par jour : jamais relevé",
    "Poids sur 90 jours : de 81,2 à 81,9 kg, 3 pesée(s)",
    "Cibles réglées : poids 76,0 kg, protéines 140,0 g par jour, hydratation 2500,0 ml par jour",
    "Suppléments : aucun suivi",
    "Assiduité de suivi : 2 jour(s) d'affilée, record 4, 9 jour(s) relevés au total",
    "Respect du planning : rien n'était prévu sur la période",
]

# ── Les carnets ───────────────────────────────────────
#
# Rendus par `context.memory_lines`, donc sous la forme « sujet — note ». Le lot 3 y
# ajoutera une date ; le jour où il le fera, ces lignes la porteront aussi.

CARNET_VIDE: list[tuple[str, str]] = []

#: `(sujet, note)` et non des lignes toutes faites, parce que le carnet part **deux fois**
#: dans un tour : mis en phrases pour la consigne par `context.memory_lines`, et brut vers
#: `read_reply(known=…)` qui écarte les redites. Ne garder que les phrases perdait la
#: seconde — l'exécuteur passait `known=None`, `_echoes` n'avait rien à comparer, et le cas
#: `redite-carnet` a rendu ce défaut visible à la première exécution.
CARNET_FOURNI: list[tuple[str, str]] = [
    ("santé", "Douleur au genou droit en descente depuis mars, kiné consulté"),
    ("sommeil", "Dors mal les nuits qui suivent une séance après 20 h"),
    ("contrainte", "Pas de salle le mercredi, seulement course à pied"),
    ("matériel", "Barre et disques à la maison, pas de rack"),
]

# ── Les tranches ──────────────────────────────────────
#
# Servies **seulement si le modèle les réclame**, exactement comme `context.slices`. Elles
# portent les identifiants et les jetons : c'est ce qui referme la boucle de `IA-16` — le
# modèle ne peut désigner une ligne qu'après l'avoir lue.
#
# Les identifiants ci-dessous sont fictifs mais **de la bonne forme** : un jeton trop court
# ou un `row_id` négatif ferait échouer la validation pour une raison qui n'a rien à voir
# avec ce qu'on mesure.

TRANCHES = {
    # ── Servies depuis le lot 1 ──
    "progression_charges": [
        "« Développé couché » (pectoraux, exercise_id=dev-couche) : 65 kg le 13/08/2026 — "
        "+2.5 kg depuis la fois d'avant — record 65 kg — 1RM estimé 81,3 kg — "
        "charges par séance : 57,5 kg, 60 kg, 60 kg, 62,5 kg, 65 kg",
        "« Squat » (jambes, exercise_id=squat) : 90 kg le 11/08/2026 — "
        "+0 kg depuis la fois d'avant — record 92,5 kg — 1RM estimé 104,5 kg — "
        "charges par séance : 85 kg, 90 kg, 92,5 kg, 90 kg, 90 kg",
        "« Tractions » (dos, exercise_id=tractions) : poids du corps le 13/08/2026 — "
        "record poids du corps — charges par séance : poids du corps, poids du corps",
    ],
    "detail_seances": [
        "Séance du 11/08/2026 : Squat 4×6 à 90 kg (volume 2160 kg)",
        "Séance du 13/08/2026 : Développé couché 3×7 à 65 kg (volume 1365 kg) · "
        "Tractions 4×8 au poids du corps (32 répétitions)",
    ],
    "hydratation_du_jour": [
        "Hydratation du jour : 1100 ml sur une cible de 2500 ml (44,0 %), il reste 1400 ml à boire",
        "Moyenne d'hydratation sur 7 jours : 1780 ml",
        "Prise de 600 ml à 08:15 (row_id=0, token=1a2b3c4d)",
        "Prise de 500 ml à 13:40 (row_id=1, token=5e6f7a8b)",
    ],
    "repas_du_jour": [
        "Nutrition du jour : 78,0 g de protéines sur 140,0 g visés, il reste 62,0 g "
        "à prendre, 1420 kcal "
        "(2 repas sur 2 avec les calories renseignées), sucres ajoutés 22,0 g "
        "sur un plafond de 50,0 g",
        "Repas petit_dejeuner à 07:20 (row_id=0, token=a1f4c9e2)",
        "Repas dejeuner à 12:45 (row_id=1, token=b7d2e5a8)",
    ],
    "pesees_recentes": [
        "Pesée du 15/08/2026 : 78,6 kg (row_id=30, token=c3a9f1b6)",
        "Pesée du 12/08/2026 : 78,9 kg (row_id=29, token=d8e4b2c7)",
    ],
    "exercices": [
        "Exercice « Développé couché » (exercise_id=dev-couche, pectoraux)",
        "Exercice « Squat » (exercise_id=squat, jambes)",
        "Exercice « Tractions » (exercise_id=tractions, dos)",
    ],
    "planning_a_venir": [
        "Prévu le 18/08/2026 à 18:30 : Séance haut du corps (row_id=4, token=e5c8d3a1)",
        "Prévu le 20/08/2026 à 18:30 : Sortie course 8 km (row_id=5, token=f2b6a9d4)",
    ],
    "activites_recentes": [
        "Course du 14/08/2026 : 8,2 km, 41 min, allure 5 min/km, FC moyenne 152, "
        "dénivelé 85 m (row_id=12, token=aa11bb22)",
        "Séance du 13/08/2026 : muscu, 62 min, effort perçu 7/10 (row_id=41, token=cc33dd44)",
    ],
    "supplements_du_jour": [
        "Supplément « Créatine » à 08:00 — déjà pris (schedule_id=creat-matin)",
        "Supplément « Magnésium » à 21:00 — pas encore pris (schedule_id=magn-soir)",
    ],
}

__all__ = [
    "CARNET_FOURNI",
    "CARNET_VIDE",
    "MAIGRE",
    "RICHE",
    "TRANCHES",
    "VIDE",
]
