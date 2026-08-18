"""Running generations in the background for the API."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from vibestack.ledger_store import LedgerStore
from vibestack.llm_protocol import StructuredLLM
from vibestack.orchestrator import generate_from_spec
from vibestack.review import CouncilReport
from vibestack.spec import ProjectSpec
from vibestack.stages.council import run_council
from vibestack.stages.parse import parse_prompt_to_spec
from vibestack.usage import collect_usage, summarise
from vibestack.validation import Validator

MAX_CONCURRENT_JOBS = 2


class JobStatus(str, Enum):
    """Where a job has got to."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(BaseModel):
    """The public state of one generation job."""

    job_id: str
    status: JobStatus = JobStatus.QUEUED
    prompt: str = ""
    project_name: str = ""
    progress: list[str] = Field(default_factory=list)
    file_count: int = 0
    build_passed: bool = False
    heal_attempts: int = 0
    review_counts: dict[str, int] = Field(default_factory=dict)
    cost_usd: float = 0.0
    total_tokens: int = 0
    error: str = ""


class JobManager:
    """Starts generation jobs and keeps track of their progress."""

    def __init__(
        self,
        workspace_root: Path,
        store: LedgerStore,
        validator: Validator | None = None,
        llm: StructuredLLM | None = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._store = store
        self._validator = validator
        self._llm = llm
        self._executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS)

        # Jobs are read by request threads and written by worker threads, so
        # every access goes through this lock.
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    def output_directory(self, job_id: str) -> Path:
        return self._workspace_root / job_id

    def has_model(self) -> bool:
        return self._llm is not None

    def submit(self, prompt: str = "", spec: ProjectSpec | None = None) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id=job_id, prompt=prompt)

        with self._lock:
            self._jobs[job_id] = job

        self._executor.submit(self._run_job, job_id, prompt, spec)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job is not None else None

    def list_jobs(self) -> list[Job]:
        with self._lock:
            jobs = [job.model_copy(deep=True) for job in self._jobs.values()]
        jobs.reverse()
        return jobs

    def _update(self, job_id: str, **changes) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for field_name, value in changes.items():
                setattr(job, field_name, value)

    def _add_progress(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.progress.append(message)

    def _run_job(self, job_id: str, prompt: str, spec: ProjectSpec | None) -> None:
        try:
            self._update(job_id, status=JobStatus.RUNNING)

            if spec is None:
                if self._llm is None:
                    raise RuntimeError(
                        "No API key is configured, so a prompt cannot be parsed. "
                        "Send a specification instead."
                    )
                self._add_progress(job_id, "Parsing the prompt into a specification...")
                spec = parse_prompt_to_spec(prompt, self._llm)

            self._update(job_id, project_name=spec.project_name)
            self._add_progress(job_id, f"Generating '{spec.project_name}'...")

            output_directory = self.output_directory(job_id)
            state = generate_from_spec(
                spec,
                output_directory,
                validator=self._validator,
                llm=self._llm,
                on_progress=lambda message: self._add_progress(job_id, message),
            )

            report = self._review_if_possible(job_id, state)
            self._store.save_run(job_id, state, prompt=prompt, report=report)
            usage = summarise(state.usage)

            self._update(
                job_id,
                status=JobStatus.COMPLETED,
                file_count=len(state.generated_files),
                build_passed=state.build_passed,
                heal_attempts=state.heal_attempts,
                review_counts=report.count_by_severity() if report else {},
                cost_usd=round(usage.cost_usd, 6),
                total_tokens=usage.prompt_tokens + usage.completion_tokens,
            )
            self._add_progress(job_id, "Done.")

        except Exception as error:
            # A failed job must report why, not disappear.
            self._update(job_id, status=JobStatus.FAILED, error=str(error))
            self._add_progress(job_id, f"Failed: {error}")

    def _review_if_possible(self, job_id: str, state) -> CouncilReport | None:
        """A failing review must not fail the job; the project is already generated."""
        if self._llm is None:
            return None

        self._add_progress(job_id, "Running the review council...")
        try:
            report = run_council(state, self._llm)
        except Exception as error:
            self._add_progress(job_id, f"Review could not be completed: {error}")
            return None

        collect_usage(state, self._llm)
        self._add_progress(
            job_id, f"Review complete: {len(report.findings)} finding(s)."
        )
        return report
