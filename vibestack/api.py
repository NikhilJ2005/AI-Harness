"""The VibeStack HTTP API and demo page.

    uvicorn vibestack.api:create_app --factory --reload

Built by a factory rather than at import time: building it opens a database,
and importing a module should never have that kind of side effect.
"""

import io
import zipfile
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from vibestack.auth import (
    AuthError,
    authenticate,
    create_access_token,
    find_user_by_email,
    read_email_from_token,
    register_user,
)
from vibestack.config import Settings
from vibestack.db.repository import Repository
from vibestack.db.session import Database
from vibestack.jobs import Job, JobManager
from vibestack.llm_client import LLMClient
from vibestack.llm_protocol import StructuredLLM
from vibestack.spec import ProjectSpec
from vibestack.state import LedgerEntry
from vibestack.usage import summarise
from vibestack.validators import SandboxKind, build_validator

STATIC_DIRECTORY = Path(__file__).parent / "static"
bearer_scheme = HTTPBearer(auto_error=False)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str


class GenerateRequest(BaseModel):
    """Exactly one of prompt or spec is required. A spec needs no API key."""

    prompt: str = ""
    spec: ProjectSpec | None = None
    # A key supplied here is used for this job only and never written down.
    api_key: str = ""


class GenerateResponse(BaseModel):
    job_id: str
    status: str


def build_llm_or_none(settings: Settings) -> StructuredLLM | None:
    if not settings.has_api_key():
        return None
    return LLMClient(settings)


def build_llm_factory(settings: Settings):
    """Builds a client from a user's own key, without mutating our settings."""

    def factory(api_key: str) -> StructuredLLM:
        return LLMClient(settings.model_copy(update={"openrouter_api_key": api_key}))

    return factory


def create_app(
    database: Database | None = None,
    settings: Settings | None = None,
    llm: StructuredLLM | None = None,
    sandbox: SandboxKind = SandboxKind.AUTO,
) -> FastAPI:
    """Dependencies are injectable so tests can supply a fake model and temp database."""
    settings = settings or Settings()
    database = database or Database(settings)
    database.create_all()

    manager = JobManager(
        database=database,
        validator=build_validator(sandbox),
        llm=llm if llm is not None else build_llm_or_none(settings),
        llm_factory=build_llm_factory(settings),
    )

    # Anything left running belongs to a process that no longer exists.
    reaped = manager.reap_stale_jobs()

    app = FastAPI(
        title="VibeStack",
        description="Generate a FastAPI backend, prove it works, and explain every change.",
        version="0.2.0",
    )
    app.state.reaped_on_start = reaped

    def current_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    ):
        """Resolve the caller, or refuse the request."""
        unauthorised = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
        if credentials is None:
            raise unauthorised

        email = read_email_from_token(credentials.credentials, settings)
        if email is None:
            raise unauthorised

        with database.session() as session:
            user = find_user_by_email(session, email)
            if user is None:
                raise unauthorised
            return UserResponse(id=user.id, email=user.email)

    # --- pages and health ---------------------------------------------------

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def demo_page() -> str:
        return (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")

    @app.get("/api/health", tags=["health"])
    def health_check() -> dict[str, object]:
        return {"status": "ok", "model_configured": manager.has_model()}

    # --- accounts -----------------------------------------------------------

    @app.post("/api/auth/register", response_model=TokenResponse, status_code=201, tags=["auth"])
    def register(request: RegisterRequest) -> TokenResponse:
        with database.session() as session:
            try:
                user = register_user(session, request.email, request.password)
            except AuthError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
            email = user.email
        return TokenResponse(access_token=create_access_token(email, settings))

    @app.post("/api/auth/login", response_model=TokenResponse, tags=["auth"])
    def login(request: LoginRequest) -> TokenResponse:
        with database.session() as session:
            try:
                user = authenticate(session, request.email, request.password)
            except AuthError as error:
                raise HTTPException(
                    status_code=401,
                    detail=str(error),
                    headers={"WWW-Authenticate": "Bearer"},
                ) from error
            email = user.email
        return TokenResponse(access_token=create_access_token(email, settings))

    @app.get("/api/auth/me", response_model=UserResponse, tags=["auth"])
    def read_me(user: UserResponse = Depends(current_user)) -> UserResponse:
        return user

    # --- generation ---------------------------------------------------------

    @app.post("/api/generate", response_model=GenerateResponse, status_code=202, tags=["generation"])
    def start_generation(
        request: GenerateRequest, user: UserResponse = Depends(current_user)
    ) -> GenerateResponse:
        if not request.prompt and request.spec is None:
            raise HTTPException(
                status_code=400, detail="Provide either a prompt or a specification."
            )

        job = manager.submit(
            user_id=user.id,
            prompt=request.prompt,
            spec=request.spec,
            api_key=request.api_key or None,
        )
        return GenerateResponse(job_id=job.job_id, status=job.status.value)

    @app.get("/api/jobs", response_model=list[Job], tags=["generation"])
    def list_jobs(user: UserResponse = Depends(current_user)) -> list[Job]:
        return manager.list_jobs(user.id)

    @app.get("/api/jobs/{job_id}", response_model=Job, tags=["generation"])
    def read_job(job_id: str, user: UserResponse = Depends(current_user)) -> Job:
        return _job_or_404(job_id, user)

    @app.get("/api/jobs/{job_id}/ledger", tags=["ledger"])
    def read_ledger(
        job_id: str, user: UserResponse = Depends(current_user)
    ) -> list[LedgerEntry]:
        """The audit trail: every file, the stage that made it, and why."""
        _job_or_404(job_id, user)
        with database.session() as session:
            return Repository(session).get_entries(job_id)

    @app.get("/api/jobs/{job_id}/review", tags=["ledger"])
    def read_review(job_id: str, user: UserResponse = Depends(current_user)) -> dict:
        _job_or_404(job_id, user)
        with database.session() as session:
            findings = Repository(session).get_findings(job_id)
        return {"count": len(findings), "findings": findings}

    @app.get("/api/jobs/{job_id}/usage", tags=["ledger"])
    def read_usage(job_id: str, user: UserResponse = Depends(current_user)) -> dict:
        _job_or_404(job_id, user)
        with database.session() as session:
            records = Repository(session).get_usage(job_id)
        return {"records": records, "summary": summarise(records)}

    @app.get("/api/jobs/{job_id}/files", tags=["generation"])
    def list_files(job_id: str, user: UserResponse = Depends(current_user)) -> dict:
        """Paths and contents, for the file browser in the interface."""
        _job_or_404(job_id, user)
        with database.session() as session:
            files = Repository(session).get_files(job_id)
        return {"paths": sorted(files), "files": files}

    @app.get("/api/jobs/{job_id}/download", tags=["generation"])
    def download_project(
        job_id: str, user: UserResponse = Depends(current_user)
    ) -> Response:
        job = _job_or_404(job_id, user)
        with database.session() as session:
            files = Repository(session).get_files(job_id)

        if not files:
            raise HTTPException(
                status_code=404, detail="This job has not produced any files."
            )

        file_name = f"{job.project_name or 'generated-backend'}.zip"
        return Response(
            content=build_zip_archive(files),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
        )

    def _job_or_404(job_id: str, user: UserResponse) -> Job:
        """Scoped by user, so another account's job is indistinguishable from a missing one."""
        job = manager.get(job_id, user.id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job id")
        return job

    return app


def build_zip_archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in sorted(files.items()):
            archive.writestr(path, content)
    return buffer.getvalue()
