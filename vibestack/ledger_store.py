"""Persistent storage for the change ledger."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from vibestack.review import CouncilReport, ReviewFinding, ReviewLens, Severity
from vibestack.state import GenerationState, LedgerEntry

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        prompt TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        file_count INTEGER NOT NULL DEFAULT 0,
        build_passed INTEGER NOT NULL DEFAULT 0,
        heal_attempts INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ledger_entries (
        entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        stage TEXT NOT NULL,
        file_path TEXT NOT NULL,
        rationale TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs (run_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS review_findings (
        finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        lens TEXT NOT NULL,
        severity TEXT NOT NULL,
        file_path TEXT NOT NULL,
        summary TEXT NOT NULL,
        recommendation TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES runs (run_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS entries_by_run ON ledger_entries (run_id)",
    "CREATE INDEX IF NOT EXISTS findings_by_run ON review_findings (run_id)",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LedgerStore:
    """Reads and writes the change ledger. Opens a connection per call, so it is thread-safe."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _create_schema(self) -> None:
        with self._connect() as connection:
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)

    def save_run(
        self,
        run_id: str,
        state: GenerationState,
        prompt: str = "",
        report: CouncilReport | None = None,
    ) -> None:
        """Replaces any existing rows, so saving the same run twice is safe."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO runs
                    (run_id, project_name, prompt, created_at, file_count,
                     build_passed, heal_attempts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    state.spec.project_name,
                    prompt,
                    _utc_now_iso(),
                    len(state.generated_files),
                    1 if state.build_passed else 0,
                    state.heal_attempts,
                ),
            )

            connection.execute("DELETE FROM ledger_entries WHERE run_id = ?", (run_id,))
            connection.executemany(
                """
                INSERT INTO ledger_entries
                    (run_id, stage, file_path, rationale, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (run_id, entry.stage, entry.file_path, entry.rationale, entry.timestamp)
                    for entry in state.ledger
                ],
            )

            if report is not None:
                connection.execute(
                    "DELETE FROM review_findings WHERE run_id = ?", (run_id,)
                )
                connection.executemany(
                    """
                    INSERT INTO review_findings
                        (run_id, lens, severity, file_path, summary, recommendation)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            run_id,
                            finding.lens.value,
                            finding.severity.value,
                            finding.file_path,
                            finding.summary,
                            finding.recommendation,
                        )
                        for finding in report.findings
                    ],
                )

    def get_entries(self, run_id: str) -> list[LedgerEntry]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT stage, file_path, rationale, timestamp
                FROM ledger_entries
                WHERE run_id = ?
                ORDER BY entry_id
                """,
                (run_id,),
            ).fetchall()

        return [
            LedgerEntry(
                stage=row["stage"],
                file_path=row["file_path"],
                rationale=row["rationale"],
                timestamp=row["timestamp"],
            )
            for row in rows
        ]

    def get_findings(self, run_id: str) -> list[ReviewFinding]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT lens, severity, file_path, summary, recommendation
                FROM review_findings
                WHERE run_id = ?
                ORDER BY finding_id
                """,
                (run_id,),
            ).fetchall()

        return [
            ReviewFinding(
                lens=ReviewLens(row["lens"]),
                severity=Severity(row["severity"]),
                file_path=row["file_path"],
                summary=row["summary"],
                recommendation=row["recommendation"],
            )
            for row in rows
        ]

    def get_run(self, run_id: str) -> dict | None:
        """Return one run's summary, or None when it is not in the store."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()

        return dict(row) if row is not None else None

    def list_runs(self, limit: int = 50) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()

        return [dict(row) for row in rows]
