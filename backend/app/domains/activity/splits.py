"""Ce qu'on déduit des paliers d'une course (`ACT-19`).

Module **pur** : il ne lit aucun fichier, n'interroge aucun modèle, ne connaît ni pydantic
ni FastAPI. C'est le parti pris de `chart-axis.ts` côté écran — ce qui décide se teste sur
des valeurs fixes, ce qui dessine se regarde — et il vaut ici pour une raison de plus :
ces calculs sont exactement ceux que l'invariant « aucun calcul métier côté client »
interdit à l'écran de refaire. Ils n'ont donc qu'une implémentation, et elle est ici.

## Le neuvième palier

Une course de 8,14 km rend neuf lignes : huit autour de cinq minutes, puis `00:44`. La
neuvième n'est pas un kilomètre, c'est le reliquat de distance. Apple lui affiche quand
même une allure — `5'06"/km` — obtenue en extrapolant 44 secondes à un kilomètre entier.

La compter comme un palier plein fausse **tout** : la moyenne, l'écart, la dérive. C'est
le piège central du domaine, et il n'existe que parce que la donnée vient d'une image —
une API dirait la distance de chaque palier.

## Pourquoi `partial` se déduit ici et n'est pas cru sur parole

Le prompt d'extraction demande le drapeau au modèle. On le lui demande parce que le lui
faire nommer améliore sa lecture du reste, **pas** parce qu'on s'y fie : un modèle qui
qualifie son propre travail rend un verdict aussi faux que son extraction. Le drapeau
retenu est celui que `mark_partials` calcule sur les durées, où le reliquat se voit sans
ambiguïté.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from statistics import median, pstdev

#: Longueur d'un palier quand la capture ne dit pas laquelle. Un kilomètre : c'est ce que
#: l'application affiche par défaut, et le seul repli qui ne déforme pas une distance.
DEFAULT_SPLIT_KM = 1.0

#: En deçà de cette part de la durée médiane, un palier est un **reliquat** et non un
#: kilomètre. Le seuil est large à dessein : sur la course de référence, le reliquat fait
#: 14 % de la médiane, et le palier le plus lent en fait 102 %. Rien ne vit entre les deux,
#: et un seuil serré n'attraperait que des cas que l'on préfère laisser pleins.
PARTIAL_RATIO = 0.6

#: Écart toléré entre la somme des paliers et la durée annoncée, en secondes. Une lecture
#: correcte tombe **juste** — 2 459 s des deux côtés sur la course de référence : au-delà
#: de quelques secondes, c'est qu'une ligne a été mal lue ou qu'une capture manque.
DURATION_TOLERANCE_S = 15.0

#: Même idée sur la distance : les paliers pleins doivent redonner la partie entière de la
#: distance totale, à un demi-palier près.
DISTANCE_TOLERANCE_KM = 0.5


@dataclass(frozen=True, slots=True)
class Split:
    """Un palier, tel qu'il se calcule — sans dépendance à la couche de stockage."""

    index: int
    duration_s: float
    pace_min_km: float | None = None
    cadence_spm: int | None = None
    avg_hr: int | None = None
    elevation_m: int | None = None
    partial: bool = False
    distance_km: float | None = None


