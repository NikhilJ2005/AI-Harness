"""Accounts: password hashing, tokens, and looking up the caller.

This follows the same pattern VibeStack's auth_tool generates for the projects
it builds — bcrypt for storage, a signed token for the session. The tool eats
its own cooking.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from vibestack.config import Settings
from vibestack.db.models import User

TOKEN_ALGORITHM = "HS256"

# bcrypt refuses anything longer than 72 bytes, so a long password would raise
# rather than simply being weak.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 8


class AuthError(Exception):
    """Registration or sign-in failed. The API turns this into a 4xx."""


def hash_password(plain_password: str) -> str:
    password_bytes = plain_password.encode("utf-8")[:MAX_PASSWORD_BYTES]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode("utf-8")[:MAX_PASSWORD_BYTES]
    try:
        return bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))
    except ValueError:
        # A malformed hash in the database must read as "wrong password",
        # not crash the endpoint.
        return False


def create_access_token(email: str, settings: Settings) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": email, "exp": expires_at}
    return jwt.encode(payload, settings.secret_key, algorithm=TOKEN_ALGORITHM)


def read_email_from_token(token: str, settings: Settings) -> str | None:
    """The email a token identifies, or None if it is invalid or expired."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[TOKEN_ALGORITHM])
    except jwt.PyJWTError:
        return None
    email = payload.get("sub")
    return email if isinstance(email, str) else None


def find_user_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email))


def register_user(session: Session, email: str, password: str) -> User:
    """Raises AuthError if the email is taken or the password is too short."""
    email = email.strip().lower()
    if not email:
        raise AuthError("An email address is required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(
            f"The password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if find_user_by_email(session, email) is not None:
        raise AuthError("An account with that email already exists.")

    user = User(email=email, password_hash=hash_password(password))
    session.add(user)
    session.flush()  # assigns the id without waiting for the commit
    return user


def authenticate(session: Session, email: str, password: str) -> User:
    """Raises AuthError on bad credentials, without saying which part was wrong."""
    user = find_user_by_email(session, email.strip().lower())
    if user is None or not verify_password(password, user.password_hash):
        raise AuthError("Incorrect email or password.")
    return user
