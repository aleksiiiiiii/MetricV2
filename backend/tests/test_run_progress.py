"""La progression d'une collection de courses (`ACT-20`).

Le piège de ce module n'est pas celui des paliers. `splits.py` compare huit kilomètres
d'une même sortie ; ici on compare des sorties entre elles, et **deux allures ne veulent
plus dire la même chose** : 5'30" sur 15 km est une meilleure course que 5'10" sur 3 km.

Les tests qui suivent portent surtout là-dessus — sur ce que le module refuse de dire
autant que sur ce qu'il calcule.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.domains.activity import progress

TODAY = date(2026, 8, 22)


def sortie(index: int, day: str, distance: float, minutes: float) -> progress.Sortie:
    """Une course dont l'allure est cohérente avec sa distance et sa durée."""
    return progress.Sortie(
        index=index,
        day=date.fromisoformat(day),
        distance_km=distance,
        duration_min=minutes,
        pace_min_km=minutes / distance,
    )


# ── Ce que le module refuse de dire ───────────────────


def test_an_empty_history_says_nothing_rather_than_zero() -> None:
    """Aucune course n'est pas « zéro kilomètre à l'allure de zéro »."""
    empty = progress.analyse([])

    assert empty.total_runs == 0
    assert empty.best_pace_min_km is None
    assert empty.overall_pace_min_km is None
    assert empty.months == []


def test_a_window_needs_two_runs_on_each_side_to_compare_anything() -> None:
    """Une sortie contre une sortie ferait dire à un fractionné que la forme s'effondre."""
    three = [sortie(i, f"2026-08-0{i}", 5.0, 25.0) for i in range(1, 4)]

    assert progress.analyse(three).window.size == 0
    assert progress.analyse(three).window.pace_delta_s_per_km is None


def test_the_window_is_half_the_history_and_never_more_than_five() -> None:
    """Sur douze courses on compare cinq contre cinq, sur six trois contre trois."""
    six = [sortie(i, f"2026-08-0{i}", 5.0, 25.0) for i in range(1, 7)]
    twelve = [sortie(i, f"2026-08-{i:02d}", 5.0, 25.0) for i in range(1, 13)]

    assert progress.analyse(six).window.size == 3
    assert progress.analyse(twelve).window.size == 5


def test_a_month_without_a_run_is_absent_and_not_a_zero() -> None:
    """Un zéro inséré se lirait comme une mesure.

    Juillet et septembre courus, août non : la liste porte **deux** mois, pas trois. Un
    trou dans une courbe est plus honnête qu'un mois à zéro qu'on n'a jamais couru.
    """
    across = [sortie(1, "2026-07-10", 5.0, 25.0), sortie(2, "2026-09-10", 5.0, 25.0)]

    assert [month.month for month in progress.analyse(across).months] == ["2026-07", "2026-09"]


# ── L'allure d'un groupe ──────────────────────────────


def test_a_group_pace_weighs_by_distance_and_not_by_run() -> None:
    """Temps total sur distance totale, et non la moyenne des allures.

    Un 2 km à 6'00" et un 20 km à 5'00" : la moyenne des allures donnerait 5'30", ce qui
    laisserait un footing de récupération saborder un mois entier. Pondérée, l'allure du
    groupe est 5'05" — celle qu'on a réellement tenue sur les 22 kilomètres.
    """
    mixed = [sortie(1, "2026-08-01", 2.0, 12.0), sortie(2, "2026-08-02", 20.0, 100.0)]

    computed = progress.analyse(mixed).overall_pace_min_km

    assert computed == 5.091  # 112 min ÷ 22 km, et non (6 + 5) ÷ 2
    assert computed is not None and computed < 5.5


# ── Les bandes de distance ────────────────────────────


def test_a_record_only_means_something_inside_its_distance_band() -> None:
    """C'est la seule comparaison d'allures honnête de la page.

    Un 3 km rapide et un 15 km plus lent : le record absolu désigne le 3 km, ce qui ne
    dit rien de la forme. Par bande, chacun est le meilleur du sien.
    """
    both = [sortie(1, "2026-08-01", 3.0, 15.3), sortie(2, "2026-08-05", 15.0, 82.5)]

    bands = {band.label: band for band in progress.analyse(both).bands}

    assert bands["Moins de 5 km"].best_index == 1
    assert bands["10 km et plus"].best_index == 2
    assert bands["5 à 10 km"].runs == 0


def test_an_empty_band_stays_in_the_list() -> None:
    """La faire disparaître cacherait qu'on n'a jamais couru au-delà de dix kilomètres.

    Ce qui est précisément une information — et donnerait par-dessus le marché trois
    dispositions d'écran selon l'historique.
    """
    short = [sortie(1, "2026-08-01", 3.0, 15.0)]

    bands = progress.analyse(short).bands

    assert len(bands) == 3
    assert [band.runs for band in bands] == [1, 0, 0]
    assert bands[2].best_pace_min_km is None