@dataclass(frozen=True, slots=True)
class Analysis:
    """Ce que les paliers disent d'une course, une fois les reliquats mis à part."""

    full_count: int = 0
    partial_count: int = 0
    #: Dérive d'allure en **secondes par kilomètre** : seconde moitié moins première.
    #: Négative, la course a accéléré.
    drift_s_per_km: float | None = None
    first_half_pace_min_km: float | None = None
    second_half_pace_min_km: float | None = None
    fastest_index: int | None = None
    slowest_index: int | None = None
    #: Bornes de l'axe d'allure, **dans l'ordre où le graphique les attend** : le plus lent
    #: d'abord. Une allure basse est une course rapide, et une courbe qui descend quand on
    #: accélère se lit à l'envers — c'est l'axe qu'on retourne, pas la donnée.
    pace_domain_min_km: tuple[float, float] | None = None
    cadence_max_spm: int | None = None

    # ── Régularité (`ACT-19`) ─────────────────────────
    #
    # Une course de 8 km à 5'02" de moyenne peut être huit kilomètres identiques ou quatre
    # sprints et quatre marches. La moyenne ne les distingue pas ; ces trois-là si.

    #: Allure de référence des paliers pleins : temps total sur distance totale. Elle
    #: diffère de l'allure de la course, qui inclut le reliquat.
    average_pace_min_km: float | None = None
    fastest_pace_min_km: float | None = None
    slowest_pace_min_km: float | None = None
    #: Le plus lent moins le plus rapide, en secondes par kilomètre.
    pace_spread_s_per_km: float | None = None
    #: Écart-type des allures, en secondes par kilomètre. **Population et non échantillon** :
    #: ces paliers sont la course entière, pas un tirage dans quelque chose de plus grand.
    pace_sd_s_per_km: float | None = None
    #: Seconde moitié plus rapide que la première. `None` quand la dérive ne se calcule pas.
    negative_split: bool | None = None

    # ── Cadence et foulée ─────────────────────────────

    cadence_avg_spm: int | None = None
    cadence_min_spm: int | None = None
    #: Dérive de cadence, en pas par minute : seconde moitié moins première. **Positive =
    #: la foulée s'accélère**, à l'inverse de la dérive d'allure — les deux signes ne se
    #: lisent pas dans le même sens, et l'écran doit le dire pour chacun.
    cadence_drift_spm: float | None = None
    #: Longueur de foulée moyenne, en mètres par pas.
    stride_avg_m: float | None = None
    stride_min_m: float | None = None
    stride_max_m: float | None = None
    #: Amplitude des écarts à la moyenne, en s/km — de quoi normaliser des barres signées
    #: sans qu'un écran ait à chercher un maximum dans une collection de mesures.
    deviation_max_s_per_km: float | None = None
    #: Même chose sur la cadence, en pas par minute. La cadence compte **tous** les
    #: paliers, reliquat compris : 163 pas par minute sur 44 secondes est une mesure, là
    #: où l'allure du même palier est une extrapolation.
    cadence_deviation_max_spm: float | None = None


def speed_kmh(pace_min_km: float | None) -> float | None:
    """L'autre lecture d'une allure. `5'00"/km` fait 12 km/h."""
    return None if not pace_min_km or pace_min_km <= 0 else 60 / pace_min_km


def stride_m(split: Split) -> float | None:
    """Longueur de foulée d'un palier, en mètres par pas.

        foulée = distance ÷ (cadence × durée)

    La seule grandeur de ce module qui **croise deux mesures indépendantes** — la distance
    parcourue et les pas comptés —, et c'est ce qui la rend intéressante : à allure égale,
    une foulée plus longue et moins fréquente n'est pas la même course qu'une foulée courte
    et rapide. Aucune application du marché ne l'affiche, et elle se déduit pourtant de ce
    que toutes montrent.

    La cadence d'Apple compte **les deux pieds** : 166 SPM sur 5 min 06 fait 846 pas pour
    un kilomètre, soit 1,18 m par pas — l'ordre de grandeur attendu d'un coureur à 5'/km.
    """
    if not split.cadence_spm or split.cadence_spm <= 0:
        return None
    if split.distance_km is None or split.distance_km <= 0 or split.duration_s <= 0:
        return None
    steps = split.cadence_spm * (split.duration_s / 60)
    return None if steps <= 0 else split.distance_km * 1000 / steps


def mark_partials(splits: list[Split]) -> list[Split]:
    """Repose le drapeau `partial` sur ce que disent les durées.

    La médiane et non la moyenne : sur neuf paliers dont un de 44 secondes, la moyenne est
    déjà tirée vers le bas par le reliquat qu'on cherche justement à écarter.

    Un palier isolé ne se qualifie pas — il n'y a rien à quoi le comparer, et le déclarer
    partiel sur sa seule durée reviendrait à deviner.
    """
    if len(splits) < 2:
        return list(splits)

    reference = median(split.duration_s for split in splits)
    if reference <= 0:
        return list(splits)

    return [
        replace(split, partial=split.duration_s < reference * PARTIAL_RATIO) for split in splits
    ]


