"""The VibeStack HTTP API and demo page.

Start it with:

    uvicorn vibestack.api:create_app --factory --reload

Then open http://localhost:8000 to generate a backend from the browser and read
the change ledger for any run.

The application is built by a factory rather than created when this module is
imported. Building it opens the ledger database, and importing a module should
never have that kind of side effect.
"""

import io
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from vibestack.config import Settings
from vibestack.jobs import Job, JobManager
from vibestack.ledger_store import LedgerStore
from vibestack.llm_client import LLMClient
from vibestack.llm_protocol import StructuredLLM
from vibestack.spec import ProjectSpec
from vibestack.state import LedgerEntry
from vibestack.validators import SandboxKind, build_validator

WORKSPACE_ROOT = Path("vibestack-workspace")
DATABASE_PATH = WORKSPACE_ROOT / "ledger.db"
STATIC_DIRECTORY = Path(__file__).parent / "static"


class GenerateRequest(BaseModel):
    """What a client sends to start a generation.

    Exactly one of ``prompt`` or ``spec`` is required. Sending a spec needs no
    API key, which is what makes the demo work offline.
    """

    prompt: str = ""
    spec: ProjectSpec | None = None


class GenerateResponse(BaseModel):
    """The job created for a generation request."""

    job_id: str
    status: str


def build_llm_or_none(settings: Settings) -> StructuredLLM | None:
    """Return a model client, or None when no key is configured."""
    if not settings.has_api_key():
        return None
    return LLMClient(settings)


def create_app(
    workspace_root: Path = WORKSPACE_ROOT,
    database_path: Path | None = None,
    llm: StructuredLLM | None = None,
    sandbox: SandboxKind = SandboxKind.AUTO,
) -> FastAPI:
    """Build the application.

    Everything the app depends on can be supplied by the caller, which is what
    lets the tests run it with a fake model and a temporary workspace.
    """
    settings = Settings()
    store = LedgerStore(database_path or (workspace_root / "ledger.db"))
    manager = JobManager(
        workspace_root=workspace_root,
        store=store,
        validator=build_validator(sandbox),
        llm=llm if llm is not None else build_llm_or_none(settings),
    )

    app = FastAPI(
        title="VibeStack",
        description="Generate a FastAPI backend, prove it works, and explain every change.",
        version="0.1.0",
    )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def demo_page() -> str:
        """Serve the single-page demo interface."""
        return (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")

    @app.get("/api/health", tags=["health"])
    def health_check() -> dict[str, object]:
        """Report that the service is running and whether a model is configured."""
        return {"status": "ok", "model_configured": manager.has_model()}

    @app.post(
        "/api/generate",
        response_model=GenerateResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["generation"],
    )
    def start_generation(request: GenerateRequest) -> GenerateResponse:
        """Start a generation and return the job that will carry it out."""
        if not request.prompt and request.spec is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide either a prompt or a specification.",
            )

        job = manager.submit(prompt=request.prompt, spec=request.spec)
        return GenerateResponse(job_id=job.job_id, status=job.status.value)

    @app.get("/api/jobs", response_model=list[Job], tags=["generation"])
    def list_jobs() -> list[Job]:
        """Return every job this server has run, newest first."""
        return manager.list_jobs()

    @app.get("/api/jobs/{job_id}", response_model=Job, tags=["generation"])
    def read_job(job_id: str) -> Job:
        """Return the current state of one job."""
        return _job_or_404(job_id)

    @app.get("/api/jobs/{job_id}/ledger", tags=["ledger"])
    def read_ledger(job_id: str) -> list[LedgerEntry]:
        """Return the change ledger: every file, and why it exists.

        This is the audit trail. Each entry names the stage that made the
        change, the file it touched, and the reason in plain English.
        """
        _job_or_404(job_id)
        return store.get_entries(job_id)

    @app.get("/api/jobs/{job_id}/review", tags=["ledger"])
    def read_review(job_id: str) -> dict[str, object]:
        """Return what the review council found."""
        _job_or_404(job_id)
        findings = store.get_findings(job_id)
        return {"count": len(findings), "findings": findings}

    @app.get("/api/jobs/{job_id}/download", tags=["generation"])
    def download_project(job_id: str) -> Response:
        """Download the generated project as a zip archive."""
        job = _job_or_404(job_id)
        project_directory = manager.output_directory(job_id)
        if not project_directory.is_dir():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This job has not produced any files.",
            )

        archive = build_zip_archive(project_directory)
        file_name = f"{job.project_name or 'generated-backend'}.zip"
        return Response(
            content=archive,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
        )

    def _job_or_404(job_id: str) -> Job:
        """Look up a job, or raise a 404."""
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Unknown job id"
            )
        return job

    return app


def build_zip_archive(project_directory: Path) -> bytes:
    """Pack a generated project into a zip archive held in memory.

    Internal working files are left out, so the download contains only the
    project the user asked for.
    """
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(project_directory.rglob("*")):
            if not file_path.is_file():
                continue
            relative_path = file_path.relative_to(project_directory)
            if _is_internal(relative_path):
                continue
            archive.write(file_path, arcname=str(relative_path))

    return buffer.getvalue()


def _is_internal(relative_path: Path) -> bool:
    """Return True for files that should not be shipped to the user."""
    excluded_directories = {".vibestack", "__pycache__", ".pytest_cache"}
    for part in relative_path.parts:
        if part in excluded_directories:
            return True
    return relative_path.suffix in {".pyc", ".db"}
