"""Reading and writing everything a run produces."""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from vibestack.db.models import (
    GeneratedFile,
    Job,
    LedgerEntryRow,
    ReviewFindingRow,
    UsageRecordRow,
)
from vibestack.review import CouncilReport, ReviewFinding, ReviewLens, Severity
from vibestack.state import GenerationState, LedgerEntry
from vibestack.usage import UsageRecord

# A job still marked running after this long was almost certainly killed by a
# restart rather than being genuinely slow.
STALE_JOB_MINUTES = 30


class Repository:
    """Job and result storage. One instance wraps one open session."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # --- jobs ---------------------------------------------------------------

    def create_job(self, job_id: str, user_id: int, prompt: str) -> Job:
        job = Job(id=job_id, user_id=user_id, prompt=prompt, status="queued")
        self.session.add(job)
        self.session.flush()
        return job

    def get_job(self, job_id: str, user_id: int | None = None) -> Job | None:
        """Scoped by user when one is given, so a caller cannot read another's job."""
        query = select(Job).where(Job.id == job_id)
        if user_id is not None:
            query = query.where(Job.user_id == user_id)
        return self.session.scalar(query)

    def list_jobs(self, user_id: int, limit: int = 50) -> list[Job]:
        return list(
            self.session.scalars(
                select(Job)
                .where(Job.user_id == user_id)
                .order_by(Job.created_at.desc())
                .limit(limit)
            )
        )

    def update_job(self, job_id: str, **changes) -> None:
        job = self.session.get(Job, job_id)
        if job is None:
            return
        for field_name, value in changes.items():
            setattr(job, field_name, value)

    def append_progress(self, job_id: str, message: str) -> None:
        job = self.session.get(Job, job_id)
        if job is None:
            return
        lines = json.loads(job.progress or "[]")
        lines.append(message)
        job.progress = json.dumps(lines)

    def read_progress(self, job: Job) -> list[str]:
        return json.loads(job.progress or "[]")

    def reap_stale_jobs(self) -> int:
        """Fail jobs left running by a restart. Returns how many were reaped.

        Free and paid instances alike restart on deploy, and a job in a killed
        process will never finish. Without this it would sit at "running"
        forever.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_JOB_MINUTES)
        stale = list(
            self.session.scalars(
                select(Job).where(Job.status.in_(["queued", "running"]))
            )
        )

        reaped = 0
        for job in stale:
            updated = job.updated_at
            # Rows written before this process started are naive in SQLite.
            if updated is not None and updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if updated is not None and updated > cutoff:
                continue
            job.status = "failed"
            job.error = "Interrupted by a server restart."
            reaped += 1
        return reaped

    # --- results ------------------------------------------------------------

    def save_run(
        self,
        job_id: str,
        state: GenerationState,
        report: CouncilReport | None = None,
    ) -> None:
        """Replace everything stored for a job, so saving twice is safe."""
        self._replace_files(job_id, state.generated_files)
        self._replace_ledger(job_id, state.ledger)
        self._replace_usage(job_id, state.usage)
        if report is not None:
            self._replace_findings(job_id, report.findings)

    def _replace_files(self, job_id: str, files: dict[str, str]) -> None:
        self.session.execute(delete(GeneratedFile).where(GeneratedFile.job_id == job_id))
        for path, content in sorted(files.items()):
            self.session.add(GeneratedFile(job_id=job_id, path=path, content=content))

    def _replace_ledger(self, job_id: str, entries: list[LedgerEntry]) -> None:
        self.session.execute(delete(LedgerEntryRow).where(LedgerEntryRow.job_id == job_id))
        for entry in entries:
            self.session.add(
                LedgerEntryRow(
                    job_id=job_id,
                    stage=entry.stage,
                    file_path=entry.file_path,
                    rationale=entry.rationale,
                    timestamp=entry.timestamp,
                )
            )

    def _replace_usage(self, job_id: str, records: list[UsageRecord]) -> None:
        self.session.execute(delete(UsageRecordRow).where(UsageRecordRow.job_id == job_id))
        for record in records:
            self.session.add(
                UsageRecordRow(
                    job_id=job_id,
                    purpose=record.purpose,
                    tier=record.tier,
                    model=record.model,
                    prompt_tokens=record.prompt_tokens,
                    completion_tokens=record.completion_tokens,
                    cost_usd=record.cost_usd,
                )
            )

    def _replace_findings(self, job_id: str, findings: list[ReviewFinding]) -> None:
        self.session.execute(
            delete(ReviewFindingRow).where(ReviewFindingRow.job_id == job_id)
        )
        for finding in findings:
            self.session.add(
                ReviewFindingRow(
                    job_id=job_id,
                    lens=finding.lens.value,
                    severity=finding.severity.value,
                    file_path=finding.file_path,
                    summary=finding.summary,
                    recommendation=finding.recommendation,
                )
            )

    # --- reads --------------------------------------------------------------

    def get_entries(self, job_id: str) -> list[LedgerEntry]:
        rows = self.session.scalars(
            select(LedgerEntryRow)
            .where(LedgerEntryRow.job_id == job_id)
            .order_by(LedgerEntryRow.id)
        )
        return [
            LedgerEntry(
                stage=row.stage,
                file_path=row.file_path,
                rationale=row.rationale,
                timestamp=row.timestamp,
            )
            for row in rows
        ]

    def get_findings(self, job_id: str) -> list[ReviewFinding]:
        rows = self.session.scalars(
            select(ReviewFindingRow)
            .where(ReviewFindingRow.job_id == job_id)
            .order_by(ReviewFindingRow.id)
        )
        return [
            ReviewFinding(
                lens=ReviewLens(row.lens),
                severity=Severity(row.severity),
                file_path=row.file_path,
                summary=row.summary,
                recommendation=row.recommendation,
            )
            for row in rows
        ]

    def get_usage(self, job_id: str) -> list[UsageRecord]:
        rows = self.session.scalars(
            select(UsageRecordRow)
            .where(UsageRecordRow.job_id == job_id)
            .order_by(UsageRecordRow.id)
        )
        return [
            UsageRecord(
                purpose=row.purpose,
                tier=row.tier,
                model=row.model,
                prompt_tokens=row.prompt_tokens,
                completion_tokens=row.completion_tokens,
                cost_usd=row.cost_usd,
            )
            for row in rows
        ]

    def get_files(self, job_id: str) -> dict[str, str]:
        rows = self.session.scalars(
            select(GeneratedFile)
            .where(GeneratedFile.job_id == job_id)
            .order_by(GeneratedFile.path)
        )
        return {row.path: row.content for row in rows}

    def get_file(self, job_id: str, path: str) -> str | None:
        row = self.session.scalar(
            select(GeneratedFile).where(
                GeneratedFile.job_id == job_id, GeneratedFile.path == path
            )
        )
        return row.content if row is not None else None
