"""Running generations in the background, and remembering them afterwards."""

import tempfile
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from vibestack.db.repository import Repository
from vibestack.db.session import Database
from vibestack.llm_protocol import StructuredLLM
from vibestack.orchestrator import generate_from_spec
from vibestack.review import CouncilReport
from vibestack.spec import ProjectSpec
from vibestack.stages.council import run_council
from vibestack.stages.parse import parse_prompt_to_spec
from vibestack.usage import collect_usage, summarise
from vibestack.validation import Validator

MAX_CONCURRENT_JOBS = 2

# Builds a client from a user-supplied key. Kept as a callable so tests can
# supply a fake without touching the network.
LLMFactory = Callable[[str], StructuredLLM]


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(BaseModel):
    """The public shape of a job. Never carries the user's API key."""

    job_id: str
    status: JobStatus = JobStatus.QUEUED
    prompt: str = ""
    project_name: str = ""
    progress: list[str] = Field(default_factory=list)
    file_count: int = 0
    build_passed: bool = False
    heal_attempts: int = 0
    cost_usd: float = 0.0
    total_tokens: int = 0
    review_counts: dict[str, int] = Field(default_factory=dict)
    error: str = ""


class JobManager:
    """Starts generation jobs and records them against their owner."""

    def __init__(
        self,
        database: Database,
        validator: Validator | None = None,
        llm: StructuredLLM | None = None,
        llm_factory: LLMFactory | None = None,
    ) -> None:
        self._database = database
        self._validator = validator
        self._llm = llm
        self._llm_factory = llm_factory
        self._executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS)

    def has_model(self) -> bool:
        return self._llm is not None

    def _llm_for(self, api_key: str | None) -> StructuredLLM | None:
        """A user's own key wins over the server's, and is never stored."""
        if api_key and self._llm_factory is not None:
            return self._llm_factory(api_key)
        return self._llm

    def reap_stale_jobs(self) -> int:
        with self._database.session() as session:
            return Repository(session).reap_stale_jobs()

    def submit(
        self,
        user_id: int,
        prompt: str = "",
        spec: ProjectSpec | None = None,
        api_key: str | None = None,
    ) -> Job:
        job_id = uuid.uuid4().hex[:12]
        with self._database.session() as session:
            Repository(session).create_job(job_id, user_id, prompt)

        self._executor.submit(self._run_job, job_id, prompt, spec, api_key)
        return Job(job_id=job_id, prompt=prompt)

    def get(self, job_id: str, user_id: int) -> Job | None:
        with self._database.session() as session:
            row = Repository(session).get_job(job_id, user_id)
            if row is None:
                return None
            return self._to_job(session, row)

    def list_jobs(self, user_id: int) -> list[Job]:
        with self._database.session() as session:
            repository = Repository(session)
            return [self._to_job(session, row) for row in repository.list_jobs(user_id)]

    def _to_job(self, session, row) -> Job:
        # Counted from the stored findings rather than held in memory, so the
        # numbers survive a restart like everything else.
        counts: dict[str, int] = {}
        for finding in Repository(session).get_findings(row.id):
            key = finding.severity.value
            counts[key] = counts.get(key, 0) + 1

        return Job(
            job_id=row.id,
            status=JobStatus(row.status),
            prompt=row.prompt,
            project_name=row.project_name,
            progress=Repository(session).read_progress(row),
            file_count=row.file_count,
            build_passed=bool(row.build_passed),
            heal_attempts=row.heal_attempts,
            cost_usd=row.cost_usd,
            total_tokens=row.total_tokens,
            review_counts=counts,
            error=row.error,
        )

    def _update(self, job_id: str, **changes) -> None:
        with self._database.session() as session:
            Repository(session).update_job(job_id, **changes)

    def _add_progress(self, job_id: str, message: str) -> None:
        with self._database.session() as session:
            Repository(session).append_progress(job_id, message)

    def _run_job(
        self,
        job_id: str,
        prompt: str,
        spec: ProjectSpec | None,
        api_key: str | None,
    ) -> None:
        llm = self._llm_for(api_key)
        try:
            self._update(job_id, status=JobStatus.RUNNING.value)

            if spec is None:
                if llm is None:
                    raise RuntimeError(
                        "No API key is configured, so a prompt cannot be parsed. "
                        "Send a specification instead, or supply your own key."
                    )
                self._add_progress(job_id, "Parsing the prompt into a specification...")
                spec = parse_prompt_to_spec(prompt, llm)

            self._update(job_id, project_name=spec.project_name)
            self._add_progress(job_id, f"Generating '{spec.project_name}'...")

            # The project only needs to exist on disk while the gates run
            # against it. Everything worth keeping goes to the database.
            with tempfile.TemporaryDirectory(prefix="vibestack-job-") as directory:
                state = generate_from_spec(
                    spec,
                    Path(directory),
                    validator=self._validator,
                    llm=llm,
                    on_progress=lambda message: self._add_progress(job_id, message),
                )

            report = self._review_if_possible(job_id, state, llm)
            usage = summarise(state.usage)

            with self._database.session() as session:
                repository = Repository(session)
                repository.save_run(job_id, state, report)
                repository.update_job(
                    job_id,
                    status=JobStatus.COMPLETED.value,
                    file_count=len(state.generated_files),
                    build_passed=1 if state.build_passed else 0,
                    heal_attempts=state.heal_attempts,
                    cost_usd=round(usage.cost_usd, 6),
                    total_tokens=usage.prompt_tokens + usage.completion_tokens,
                )

            self._add_progress(job_id, "Done.")

        except Exception as error:
            self._update(job_id, status=JobStatus.FAILED.value, error=str(error))
            self._add_progress(job_id, f"Failed: {error}")

    def _review_if_possible(
        self, job_id: str, state, llm: StructuredLLM | None
    ) -> CouncilReport | None:
        """A failing review must not fail the job; the project is already generated."""
        if llm is None:
            return None

        self._add_progress(job_id, "Running the review council...")
        try:
            report = run_council(state, llm)
        except Exception as error:
            self._add_progress(job_id, f"Review could not be completed: {error}")
            return None

        collect_usage(state, llm)
        self._add_progress(job_id, f"Review complete: {len(report.findings)} finding(s).")
        return report
