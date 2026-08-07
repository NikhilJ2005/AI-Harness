"""The mutable state that flows through a single generation run.

``GenerationState`` is the "spine" of the pipeline: it is created once and then
passed to (and updated by) every stage. Because there is exactly one of these
per run and every stage reads and writes the same object, the generated files
stay consistent with each other — this is the shared context that lets us use a
single agent instead of a fragmented multi-agent design.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from vibestack.spec import ProjectSpec


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


class LedgerEntry(BaseModel):
    """One recorded change, for the audit trail (the "why" behind an edit)."""

    stage: str  # e.g. "parse", "generate", "self-heal"
    file_path: str
    rationale: str  # a plain-English reason for the change
    timestamp: str = Field(default_factory=_utc_now_iso)


class GenerationState(BaseModel):
    """Everything we know about one in-progress generation.

    Created once from a ``ProjectSpec``, then updated stage by stage. This is
    also our checkpoint unit: serialising it to disk after each stage lets a
    crashed run resume from the last good point.
    """

    spec: ProjectSpec
    generated_files: dict[str, str] = Field(default_factory=dict)  # path -> text
    build_passed: bool = False
    error_log: str = ""
    heal_attempts: int = 0
    ledger: list[LedgerEntry] = Field(default_factory=list)

    def record_change(self, stage: str, file_path: str, rationale: str) -> None:
        """Append an entry to the change ledger.

        This is the single place changes are recorded, so every stage documents
        its edits in the same way.
        """
        entry = LedgerEntry(stage=stage, file_path=file_path, rationale=rationale)
        self.ledger.append(entry)
