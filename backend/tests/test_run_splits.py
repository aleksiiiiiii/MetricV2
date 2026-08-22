"""Les paliers d'une course (`ACT-19`, `IMP-03`).

La course de référence de tous ces tests est celle des captures du lot C08 : 8,14 km en
40:59, neuf lignes de paliers dont la dernière fait `00:44`. Elle a une propriété qui la
rend précieuse et qu'aucune donnée inventée n'aurait eue — **les deux captures se
contrôlent l'une l'autre** :

* la somme des neuf paliers fait 2 459 s, et le temps de séance affiche `0:40:59` ;
* huit paliers pleins plus le reliquat font 8,14 km, et le résumé affiche `8.14 KM` ;
* 2 459 ÷ 8,14 donne 302 s/km, et le résumé affiche `5'02"/KM`.

C'est cette cohérence, et rien d'autre, qui permet de vérifier une extraction dont on n'a
pas la donnée d'origine.
"""

from __future__ import annotations

import io
import json
from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

from app.domains.activity import splits
from app.domains.imports.analysis import read_draft
from tests.fake_openrouter import FakeOpenRouter, Reply
from tests.fake_webdav import FakeWebDav

SPLITS_FILE = "Metric/activity/run_splits.csv"
TODAY = date(2026, 8, 22)

#: La course des captures, telle qu'un modèle la recopie — durées et allures littérales.
REFERENCE = [
    ("05:06", "5'06\"/KM", 166),
    ("04:59", "4'59\"/KM", 167),
    ("05:05", "5'05\"/KM", 158),
    ("05:06", "5'06\"/KM", 169),
    ("05:11", "5'11\"/KM", 172),
    ("05:00", "5'00\"/KM", 173),
    ("04:53", "4'53\"/KM", 174),
    ("04:55", "4'55\"/KM", 173),
    ("00:44", "5'06\"/KM", 163),
]


def model_payload(**overrides: object) -> dict[str, object]:
    """La réponse du modèle sur les deux captures de référence."""
    payload: dict[str, object] = {
        "kind": "run",
        "activity": "Outdoor Run",
        "date": "August 21, 2026",
        "start_time": "7:40 PM",
        "end_time": "8:21 PM",
        "distance": "8.14 KM",
        "duration": "0:40:59",
        "pace": "5'02\"/KM",
        "cadence_spm": "168",
        "elevation_m": "66 M",
        "calories": "439",
        "total_calories": "492",
        "split_length": "1 Kilometer",
        "splits_seen": 9,
        "splits_contiguous": True,
        "splits": [
            {"index": index, "time": time, "pace": pace, "cadence_spm": str(cadence)}
            for index, (time, pace, cadence) in enumerate(REFERENCE, start=1)
        ],
        "readable": True,
    }
    payload.update(overrides)
    return payload


def splits_of(payload: dict[str, object]) -> list[dict[str, Any]]:
    """Les paliers d'une réponse, typés.

    Le scénario les remanie — en retire un, en double un, ment sur leur drapeau — et
    `dict[str, object]` ne se laisse pas indexer. Un accesseur plutôt qu'un `type: ignore`
    par cas : les trois disaient des choses différentes du même besoin.
    """
    found = payload["splits"]
    assert isinstance(found, list)
    return found


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 900), "black").save(buffer, format="PNG")
    return buffer.getvalue()


# ── Le neuvième palier (`ACT-19`) ─────────────────────
#
# Tout ce module existe pour cette ligne-là. `00:44` n'est pas un kilomètre : c'est le
# reliquat de distance, et Apple lui affiche quand même une allure par extrapolation.


def test_the_short_last_split_is_a_remainder_and_not_a_kilometre() -> None:
    draft = read_draft(model_payload(), today=TODAY)

    assert [split.index for split in draft.splits if split.partial] == [9]
    assert draft.splits[8].distance_km == 0.14
    assert all(split.distance_km == 1.0 for split in draft.splits[:8])


def test_the_model_does_not_get_to_decide_which_split_is_partial() -> None:
    """Le drapeau est **recalculé** sur les durées : un modèle qui se trompe est corrigé.

    Le prompt demande `partial` parce que le faire nommer améliore la lecture du reste,
    pas parce qu'on s'y fie. Ici le modèle déclare l'inverse de la vérité sur toute la
    ligne, et la lecture rend malgré tout le bon reliquat.
    """
    lying = model_payload()
    for position, split in enumerate(splits_of(lying)):
        split["partial"] = position != 8  # tout sauf le vrai reliquat

    draft = read_draft(lying, today=TODAY)

    assert [split.index for split in draft.splits if split.partial] == [9]