def measure_distances(
    splits: list[Split], *, split_length_km: float | None, total_distance_km: float | None
) -> list[Split]:
    """Donne à chaque palier sa longueur **réelle**.

    Un palier plein vaut la longueur annoncée par l'en-tête de la liste (« 1 Kilometer »,
    « 1 Mile »). Le reliquat vaut ce qui reste de la distance totale — et, à défaut de
    distance totale, ce que son allure extrapolée implique : `durée ÷ allure` redonne
    exactement la distance qu'Apple a utilisée pour extrapoler.

    Les deux chemins se rejoignent sur la course de référence : `8,14 - 8 = 0,14` km, et
    `44 s ÷ 5'06"/km = 0,144` km. Le premier est préféré parce qu'il vient d'une mesure
    affichée plutôt que d'un calcul dérivé d'un calcul.
    """
    length = split_length_km if split_length_km and split_length_km > 0 else DEFAULT_SPLIT_KM
    full = [split for split in splits if not split.partial]

    remainder: float | None = None
    if total_distance_km is not None:
        left = total_distance_km - len(full) * length
        # Un reliquat négatif ou nul veut dire que la distance totale et les paliers ne
        # parlent pas de la même course. On ne le distribue pas : la relecture le dira.
        remainder = round(left, 3) if left > 0 else None

    measured: list[Split] = []
    for split in splits:
        if not split.partial:
            measured.append(replace(split, distance_km=length))
            continue
        implied = (
            split.duration_s / 60 / split.pace_min_km
            if split.pace_min_km and split.pace_min_km > 0
            else None
        )
        value = remainder if remainder is not None else implied
        measured.append(replace(split, distance_km=round(value, 3) if value else None))
    return measured


def analyse(splits: list[Split]) -> Analysis:
    """Les chiffres de la page Course, calculés une fois et côté serveur.

    **Les paliers partiels sont écartés de tout ce qui se moyenne.** Ils restent dans la
    liste — l'écran les affiche, marqués — mais un reliquat de 44 secondes n'entre ni dans
    une dérive, ni dans un extremum d'allure : son allure est une extrapolation, et la
    comparer à une mesure reviendrait à comparer une estimation à un chronomètre.

    La cadence, elle, **n'est pas extrapolée** : 163 pas par minute sur 44 secondes est
    une mesure aussi valable que sur cinq minutes. Le maximum de cadence tient donc compte
    de tous les paliers, et c'est la seule asymétrie de ce module.
    """
    full = [split for split in splits if not split.partial]
    paces = [(split.index, split.pace_min_km) for split in full if split.pace_min_km]

    fastest = min(paces, key=lambda pair: pair[1])[0] if paces else None
    slowest = max(paces, key=lambda pair: pair[1])[0] if paces else None

    domain: tuple[float, float] | None = None
    if paces:
        values = [pace for _, pace in paces]
        low, high = min(values), max(values)
        # Deux bornes égales — une course d'une régularité de métronome, ou un seul palier
        # — donneraient une bande d'épaisseur nulle. On l'ouvre d'une seconde par
        # kilomètre de part et d'autre, ce qui n'invente aucune valeur : c'est l'échelle
        # qui s'écarte, pas le point qui se déplace.
        if high - low < 1 / 60:
            low, high = low - 1 / 120, high + 1 / 120
        domain = (round(high, 4), round(low, 4))

    first_half, second_half = _halves(full)
    drift = (
        round((second_half - first_half) * 60, 1)
        if first_half is not None and second_half is not None
        else None
    )

    cadences = [split.cadence_spm for split in splits if split.cadence_spm]
    strides = [value for value in (stride_m(split) for split in splits) if value is not None]

    # La régularité se mesure sur les paliers pleins seuls : un reliquat de 44 secondes
    # ferait exploser un écart-type sans que la course ait varié d'un pas.
    values = [pace for _, pace in paces]
    average = _mean_pace(full)
    spread = round((max(values) - min(values)) * 60, 1) if len(values) >= 2 else None
    deviation = (
        round(max(abs(pace - average) for pace in values) * 60, 1)
        if average is not None and values
        else None
    )

    return Analysis(
        full_count=len(full),
        partial_count=len(splits) - len(full),
        drift_s_per_km=drift,
        first_half_pace_min_km=_round(first_half),
        second_half_pace_min_km=_round(second_half),
        fastest_index=fastest,
        slowest_index=slowest,
        pace_domain_min_km=domain,
        cadence_max_spm=max(cadences) if cadences else None,
        average_pace_min_km=_round(average),
        fastest_pace_min_km=_round(min(values)) if values else None,
        slowest_pace_min_km=_round(max(values)) if values else None,
        pace_spread_s_per_km=spread,
        # `pstdev` et non `stdev` : ces paliers **sont** la course, pas un échantillon
        # tiré d'une population plus large dont on estimerait la dispersion.
        pace_sd_s_per_km=round(pstdev(values) * 60, 1) if len(values) >= 2 else None,
        negative_split=drift < 0 if drift is not None else None,
        cadence_avg_spm=round(sum(cadences) / len(cadences)) if cadences else None,
        cadence_min_spm=min(cadences) if cadences else None,
        cadence_drift_spm=_cadence_drift(full),
        stride_avg_m=round(sum(strides) / len(strides), 3) if strides else None,
        stride_min_m=round(min(strides), 3) if strides else None,
        stride_max_m=round(max(strides), 3) if strides else None,
        deviation_max_s_per_km=deviation,
        cadence_deviation_max_spm=(
            round(max(abs(value - sum(cadences) / len(cadences)) for value in cadences), 1)
            if cadences
            else None
        ),
    )