def test_a_band_points_at_the_run_that_holds_its_record() -> None:
    """L'écran mène à la course sans la chercher lui-même."""
    runs = [
        sortie(1, "2026-08-01", 6.0, 33.0),
        sortie(2, "2026-08-08", 6.0, 30.0),  # la plus rapide de sa bande
        sortie(3, "2026-08-15", 6.0, 31.2),
    ]

    band = next(b for b in progress.analyse(runs).bands if b.label == "5 à 10 km")

    assert band.best_index == 2
    assert band.best_day == date(2026, 8, 8)
    assert band.runs == 3


# ── La progression proprement dite ────────────────────


def test_the_window_says_the_recent_runs_are_faster() -> None:
    """Le chiffre que la page existe pour montrer.

    Six courses de 5 km : les trois premières à 5'30", les trois dernières à 5'00". La
    fenêtre rend -30 s/km — **négatif veut dire plus rapide**, et l'écran le dit en
    toutes lettres plutôt que de montrer le signe seul.
    """
    runs = [sortie(i, f"2026-08-0{i}", 5.0, 27.5) for i in range(1, 4)]
    runs += [sortie(i, f"2026-08-0{i}", 5.0, 25.0) for i in range(4, 7)]

    window = progress.analyse(runs).window

    assert window.size == 3
    assert window.pace_delta_s_per_km == -30.0
    assert window.recent_pace_min_km == 5.0
    assert window.previous_pace_min_km == 5.5


def test_the_monthly_volume_is_the_progression_without_a_caveat() -> None:
    """Des kilomètres sont des kilomètres : leur somme se compare sans réserve.

    C'est la seule série de la page dont la lecture ne dépend pas des distances courues,
    et c'est pour cela qu'elle y est.
    """
    runs = [
        sortie(1, "2026-07-05", 5.0, 25.0),
        sortie(2, "2026-07-20", 5.0, 25.0),
        sortie(3, "2026-08-03", 10.0, 52.0),
        sortie(4, "2026-08-17", 8.0, 41.0),
    ]

    months = progress.analyse(runs).months

    assert [month.distance_km for month in months] == [10.0, 18.0]
    assert [month.runs for month in months] == [2, 2]


def test_the_pace_axis_is_handed_over_upside_down_here_too() -> None:
    """Le plus lent d'abord, comme partout où ce dépôt trace une allure.

    Deux graphiques d'allure dans l'application qui ne se liraient pas dans le même sens
    seraient pires que pas de second graphique du tout.
    """
    runs = [sortie(1, "2026-08-01", 5.0, 27.5), sortie(2, "2026-08-08", 5.0, 25.0)]

    domain = progress.analyse(runs).pace_domain_min_km

    assert domain is not None
    assert domain[0] > domain[1]


# ── La route ──────────────────────────────────────────


def test_the_page_reads_every_run_and_its_aggregates_in_one_request(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """Une requête pour la liste **et** les agrégats.

    En scinder deux aurait laissé l'écran assembler deux réponses de fraîcheurs
    différentes, ce qui est le recollage que le tableau de bord vient d'abandonner.
    """
    for day, distance, duration in (
        ("2026-07-05", "5", "27:30"),
        ("2026-08-03", "10", "52:00"),
        ("2026-08-17", "8", "41:00"),
    ):
        store_client.post(
            "/api/activity/runs",
            headers=auth,
            json={"date": day, "distance_km": distance, "duration_min": duration},
        )

    body = store_client.get("/api/activity/runs/progress", headers=auth).json()

    assert body["total_runs"] == 3
    assert body["total_distance_km"] == 23.0
    # La plus récente d'abord : c'est celle qu'on vient voir, et la liste se lit du haut.
    assert [run["date"] for run in body["runs"]] == ["2026-08-17", "2026-08-03", "2026-07-05"]
    # Les agrégats, eux, sont chronologiques — une courbe se lit dans le sens du temps.
    assert [month["month"] for month in body["months"]] == ["2026-07", "2026-08"]


def test_progress_is_not_swallowed_by_the_identifier_route(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """`/runs/progress` est déclarée avant `/runs/{row_id}`.

    Sans cet ordre, FastAPI essaie le motif d'identifiant — qui n'accepte qu'un entier —
    et rend un `422` sur une adresse parfaitement valide.
    """
    response = store_client.get("/api/activity/runs/progress", headers=auth)

    assert response.status_code == 200
    assert response.json()["total_runs"] == 0
