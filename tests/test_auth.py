"""Tests for accounts, hashing, and tokens."""

import pytest

from vibestack.auth import (
    AuthError,
    authenticate,
    create_access_token,
    find_user_by_email,
    hash_password,
    read_email_from_token,
    register_user,
    verify_password,
)
from vibestack.config import Settings
from vibestack.db.session import Database


@pytest.fixture
def database(tmp_path):
    db = Database(url=f"sqlite:///{tmp_path}/test.db")
    db.create_all()
    return db


@pytest.fixture
def settings():
    return Settings(_env_file=None, secret_key="test-secret")


def test_password_round_trip():
    hashed = hash_password("super-secret")

    assert hashed != "super-secret"
    assert verify_password("super-secret", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_a_malformed_hash_reads_as_a_wrong_password():
    """A corrupt row must not crash the login endpoint."""
    assert verify_password("anything", "not-a-real-hash") is False


def test_very_long_passwords_are_accepted():
    """bcrypt rejects input over 72 bytes, so it has to be truncated first."""
    long_password = "x" * 200

    hashed = hash_password(long_password)

    assert verify_password(long_password, hashed) is True


def test_token_round_trip(settings):
    token = create_access_token("nikhil@example.com", settings)

    assert read_email_from_token(token, settings) == "nikhil@example.com"


def test_a_token_signed_with_another_key_is_rejected(settings):
    token = create_access_token("nikhil@example.com", settings)
    other = Settings(_env_file=None, secret_key="a-different-secret")

    assert read_email_from_token(token, other) is None


def test_garbage_token_is_rejected(settings):
    assert read_email_from_token("not-a-token", settings) is None


def test_registering_and_signing_in(database):
    with database.session() as session:
        user = register_user(session, "Nikhil@Example.com ", "super-secret")
        assert user.id is not None
        # Emails are normalised, so casing cannot create a second account.
        assert user.email == "nikhil@example.com"

    with database.session() as session:
        signed_in = authenticate(session, "nikhil@example.com", "super-secret")
        assert signed_in.email == "nikhil@example.com"


def test_the_password_is_never_stored_in_the_clear(database):
    with database.session() as session:
        register_user(session, "a@b.com", "super-secret")

    with database.session() as session:
        user = find_user_by_email(session, "a@b.com")
        assert "super-secret" not in user.password_hash


def test_duplicate_registration_is_refused(database):
    with database.session() as session:
        register_user(session, "a@b.com", "super-secret")

    with database.session() as session:
        with pytest.raises(AuthError, match="already exists"):
            register_user(session, "a@b.com", "another-password")


def test_short_passwords_are_refused(database):
    with database.session() as session:
        with pytest.raises(AuthError, match="at least"):
            register_user(session, "a@b.com", "short")


def test_wrong_password_is_refused(database):
    with database.session() as session:
        register_user(session, "a@b.com", "super-secret")

    with database.session() as session:
        with pytest.raises(AuthError, match="Incorrect"):
            authenticate(session, "a@b.com", "wrong-password")


def test_unknown_account_is_refused(database):
    with database.session() as session:
        with pytest.raises(AuthError, match="Incorrect"):
            authenticate(session, "nobody@example.com", "super-secret")
