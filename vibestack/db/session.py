"""The engine and session factory."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from vibestack.config import Settings
from vibestack.db.models import Base


def build_connect_arguments(database_url: str) -> dict[str, object]:
    """SQLite refuses cross-thread connections unless told otherwise.

    Jobs run on a thread pool, so without this the background workers cannot
    use the session that the request thread created.
    """
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


class Database:
    """Owns the engine and hands out sessions."""

    def __init__(self, settings: Settings | None = None, url: str | None = None) -> None:
        resolved = url or (settings or Settings()).resolved_database_url()
        self.url = resolved
        self.engine = create_engine(
            resolved,
            connect_args=build_connect_arguments(resolved),
            pool_pre_ping=True,
        )
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        """Create any missing tables. Alembic owns the schema in production."""
        Base.metadata.create_all(bind=self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """A session that commits on success and rolls back on error."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