def test_a_remainder_does_not_drag_the_averages_down() -> None:
    """44 secondes comptées comme un kilomètre fausseraient dérive et extrema.

    C'est le piège central du lot : la dérive porte sur les huit paliers pleins, et le
    palier le plus rapide est le 7ᵉ — pas le reliquat, dont l'allure est extrapolée.
    """
    draft = read_draft(model_payload(), today=TODAY)
    analysis = splits.analyse(
        [
            splits.Split(
                index=split.index,
                duration_s=split.duration_s,
                distance_km=split.distance_km,
                pace_min_km=split.pace_min_km,
                partial=split.partial,
            )
            for split in draft.splits
        ]
    )

    assert analysis.full_count == 8
    assert analysis.partial_count == 1
    assert analysis.fastest_index == 7
    assert analysis.slowest_index == 5


# ── La dérive d'allure ────────────────────────────────


def test_the_drift_says_the_run_accelerated() -> None:
    """Le seul chiffre de la page qui n'est nulle part dans la capture.

    Seconde moitié des paliers pleins (5 à 8) contre la première (1 à 4) :
    1 199 s contre 1 216 s sur quatre kilomètres chacune, soit 4,2 s/km de moins.
    **Négatif veut dire plus rapide**, ce que l'écran doit dire en toutes lettres.
    """
    draft = read_draft(model_payload(), today=TODAY)
    analysis = splits.analyse(
        [
            splits.Split(
                index=split.index,
                duration_s=split.duration_s,
                distance_km=split.distance_km,
                pace_min_km=split.pace_min_km,
                partial=split.partial,
            )
            for split in draft.splits
        ]
    )

    assert analysis.drift_s_per_km == -4.2
    assert analysis.first_half_pace_min_km == 5.067
    assert analysis.second_half_pace_min_km == 4.996


def test_a_drift_needs_four_full_splits_to_mean_anything() -> None:
    """En deçà, un seul kilomètre lent dirait la même chose plus fort. On rend `None`."""
    short = [
        splits.Split(index=index, duration_s=300, distance_km=1.0, pace_min_km=5.0)
        for index in range(1, 4)
    ]

    assert splits.analyse(short).drift_s_per_km is None


def test_the_middle_split_is_dropped_when_the_count_is_odd() -> None:
    """Il appartiendrait autant à l'une qu'à l'autre moitié.

    Cinq paliers dont le troisième est aberrant : l'écarter est ce qui rend la dérive
    lisible plutôt que dépendante d'une convention invisible.
    """
    paces = [5.0, 5.0, 9.9, 4.0, 4.0]
    five = [
        splits.Split(index=index, duration_s=pace * 60, distance_km=1.0, pace_min_km=pace)
        for index, pace in enumerate(paces, start=1)
    ]

    analysis = splits.analyse(five)

    assert analysis.first_half_pace_min_km == 5.0
    assert analysis.second_half_pace_min_km == 4.0
    assert analysis.drift_s_per_km == -60.0


def test_the_pace_axis_is_handed_over_upside_down() -> None:
    """Le plus lent d'abord : une allure basse est une course rapide.

    L'axe se retourne côté serveur pour que l'écran n'ait aucune décision à prendre — et
    surtout aucun `Math.max` sur une collection de mesures.
    """
    draft = read_draft(model_payload(), today=TODAY)
    analysis = splits.analyse(
        [
            splits.Split(
                index=split.index,
                duration_s=split.duration_s,
                distance_km=split.distance_km,
                pace_min_km=split.pace_min_km,
                partial=split.partial,
            )
            for split in draft.splits
        ]
    )

    assert analysis.pace_domain_min_km is not None
    slowest, fastest = analysis.pace_domain_min_km
    assert slowest > fastest


# ── La relecture serveur (`IMP-03`) ───────────────────


def test_two_coherent_captures_are_trusted() -> None:
    draft = read_draft(model_payload(), today=TODAY)

    assert draft.splits_trusted is True
    assert draft.splits_doubts == []


