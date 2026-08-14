"""Plafond de taille des requêtes, et son refus lisible.

**Le symptôme d'origine** : en mode photo, « Estimer les macros » rendait un `413 Payload
Too Large` brut. Le client décide sur `error.code` (`API-07`) et un refus de cette forme
n'en porte aucun — l'écran affichait un échec sans phrase.

Ces tests portent sur la forme du refus autant que sur le seuil : un `413` qui ne dit rien
en français est, pour cette application, le même défaut qu'un `413` qui ne part pas.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.limits import MAX_REQUEST_BYTES
from app.domains.nutrition.photos import MAX_BYTES as MAX_PHOTO_BYTES


def test_an_oversized_body_is_refused_with_a_code_and_a_sentence(
    client: TestClient, auth: dict[str, str]
) -> None:
    response = client.post(
        "/api/nutrition",
        content=b"x" * (MAX_REQUEST_BYTES + 1),
        headers={**auth, "Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 413
    body = response.json()
    assert body["code"] == "payload_too_large"
    # En français et affichable en l'état : c'est tout ce qui manquait au `413` d'origine.
    assert "trop lourd" in body["message"]


def test_the_refusal_does_not_read_the_body(client: TestClient, auth: dict[str, str]) -> None:
    """La garde lit `Content-Length`, jamais le corps.

    Vérifié par la seule chose observable de l'extérieur : un corps *annoncé* énorme mais
    jamais transmis est refusé quand même, ce qui serait impossible s'il fallait le lire.
    """
    response = client.post(
        "/api/nutrition",
        content=b"",
        headers={
            **auth,
            "Content-Type": "application/octet-stream",
            "Content-Length": str(MAX_REQUEST_BYTES + 1),
        },
    )

    assert response.status_code == 413


def test_a_body_under_the_ceiling_reaches_the_route(
    client: TestClient, auth: dict[str, str]
) -> None:
    """La garde ne doit pas manger ce qu'elle est censée laisser passer.

    `422` et non `413` : la requête est arrivée jusqu'à la validation du domaine, qui la
    refuse pour une autre raison — c'est exactement ce qu'on veut vérifier.
    """
    response = client.post(
        "/api/nutrition",
        content=b"x" * 2048,
        headers={**auth, "Content-Type": "application/octet-stream"},
    )

    assert response.status_code != 413


def test_the_transport_ceiling_leaves_room_above_a_full_size_photo() -> None:
    """Le plafond de transport est **au-dessus** de celui d'une photo, et c'est voulu.

    Les deux confondus refuseraient une image qui tient dans la limite métier, dès que
    l'encodage multipart et les autres champs s'y ajoutent — et le message parlerait alors
    d'une taille que l'utilisateur a respectée.
    """
    assert MAX_REQUEST_BYTES > MAX_PHOTO_BYTES


def test_a_get_is_never_refused_for_its_size(client: TestClient, auth: dict[str, str]) -> None:
    """Sans `Content-Length`, rien à comparer : la requête passe."""
    assert client.get("/api/health").status_code == 200
