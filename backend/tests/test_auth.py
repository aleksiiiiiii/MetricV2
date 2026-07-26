"""Authentification (`AUTH-01` → `AUTH-08`).

Le lot le plus sensible du socle : ce qui est vérifié ici est ce qui empêche un inconnu
de lire un an de données personnelles.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.security import PasswordChecker, TokenIssuer, hash_password
from app.core.throttle import LoginThrottle
from app.main import create_app
from tests.conftest import TEST_PASSWORD, TEST_USERNAME

LOGIN = "/api/auth/login"


def credentials(**overrides: str) -> dict[str, str]:
    return {"username": TEST_USERNAME, "password": TEST_PASSWORD, **overrides}


# ── Connexion (`AUTH-01`, `AUTH-03`) ──────────────────


def test_valid_credentials_open_a_session(client: TestClient) -> None:
    response = client.post(LOGIN, json=credentials())

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["username"] == TEST_USERNAME
    assert body["access_token"]


def test_the_token_lasts_seven_days_by_default(client: TestClient) -> None:
    """`AUTH-03` : la session survit à la fermeture de l'app et au redémarrage."""
    expires_at = datetime.fromisoformat(client.post(LOGIN, json=credentials()).json()["expires_at"])

    remaining = expires_at - datetime.now(tz=UTC)
    assert timedelta(days=6, hours=23) < remaining <= timedelta(days=7)


def test_a_wrong_password_is_refused(client: TestClient) -> None:
    response = client.post(LOGIN, json=credentials(password="pas le bon"))

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


def test_a_wrong_username_is_refused(client: TestClient) -> None:
    response = client.post(LOGIN, json=credentials(username="quelquun-dautre"))

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


def test_the_message_never_says_which_field_was_wrong(client: TestClient) -> None:
    """Dire « identifiant inconnu » confirmerait à un attaquant qu'il cherche au mauvais
    endroit — ou au bon."""
    on_bad_user = client.post(LOGIN, json=credentials(username="inconnu")).json()
    on_bad_password = client.post(LOGIN, json=credentials(password="faux")).json()

    assert on_bad_user == on_bad_password


def test_the_password_is_hashed_even_when_the_username_is_unknown(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`AUTH-04` : sans cela, un identifiant faux répondrait sans passer par Argon2 et le
    temps de réponse dirait lequel des deux champs est en cause.

    On vérifie le **mécanisme** plutôt que le chronomètre : une mesure de durée serait
    instable en CI, alors que l'appel à Argon2 est une propriété exacte et observable.
    """
    # Le vérificateur est construit avant l'espion : sa validation du hash configuré ne
    # doit pas compter dans les appels observés.
    checker = PasswordChecker(settings)

    calls: list[str] = []
    original = PasswordHasher.verify

    def spy(self: PasswordHasher, digest: str, password: str, **kwargs: Any) -> bool:
        calls.append(digest)
        return bool(original(self, digest, password, **kwargs))

    # L'espion est posé sur la classe : les instances d'`argon2` refusent qu'on remplace
    # leurs attributs.
    monkeypatch.setattr(PasswordHasher, "verify", spy)

    checker.verify("inconnu", "peu importe")
    checker.verify(TEST_USERNAME, "faux mot de passe")

    assert len(calls) == 2, "Argon2 doit être exécuté dans les deux cas"
    assert calls[0] != calls[1], "l'identifiant inconnu est vérifié contre un hash leurre"


def test_login_without_configured_hash_refuses_instead_of_opening(password_hash: str) -> None:
    """Un `AUTH_PASSWORD_HASH` vide ne doit pas rendre l'API ouverte à tous."""
    del password_hash
    settings = Settings(_env_file=None, app_env="test", auth_username="aleksi")

    with TestClient(create_app(settings)) as client:
        response = client.post(LOGIN, json=credentials())

    assert response.status_code == 503
    assert response.json()["code"] == "auth_not_configured"
    assert "hash-password" in response.json()["message"]


def test_a_malformed_hash_is_treated_as_unconfigured() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_username="aleksi",
        auth_password_hash="ceci-nest-pas-un-hash-argon2",
    )

    with TestClient(create_app(settings)) as client:
        response = client.post(LOGIN, json=credentials())

    assert response.status_code == 503
    assert response.json()["code"] == "auth_not_configured"


# ── Protection des routes (`AUTH-05`, `AUTH-06`) ──────


def test_the_session_endpoint_needs_a_token(client: TestClient) -> None:
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "session_expired"


def test_a_valid_token_identifies_the_user(client: TestClient, auth: dict[str, str]) -> None:
    response = client.get("/api/auth/me", headers=auth)

    assert response.status_code == 200
    assert response.json() == {"username": TEST_USERNAME}


def test_a_forged_token_is_refused(client: TestClient, settings: Settings) -> None:
    """Signé avec un autre secret : la signature ne tient pas."""
    forged = jwt.encode(
        {"sub": TEST_USERNAME, "exp": datetime.now(tz=UTC) + timedelta(days=1)},
        "un tout autre secret, assez long pour satisfaire la RFC 7518",
        algorithm="HS256",
    )
    del settings

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401
    assert response.json()["code"] == "session_expired"