def _cadence_drift(full: list[Split]) -> float | None:
    """Dérive de cadence entre les deux moitiés, en pas par minute.

    Même découpage que la dérive d'allure — mêmes moitiés, même palier du milieu écarté —
    pour que les deux chiffres parlent du **même** partage de la course. Les calculer sur
    des découpages différents donnerait deux phrases qui semblent se contredire.

    Le signe se lit à l'envers de celui de l'allure : positif, la foulée s'est accélérée.
    """
    usable = [split for split in full if split.cadence_spm]
    if len(usable) < 4:
        return None

    half = len(usable) // 2
    first = [split.cadence_spm or 0 for split in usable[:half]]
    second = [split.cadence_spm or 0 for split in usable[len(usable) - half :]]
    return round(sum(second) / len(second) - sum(first) / len(first), 1)


def _halves(full: list[Split]) -> tuple[float | None, float | None]:
    """Allure moyenne de chaque moitié des paliers pleins, en minutes par kilomètre.

    **Le palier du milieu est écarté** quand le compte est impair : il appartiendrait
    autant à l'une qu'à l'autre, et le verser d'un côté ferait dépendre le signe de la
    dérive d'une convention invisible à l'écran.

    En dessous de deux paliers pleins par moitié — donc de quatre en tout — la dérive ne
    dit rien qu'un seul kilomètre lent ne dirait plus fort. On rend `None` plutôt qu'un
    chiffre que l'écran présenterait comme une tendance.
    """
    usable = [split for split in full if split.pace_min_km and split.distance_km]
    if len(usable) < 4:
        return None, None

    half = len(usable) // 2
    return _mean_pace(usable[:half]), _mean_pace(usable[len(usable) - half :])


def _mean_pace(splits: list[Split]) -> float | None:
    """Allure d'un groupe de paliers : temps total sur distance totale.

    **Pas la moyenne des allures.** Les deux coïncident tant que les paliers font la même
    longueur, et divergent dès qu'ils n'en font plus — une moyenne d'allures pondère
    chaque palier pareil, quelle que soit la distance qu'il couvre.
    """
    seconds = sum(split.duration_s for split in splits)
    distance = sum(split.distance_km or 0 for split in splits)
    return seconds / 60 / distance if distance > 0 else None


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


# ── Relecture d'une extraction (`IMP-03`) ─────────────


@dataclass(frozen=True, slots=True)
class Verdict:
    """Ce que la relecture pense des paliers qu'un modèle vient de rendre.

    Un verdict, **jamais un refus**. Des paliers douteux s'affichent marqués et
    l'utilisateur tranche : il a la capture sous les yeux, nous non. Les jeter
    reviendrait à lui faire ressaisir neuf lignes parce qu'une somme tombait à vingt
    secondes près.
    """

    trusted: bool = True
    reasons: tuple[str, ...] = ()


def verify(
    splits: list[Split],
    *,
    duration_min: float | None,
    distance_km: float | None,
    contiguous: bool,
) -> Verdict:
    """Confronte les paliers au résumé de la même capture (`IMP-03`).

    Les deux images d'un même import se contrôlent l'une l'autre, et c'est la **seule**
    chose qui permette de vérifier une extraction sans avoir la donnée d'origine : la
    somme des paliers doit redonner le temps de séance, et les paliers pleins la partie
    entière de la distance. Sur la course de référence, 2 459 s des deux côtés.
    """
    reasons: list[str] = []

    if not splits:
        return Verdict()

    if not contiguous:
        reasons.append("les paliers relevés ne se suivent pas — une capture manque")

    indexes = [split.index for split in splits]
    if len(set(indexes)) != len(indexes):
        reasons.append("deux paliers portent le même numéro")

    if duration_min is not None:
        total = sum(split.duration_s for split in splits)
        if abs(total - duration_min * 60) > DURATION_TOLERANCE_S:
            reasons.append("la somme des paliers ne redonne pas la durée de la séance")

    if distance_km is not None:
        measured = sum(split.distance_km or 0 for split in splits)
        if measured > 0 and abs(measured - distance_km) > DISTANCE_TOLERANCE_KM:
            reasons.append("les paliers ne redonnent pas la distance parcourue")

    return Verdict(trusted=not reasons, reasons=tuple(reasons))
