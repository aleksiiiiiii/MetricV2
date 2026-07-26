"""Script de génération du hash (`AUTH-08`)."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.core.security import PasswordChecker
from app.scripts import hash_password as script

PASSWORD = "un mot de passe assez long"


def answer(monkeypatch: pytest.MonkeyPatch, *responses: str) -> None:
    """Répond aux invites de `getpass` dans l'ordre."""
    queue = list(responses)
    monkeypatch.setattr("getpass.getpass", lambda _prompt: queue.pop(0))


def test_the_generated_hash_verifies_the_original_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Le test qui compte : ce que le script imprime doit réellement ouvrir la session."""
    answer(monkeypatch, PASSWORD, PASSWORD)

    assert script.run() == 0

    line = next(
        ligne
        for ligne in capsys.readouterr().out.splitlines()
        if ligne.startswith("AUTH_PASSWORD_HASH=")
    )
    digest = line.removeprefix("AUTH_PASSWORD_HASH=")

    checker = PasswordChecker(
        Settings(_env_file=None, auth_username="aleksi", auth_password_hash=digest)
    )
    assert checker.verify("aleksi", PASSWORD) is True
    assert checker.verify("aleksi", "autre chose") is False


def test_it_also_proposes_a_jwt_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answer(monkeypatch, PASSWORD, PASSWORD)

    script.run()

    line = next(
        ligne for ligne in capsys.readouterr().out.splitlines() if ligne.startswith("JWT_SECRET=")
    )
    assert len(line.removeprefix("JWT_SECRET=")) >= 32, "trop court pour HMAC-SHA256"


def test_two_different_entries_generate_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answer(monkeypatch, PASSWORD, "autre chose")

    assert script.run() == 1
    assert "AUTH_PASSWORD_HASH=" not in capsys.readouterr().out


def test_a_short_password_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """C'est le seul rempart devant toutes les données : douze caractères minimum."""
    answer(monkeypatch, "court", "court")

    assert script.run() == 1
    assert "AUTH_PASSWORD_HASH=" not in capsys.readouterr().out


def test_the_password_never_appears_in_the_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answer(monkeypatch, PASSWORD, PASSWORD)

    script.run()

    assert PASSWORD not in capsys.readouterr().out


def test_an_interrupted_entry_exits_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupt(_prompt: str) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr("getpass.getpass", interrupt)

    assert script.run() == 130
