"""Le profil — ce que l'assistant sait de moi et qui ne change pas.

**Il ne suit pas la règle du carnet, et tout ce fichier tourne autour de ça.** `IA-10`
autorise l'assistant à remplir le carnet tout seul parce qu'une note fausse ne casse aucun
chiffre. Une taille fausse change toutes les charges qu'on en déduit : le profil est
**saisi**, jamais proposé.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.domains.assistant import profile
from app.domains.assistant.conversation import build_prompt

PROFILE = "/api/assistant/profile"

TODAY = date(2026, 8, 17)


# ── Les lignes envoyées au modèle ─────────────────────


def test_a_filled_profile_becomes_one_line_each() -> None:
    stored = {
        profile.HEIGHT: "178",
        profile.BIRTH_YEAR: "1995",
        profile.TRAINING_DAYS: "lundi, mercredi, samedi",
        profile.EQUIPMENT: "barre, disques, pas de rack",
        profile.PREFERENCES: "je déteste le cardio en salle",
    }

    rendu = profile.lines(stored, today=TODAY)

    assert "Taille : 178 cm" in rendu
    assert "Âge : 31 ans" in rendu
    assert "Jours où je peux m'entraîner : lundi, mercredi, samedi" in rendu
    assert "Matériel dont je dispose : barre, disques, pas de rack" in rendu


def test_the_age_is_derived_from_the_year_and_not_stored() -> None:
    """Un âge rangé est faux au premier anniversaire, et personne ne le corrige.

    Le calcul est au **serveur** et non à l'écran : le client formate, il ne dérive pas.
    """
    assert profile.age("1995", today=date(2026, 1, 1)) == 31
    assert profile.age("1995", today=date(2027, 1, 1)) == 32


def test_an_unset_field_is_absent_and_never_filled_with_a_default() -> None:
    """La différence avec un objectif, et elle est entière.

    Un poids cible non réglé retombe sur 70 kg parce qu'un objectif doit exister pour qu'un
    écran ait quelque chose à montrer. Une taille non saisie n'a **pas** de repli : écrire
    « 175 cm » parce que c'est courant serait une valeur inventée, et le modèle en
    déduirait des charges.
    """
    assert profile.lines({}, today=TODAY) == []
    assert profile.lines({profile.HEIGHT: ""}, today=TODAY) == []


def test_an_unreadable_cell_counts_as_absent_rather_than_breaking() -> None:
    """Le fichier se corrige dans un tableur : une valeur abîmée y est normale.

    C'est la règle du module de réglages, reprise telle quelle — un réglage illisible
    coûte son propre repli, jamais un écran.
    """
    stored = {profile.HEIGHT: "cent-soixante-dix", profile.BIRTH_YEAR: "hier"}

    assert profile.lines(stored, today=TODAY) == []


def test_an_implausible_height_is_refused_by_the_reader_too() -> None:
    """1780 au lieu de 178 : la borne n'existe pas pour juger une saisie mais pour
    empêcher qu'une faute de frappe devienne une donnée que le modèle prendra au sérieux."""
    assert profile.height_cm("1780") is None
    assert profile.height_cm("178") == 178


# ── Le bloc dans la consigne ──────────────────────────


def test_the_profile_heads_the_prompt_before_the_numbers() -> None:
    """Les constantes décident de ce qu'on peut conseiller.

    Un plan qui suppose un rack quand il n'y en a pas ne vaut rien, quels que soient les
    chiffres qui le précèdent.
    """
    text = build_prompt(
        question="Je charge combien lundi ?",
        context=["Poids : 80,4 kg"],
        memory=[],
        profile=["Taille : 178 cm", "Matériel dont je dispose : barre, pas de rack"],
    )

    assert "## Ce que je suis" in text
    assert text.index("## Ce que je suis") < text.index("## Ce que disent les données")
    assert "pas de rack" in text


def test_an_empty_profile_removes_the_heading_instead_of_announcing_nothing() -> None:
    """Un titre suivi de rien apprend qu'il n'y a rien à savoir, ce qui est faux : il n'y
    a rien de **saisi**."""
    text = build_prompt(question="Q ?", context=["Poids : 80,4 kg"], memory=[])

    assert "Ce que je suis" not in text


# ── La route ──────────────────────────────────────────


def test_a_profile_is_read_back_as_it_was_written(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    token = store_client.get(PROFILE, headers=auth).json()["token"]

    written = store_client.put(
        PROFILE,
        json={"height_cm": 178, "birth_year": 1995, "equipment": "barre et disques"},
        headers={**auth, "If-Match": token},
    )

    assert written.status_code == 200
    body = written.json()
    assert body["height_cm"] == 178
    assert body["equipment"] == "barre et disques"
    assert any("178 cm" in line for line in body["lines"])


def test_writing_the_profile_can_clear_a_field(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """`PUT` et non `PATCH` : vider un champ — « je n'ai plus de rack » — est un geste
    normal sur un formulaire qu'on voit en entier."""
    token = store_client.get(PROFILE, headers=auth).json()["token"]
    store_client.put(
        PROFILE,
        json={"height_cm": 178, "equipment": "un rack"},
        headers={**auth, "If-Match": token},
    )

    token = store_client.get(PROFILE, headers=auth).json()["token"]
    body = store_client.put(
        PROFILE, json={"height_cm": 178}, headers={**auth, "If-Match": token}
    ).json()

    assert body["equipment"] == ""
    assert not any("Matériel" in line for line in body["lines"])


def test_writing_the_profile_without_if_match_is_a_conflict(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """`STO-05` : un `If-Match` absent est un conflit, jamais une permission."""
    response = store_client.put(PROFILE, json={"height_cm": 178}, headers=auth)

    assert response.status_code == 409


def test_an_implausible_height_is_refused_by_the_api(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    token = store_client.get(PROFILE, headers=auth).json()["token"]

    response = store_client.put(
        PROFILE, json={"height_cm": 1780}, headers={**auth, "If-Match": token}
    )

    assert response.status_code == 422


def test_the_profile_does_not_disturb_the_other_settings(
    store_client: TestClient, auth: dict[str, str]
) -> None:
    """Le profil partage `settings.csv` avec les cibles et les créneaux de rappel.

    `update_keys` conserve ce qu'il ne connaît pas — c'est pour ça qu'il existe —, et
    régler sa taille n'a aucune raison d'effacer un poids cible.
    """
    settings = store_client.get("/api/settings", headers=auth).json()
    store_client.patch(
        "/api/settings",
        json={"target_weight_kg": 76.0},
        headers={**auth, "If-Match": settings["token"]},
    )

    token = store_client.get(PROFILE, headers=auth).json()["token"]
    store_client.put(PROFILE, json={"height_cm": 178}, headers={**auth, "If-Match": token})

    after = store_client.get("/api/settings", headers=auth).json()
    assert after["values"]["target_weight_kg"] == 76.0