def test_a_sum_that_does_not_fall_marks_the_splits_doubtful() -> None:
    """Une capture manquante au milieu se voit sur la somme, jamais sur une ligne."""
    missing = model_payload()
    missing["splits"] = splits_of(missing)[:5]

    draft = read_draft(missing, today=TODAY)

    assert draft.splits_trusted is False
    assert draft.splits_doubts != []
    # **Marqués douteux, pas refusés** : l'utilisateur a la capture sous les yeux.
    assert len(draft.splits) == 5


def test_a_gap_in_the_numbering_is_noticed_even_when_the_model_denies_it() -> None:
    """La contiguïté se constate sur les index, elle ne se croit pas sur parole."""
    gapped = model_payload(splits_contiguous=True)
    del splits_of(gapped)[3]

    draft = read_draft(gapped, today=TODAY)

    assert draft.splits_trusted is False


def test_a_split_read_out_of_bounds_loses_its_field_not_the_run() -> None:
    """Une cadence de 1 852 est une mauvaise lecture, pas une raison de tout jeter."""
    absurd = model_payload()
    splits_of(absurd)[2]["cadence_spm"] = "1852"

    draft = read_draft(absurd, today=TODAY)

    assert draft.splits[2].cadence_spm is None
    assert draft.splits[2].duration_s == 305
    assert len(draft.splits) == 9


def test_a_split_without_a_readable_time_is_dropped_rather_than_filled() -> None:
    """C'est la durée qui porte tout : le reliquat s'y voit, la somme s'y contrôle."""
    broken = model_payload()
    splits_of(broken)[4]["time"] = "—"

    draft = read_draft(broken, today=TODAY)

    assert [split.index for split in draft.splits] == [1, 2, 3, 4, 6, 7, 8, 9]


def test_the_same_index_seen_on_two_overlapping_captures_is_kept_once() -> None:
    doubled = model_payload()
    doubled["splits"] = [*splits_of(doubled), splits_of(doubled)[0]]

    draft = read_draft(doubled, today=TODAY)

    assert [split.index for split in draft.splits] == [1, 2, 3, 4, 5, 6, 7, 8, 9]


# ── Le résumé (`IMP-03`) ──────────────────────────────


def test_an_english_date_is_read() -> None:
    """Un iPhone réglé en anglais titre « August 21, 2026 ». Sans table de mois, c'était
    une capture parfaitement lue qui rendait une date vide."""
    draft = read_draft(model_payload(), today=TODAY)

    assert draft.date == date(2026, 8, 21)


def test_the_two_calorie_figures_stay_apart() -> None:
    """439 actives et 492 totales. « Calories » sans qualificatif veut dire deux choses."""
    draft = read_draft(model_payload(), today=TODAY)

    assert draft.calories == 439
    assert draft.total_calories == 492


def test_the_time_range_is_read_with_its_meridiem() -> None:
    draft = read_draft(model_payload(), today=TODAY)

    assert draft.start_time is not None
    assert (draft.start_time.hour, draft.start_time.minute) == (19, 40)
    assert draft.end_time is not None
    assert (draft.end_time.hour, draft.end_time.minute) == (20, 21)


def test_a_pace_written_with_its_unit_is_read() -> None:
    """`5'02"/KM` est la forme réellement affichée — apostrophe, guillemet et dénominateur.

    L'analyseur d'avant s'arrêtait à l'apostrophe et rendait `None` : l'allure moyenne
    d'une capture Apple anglaise ne se lisait pas.
    """
    draft = read_draft(model_payload(), today=TODAY)

    assert draft.pace_min_km == 5.033


def test_splits_in_miles_are_converted_like_any_other_distance() -> None:
    """« 1 Mile » passe par l'analyseur de distances, celui qui convertit déjà."""
    imperial = read_draft(model_payload(split_length="1 Mile"), today=TODAY)

    assert imperial.split_length_km == 1.609


def test_a_summary_without_splits_still_reads_as_before() -> None:
    """L'extension ne coûte rien à ce qui marchait : un résumé seul reste un brouillon."""
    draft = read_draft({"kind": "run", "distance": "8,40 KM", "duration": "44:12"}, today=TODAY)

    assert draft.splits == []
    assert draft.splits_trusted is True
    assert draft.distance_km == 8.4


# ── De bout en bout : l'import écrit les paliers ──────


