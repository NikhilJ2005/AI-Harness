"""Shared state for one generation run."""

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from vibestack.spec import ProjectSpec


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LedgerEntry(BaseModel):
    stage: str  # "plan", "schema", "api", "self-heal", ...
    file_path: str
    rationale: str  # plain-English reason, shown to the user
    timestamp: str = Field(default_factory=_utc_now_iso)


class GenerationState(BaseModel):
    """One in-progress generation. Also the checkpoint unit."""

    spec: ProjectSpec
    generated_files: dict[str, str] = Field(default_factory=dict)  # path -> text
    build_passed: bool = False
    error_log: str = ""
    heal_attempts: int = 0
    ledger: list[LedgerEntry] = Field(default_factory=list)

    def record_change(self, stage: str, file_path: str, rationale: str) -> None:
        entry = LedgerEntry(stage=stage, file_path=file_path, rationale=rationale)
        self.ledger.append(entry)