def test_an_expired_token_is_refused(client: TestClient, settings: Settings) -> None:
    expired = jwt.encode(
        {
            "sub": TEST_USERNAME,
            "iat": datetime.now(tz=UTC) - timedelta(days=8),
            "exp": datetime.now(tz=UTC) - timedelta(days=1),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401
    assert response.json()["code"] == "session_expired"


def test_an_unsigned_token_is_refused(client: TestClient) -> None:
    """`alg: none` est l'attaque classique sur JWT : la liste d'algorithmes l'interdit."""
    unsigned = jwt.encode(
        {"sub": TEST_USERNAME, "exp": datetime.now(tz=UTC) + timedelta(days=1)},
        key="",
        algorithm="none",
    )

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {unsigned}"})

    assert response.status_code == 401


def test_a_token_without_expiry_is_refused(client: TestClient, settings: Settings) -> None:
    """Un jeton sans échéance serait éternel."""
    endless = jwt.encode({"sub": TEST_USERNAME}, settings.jwt_secret, algorithm="HS256")

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {endless}"})

    assert response.status_code == 401


def test_garbage_in_the_header_is_refused(client: TestClient) -> None:
    for header in ("Bearer", "Bearer ", "n'importe quoi", "Basic YWJjOmRlZg=="):
        response = client.get("/api/auth/me", headers={"Authorization": header})
        assert response.status_code == 401, header


def test_logout_ends_the_session_client_side(client: TestClient, auth: dict[str, str]) -> None:
    """`AUTH-07` : le jeton étant autoporteur, la déconnexion est un point d'appel
    explicite — l'effacement local est ce qui termine la session."""
    assert client.post("/api/auth/logout", headers=auth).status_code == 204
    assert client.post("/api/auth/logout").status_code == 401


# ── Anti-brute-force (`AUTH-04`) ──────────────────────


def test_five_failures_then_the_door_closes(client: TestClient) -> None:
    for _ in range(5):
        assert client.post(LOGIN, json=credentials(password="faux")).status_code == 401

    blocked = client.post(LOGIN, json=credentials(password="faux"))

    assert blocked.status_code == 429
    assert blocked.json()["code"] == "too_many_attempts"


def test_the_wait_is_announced_in_the_body_and_the_header(client: TestClient) -> None:
    for _ in range(5):
        client.post(LOGIN, json=credentials(password="faux"))

    blocked = client.post(LOGIN, json=credentials(password="faux"))

    assert "Retry-After" in blocked.headers
    assert 0 < int(blocked.headers["Retry-After"]) <= 60
    assert "secondes" in blocked.json()["message"]


def test_the_quota_blocks_even_the_right_password(client: TestClient) -> None:
    """Sinon le quota ne protégerait de rien : il suffirait de tomber juste au 6ᵉ essai."""
    for _ in range(5):
        client.post(LOGIN, json=credentials(password="faux"))

    assert client.post(LOGIN, json=credentials()).status_code == 429


def test_a_success_clears_the_counter(client: TestClient) -> None:
    """Se tromper deux fois puis réussir ne doit pas laisser de pénalité."""
    for _ in range(4):
        client.post(LOGIN, json=credentials(password="faux"))

    assert client.post(LOGIN, json=credentials()).status_code == 200
    for _ in range(4):
        assert client.post(LOGIN, json=credentials(password="faux")).status_code == 401


def test_the_window_slides() -> None:
    class Clock:
        def __init__(self) -> None:
            self.now = 0.0

        def __call__(self) -> float:
            return self.now

    clock = Clock()
    throttle = LoginThrottle(max_failures=2, window_seconds=60.0, clock=clock)

    throttle.record_failure("ip")
    clock.now = 30.0
    throttle.record_failure("ip")
    with pytest.raises(Exception, match="Trop de tentatives"):
        throttle.guard("ip")

    # La plus ancienne tentative sort de la fenêtre : une place se libère.
    clock.now = 61.0
    throttle.guard("ip")
    assert throttle.failures("ip") == 1


def test_counters_are_kept_per_address() -> None:
    throttle = LoginThrottle(max_failures=2)
    for _ in range(2):
        throttle.record_failure("10.0.0.1")

    throttle.guard("10.0.0.2")  # une autre adresse n'est pas pénalisée

    with pytest.raises(Exception, match="Trop de tentatives"):
        throttle.guard("10.0.0.1")


def test_the_quota_is_checked_before_hashing(client: TestClient) -> None:
    """Sinon une attaque par force brute ferait travailler Argon2 à chaque tentative et
    coûterait plus au serveur qu'à l'attaquant."""
    for _ in range(5):
        client.post(LOGIN, json=credentials(password="faux"))

    # Un mot de passe très long : s'il était haché, la réponse serait sensiblement lente.
    blocked = client.post(LOGIN, json=credentials(password="x" * 256))
    assert blocked.status_code == 429


# ── Jetons, au niveau unitaire ────────────────────────


def test_a_token_round_trip_preserves_the_subject(settings: Settings) -> None:
    issuer = TokenIssuer(settings)

    session = issuer.issue("aleksi")

    assert issuer.read(session.access_token) == "aleksi"


def test_the_configured_hash_verifies_the_original_password() -> None:
    digest = hash_password("un mot de passe")
    settings = Settings(
        _env_file=None, app_env="test", auth_username="a", auth_password_hash=digest
    )
    checker = PasswordChecker(settings)

    assert checker.verify("a", "un mot de passe") is True
    assert checker.verify("a", "un autre") is False