def test_two_screenshots_reach_the_model_in_the_order_they_were_sent(
    ai_app_client: TestClient, auth: dict[str, str], openrouter: FakeOpenRouter
) -> None:
    """L'ordre porte du sens : la consigne parle du résumé comme de la première capture."""
    openrouter.replies = [Reply.says(json.dumps(model_payload()))]

    response = ai_app_client.post(
        "/api/import/apple/analyze",
        files=[
            ("screenshot", ("resume.png", png(), "image/png")),
            ("screenshot", ("paliers.png", png(), "image/png")),
        ],
        headers=auth,
    )

    assert response.status_code == 200
    assert len(openrouter.calls[0].images) == 2
    assert response.json()["splits_trusted"] is True


def test_a_confirmed_import_writes_the_splits_to_their_own_file(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """`run_splits.csv` se rattache par `run_id`, jamais par la position de la ligne."""
    draft = read_draft(model_payload(), today=TODAY)

    response = store_client.post(
        "/api/import/apple",
        json={
            "kind": "run",
            "date": "2026-08-21",
            "distance_km": "8.14",
            "duration_min": "0:40:59",
            "total_calories": 492,
            "split_length_km": 1.0,
            "splits": [
                {
                    "index": split.index,
                    "duration_s": split.duration_s,
                    "pace_min_km": split.pace_min_km,
                    "cadence_spm": split.cadence_spm,
                }
                for split in draft.splits
            ],
        },
        headers=auth,
    )

    assert response.status_code == 201
    lines = dav.content_of(SPLITS_FILE).splitlines()
    assert lines[0] == (
        "run_id,index,duration_s,distance_km,pace_min_km,cadence_spm,avg_hr,elevation_m,partial"
    )
    assert len(lines) == 10  # l'en-tête et les neuf paliers
    assert lines[9].endswith(",true")  # le reliquat, marqué dans le fichier
    assert lines[1].endswith(",false")

    run_id = lines[1].split(",")[0]
    assert run_id and all(line.startswith(run_id) for line in lines[1:])


def test_the_page_reads_the_run_and_its_splits_in_one_request(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    _import_reference(store_client, auth)

    body = store_client.get("/api/activity/runs/latest", headers=auth).json()

    assert body["run"]["distance_km"] == 8.14
    assert body["run"]["total_calories"] == 492
    assert body["splits"]["full_count"] == 8
    assert body["splits"]["partial_count"] == 1
    assert body["splits"]["drift_s_per_km"] == -4.2
    assert body["splits"]["fastest_index"] == 7
    assert len(body["splits"]["splits"]) == 9


def test_the_cadence_share_is_served_rather_than_derived_on_screen(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """`ratio` vient du serveur : l'écran n'a aucun `Math.max` à faire sur des mesures."""
    _import_reference(store_client, auth)

    body = store_client.get("/api/activity/runs/latest", headers=auth).json()
    served = body["splits"]["splits"]

    assert body["splits"]["cadence_max_spm"] == 174
    assert served[6]["cadence_ratio"] == 1.0
    assert all(0 < split["cadence_ratio"] <= 1 for split in served)


def test_an_empty_history_is_an_answer_and_not_a_failure(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """L'écran doit distinguer « aucune course » d'une panne pour dire le prochain geste."""
    response = store_client.get("/api/activity/runs/latest", headers=auth)

    assert response.status_code == 200
    assert response.json()["run"] is None
    assert response.json()["splits"]["splits"] == []


def test_a_keyboard_run_has_no_splits_and_that_is_not_a_defect(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    store_client.post(
        "/api/activity/runs",
        json={"date": "2026-08-20", "distance_km": "8,40", "duration_min": "44:12"},
        headers=auth,
    )

    body = store_client.get("/api/activity/runs/latest", headers=auth).json()

    assert body["run"]["run_id"] == ""
    assert body["splits"]["splits"] == []
    assert body["splits"]["drift_s_per_km"] is None


def test_correcting_a_run_leaves_its_splits_alone(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """Le formulaire de correction n'affiche pas les paliers : il ne peut pas les effacer."""
    _import_reference(store_client, auth)
    before = store_client.get("/api/activity/runs/latest", headers=auth).json()

    corrected = store_client.patch(
        f"/api/activity/runs/{before['run']['id']}",
        json={"date": "2026-08-21", "distance_km": "8,20", "duration_min": "0:40:59"},
        headers={**auth, "If-Match": before["run"]["token"]},
    )

    assert corrected.status_code == 200
    after = store_client.get("/api/activity/runs/latest", headers=auth).json()
    assert after["run"]["run_id"] == before["run"]["run_id"]
    assert len(after["splits"]["splits"]) == 9


def test_deleting_a_run_takes_its_splits_with_it(
    store_client: TestClient, auth: dict[str, str], dav: FakeWebDav
) -> None:
    """Sans cela, `run_splits.csv` garderait des lignes que plus rien ne désigne."""
    _import_reference(store_client, auth)
    run = store_client.get("/api/activity/runs/latest", headers=auth).json()["run"]

    removed = store_client.delete(
        f"/api/activity/runs/{run['id']}",
        headers={**auth, "If-Match": run["token"]},
    )

    assert removed.status_code == 204
    assert dav.content_of(SPLITS_FILE).strip().splitlines()[1:] == []


def _import_reference(client: TestClient, auth: dict[str, str]) -> None:
    """Écrit la course des captures, paliers compris."""
    draft = read_draft(model_payload(), today=TODAY)
    client.post(
        "/api/import/apple",
        json={
            "kind": "run",
            "date": "2026-08-21",
            "distance_km": "8.14",
            "duration_min": "0:40:59",
            "total_calories": 492,
            "split_length_km": 1.0,
            "splits": [
                {
                    "index": split.index,
                    "duration_s": split.duration_s,
                    "pace_min_km": split.pace_min_km,
                    "cadence_spm": split.cadence_spm,
                }
                for split in draft.splits
            ],
        },
        headers=auth,
    )


# ── Ce que les paliers disent de plus (`ACT-19`, lot C09) ──
#
# Rien de ce qui suit n'est sur la capture. Tout se déduit de ce qui y est, et c'est la
# raison d'être de la page : une application qui affiche 5'02" de moyenne ne dit pas si
# la course a été régulière.


def reference_analysis() -> splits.Analysis:
    """L'analyse de la course des captures, sans repasser par l'import."""
    draft = read_draft(model_payload(), today=TODAY)
    return splits.analyse(
        [
            splits.Split(
                index=split.index,
                duration_s=split.duration_s,
                distance_km=split.distance_km,
                pace_min_km=split.pace_min_km,
                cadence_spm=split.cadence_spm,
                partial=split.partial,
            )
            for split in draft.splits
        ]
    )


def test_the_regularity_of_the_run_is_one_number() -> None:
    """Écart-type des allures : 5,8 s/km sur la course de référence.

    Huit kilomètres entre 4'53" et 5'11" tiennent dans dix-huit secondes d'amplitude.
    C'est ce qu'une moyenne de 5'02" ne dit pas — la même moyenne sortirait de quatre
    sprints et quatre marches.
    """
    analysis = reference_analysis()

    assert analysis.pace_sd_s_per_km == 5.8
    assert analysis.pace_spread_s_per_km == 18.0
    assert analysis.fastest_pace_min_km == 4.883
    assert analysis.slowest_pace_min_km == 5.183


def test_the_average_pace_ignores_the_remainder() -> None:
    """5,031 min/km sur les huit paliers pleins, et non l'allure de la course entière.

    Les deux diffèrent : la course affiche 5'02" reliquat compris. C'est la moyenne des
    paliers pleins qui sert de référence aux écarts, sans quoi chaque barre serait
    mesurée contre un repère qu'aucun palier plein n'a produit.
    """
    assert reference_analysis().average_pace_min_km == 5.031


def test_a_run_that_accelerated_is_a_negative_split() -> None:
    """Le drapeau suit la dérive, il ne se calcule pas deux fois."""
    analysis = reference_analysis()

    assert analysis.negative_split is True
    assert analysis.drift_s_per_km is not None
    assert analysis.drift_s_per_km < 0


def test_the_stride_crosses_two_independent_measurements() -> None:
    """1,18 m par pas — l'ordre de grandeur d'un coureur à 5'/km.

    C'est la seule grandeur du lot qui croise distance et pas comptés, et le troisième
    kilomètre le montre : 158 SPM contre 174 au septième, pour des allures voisines. La
    foulée y est la plus longue de la course, ce qu'aucune moyenne ne laissait voir.
    """
    analysis = reference_analysis()

    assert analysis.stride_avg_m == 1.177
    assert analysis.stride_max_m == 1.245  # 3ᵉ km, cadence la plus basse
    assert analysis.stride_min_m == 1.122  # 5ᵉ km, cadence haute et allure lente


def test_the_two_drifts_do_not_read_in_the_same_direction() -> None:
    """L'allure baisse et la cadence monte : deux signes opposés pour un même constat.

    C'est exactement pourquoi l'écran nomme chacun en toutes lettres plutôt que de
    montrer deux nombres signés côte à côte.
    """
    analysis = reference_analysis()

    assert analysis.drift_s_per_km == -4.2  # plus rapide
    assert analysis.cadence_drift_spm == 8.0  # foulée plus fréquente


def test_a_cadence_drift_needs_four_full_splits_like_the_pace_one() -> None:
    """Même découpage que la dérive d'allure, donc même plancher.

    Les calculer sur des découpages différents donnerait deux phrases qui semblent se
    contredire sur la même course.
    """
    three = [
        splits.Split(index=index, duration_s=300, distance_km=1.0, pace_min_km=5.0, cadence_spm=170)
        for index in range(1, 4)
    ]

    assert splits.analyse(three).cadence_drift_spm is None


def test_the_deviation_bars_arrive_signed_and_normalised() -> None:
    """Le signe porte le sens, la valeur absolue la longueur.

    Une barre divergente qui déciderait elle-même de son côté referait à l'écran le
    calcul que le serveur vient de faire — et le referait sur une collection, ce que
    l'invariant interdit deux fois plutôt qu'une.
    """
    analysis = reference_analysis()

    assert analysis.deviation_max_s_per_km == 9.1  # le 5ᵉ km, le plus lent


# ── Le contexte : cette course parmi les autres ───────


def test_a_first_run_is_compared_to_nothing(store_client: TestClient, auth: dict[str, str]) -> None:
    """Un rang de 1 sur 1 ressemblerait à un record. On ne rend rien.

    C'est la même règle que l'état vide de l'écran : mieux vaut ne rien dire que dire
    quelque chose que la donnée ne porte pas.
    """
    _import_reference(store_client, auth)

    context = store_client.get("/api/activity/runs/latest", headers=auth).json()["context"]

    assert context["runs_compared"] == 1
    assert context["pace_rank"] is None
    assert context["recent"] == []


def test_a_run_is_ranked_among_the_others_with_the_count_that_qualifies_it(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """« 2ᵉ sur 3 » et jamais « 2ᵉ ».

    Comparer l'allure d'un 8 km à celle d'un 3 km est bancal. Le rang seul le tairait ;
    le rang accompagné du nombre de courses laisse l'utilisateur en juger.
    """
    _import_reference(store_client, auth)
    for day, distance, duration in (("2026-08-10", "5", "30:00"), ("2026-08-15", "10", "48:00")):
        store_client.post(
            "/api/activity/runs",
            headers=auth,
            json={"date": day, "distance_km": distance, "duration_min": duration},
        )

    context = store_client.get("/api/activity/runs/latest", headers=auth).json()["context"]

    assert context["runs_compared"] == 3
    # 4'48"/km sur le 10 km, 5'02" sur la référence, 6'00" sur le 5 km.
    assert context["pace_rank"] == 2
    assert context["distance_rank"] == 2
    assert context["best_pace_min_km"] == 4.8
    assert context["longest_distance_km"] == 10.0


def test_the_trend_marks_the_run_being_looked_at(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """L'écran ne compare pas des identifiants pour retrouver son point.

    Le serveur désigne celui qui est mis en avant — sans quoi la courbe referait à
    l'écran un choix qui appartient à la donnée.
    """
    _import_reference(store_client, auth)
    store_client.post(
        "/api/activity/runs",
        headers=auth,
        json={"date": "2026-08-10", "distance_km": "5", "duration_min": "30:00"},
    )

    context = store_client.get("/api/activity/runs/latest", headers=auth).json()["context"]

    marked = [mark for mark in context["recent"] if mark["current"]]
    assert len(marked) == 1
    assert marked[0]["distance_km"] == 8.14
    # La plus ancienne d'abord : une courbe de tendance se lit dans le sens du temps.
    assert [mark["date"] for mark in context["recent"]] == ["2026-08-10", "2026-08-21"]
