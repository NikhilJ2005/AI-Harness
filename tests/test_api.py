"""End-to-end tests for the HTTP API.

These drive a real generation through the API, including validation, and check
that the change ledger comes back over HTTP. Only the review model is faked.
"""

import time

import pytest

pytest.importorskip("fastapi", reason="the API needs FastAPI")

from fastapi.testclient import TestClient  # noqa: E402

from vibestack.api import build_zip_archive, create_app  # noqa: E402
from vibestack.review import LensReview, ReviewFinding, ReviewLens, Severity  # noqa: E402
from vibestack.validators import SandboxKind  # noqa: E402

JOB_TIMEOUT_SECONDS = 120

EXAMPLE_SPEC = {
    "project_name": "blog_api",
    "description": "A blog API",
    "entities": [
        {
            "name": "User",
            "fields": [
                {"name": "id", "type": "int", "primary_key": True, "nullable": False},
                {"name": "email", "type": "str", "unique": True, "nullable": False},
            ],
            "relationships": [],
        }
    ],
    "auth": {"enabled": True, "strategy": "jwt", "endpoints": ["register", "login", "me"]},
    "features": [],
}


class StubReviewLLM:
    """Stands in for the review council's model."""

    def structured_completion(self, system_prompt, user_prompt, response_model, tier=None):
        if "Your perspective: security" in user_prompt:
            return LensReview(
                findings=[
                    ReviewFinding(
                        lens=ReviewLens.SECURITY,
                        severity=Severity.MEDIUM,
                        file_path="app/config.py",
                        summary="The secret key has a default value",
                        recommendation="Require it to be set from the environment",
                    )
                ],
                overall_note="One issue worth fixing.",
            )
        return LensReview()


@pytest.fixture
def client(tmp_path):
    """An API client backed by a temporary workspace and a stub model."""
    app = create_app(
        workspace_root=tmp_path / "workspace",
        database_path=tmp_path / "ledger.db",
        llm=StubReviewLLM(),
        sandbox=SandboxKind.SUBPROCESS,
    )
    with TestClient(app) as test_client:
        yield test_client


def wait_for_job(client: TestClient, job_id: str) -> dict:
    """Poll a job until it finishes, or fail the test."""
    deadline = time.time() + JOB_TIMEOUT_SECONDS

    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.2)

    raise AssertionError(f"job {job_id} did not finish in time")


def test_health_reports_whether_a_model_is_configured(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model_configured": True}


def test_demo_page_is_served(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "VibeStack" in response.text


def test_generation_requires_a_prompt_or_a_spec(client):
    response = client.post("/api/generate", json={})

    assert response.status_code == 400


def test_unknown_job_returns_404(client):
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/jobs/nope/ledger").status_code == 404


def test_full_run_produces_a_validated_project_and_a_ledger(client):
    """The Phase 3 gate: generate over HTTP, then read the audit trail back."""
    start = client.post("/api/generate", json={"spec": EXAMPLE_SPEC})
    assert start.status_code == 202
    job_id = start.json()["job_id"]

    job = wait_for_job(client, job_id)

    assert job["status"] == "completed", job["error"]
    assert job["project_name"] == "blog_api"
    assert job["file_count"] > 0
    assert job["build_passed"] is True, job["progress"]

    # The ledger explains every generated file.
    ledger = client.get(f"/api/jobs/{job_id}/ledger").json()
    assert len(ledger) >= job["file_count"]

    explained_paths = {entry["file_path"] for entry in ledger}
    assert "app/main.py" in explained_paths
    for entry in ledger:
        assert entry["rationale"].strip()
        assert entry["stage"]

    # And the council's findings are available alongside it.
    review = client.get(f"/api/jobs/{job_id}/review").json()
    assert review["count"] == 1
    assert review["findings"][0]["lens"] == "security"


def test_generated_project_can_be_downloaded(client):
    """The user gets a zip of the project, without our internal files."""
    job_id = client.post("/api/generate", json={"spec": EXAMPLE_SPEC}).json()["job_id"]
    wait_for_job(client, job_id)

    response = client.get(f"/api/jobs/{job_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "blog_api.zip" in response.headers["content-disposition"]
    # A zip archive always starts with this signature.
    assert response.content[:2] == b"PK"


def test_jobs_are_listed(client):
    job_id = client.post("/api/generate", json={"spec": EXAMPLE_SPEC}).json()["job_id"]
    wait_for_job(client, job_id)

    jobs = client.get("/api/jobs").json()

    assert [job["job_id"] for job in jobs] == [job_id]


def test_zip_archive_leaves_out_internal_files(tmp_path):
    """Checkpoints and caches must not be shipped to the user."""
    project = tmp_path / "project"
    (project / "app").mkdir(parents=True)
    (project / "app" / "main.py").write_text("code")
    (project / ".vibestack").mkdir()
    (project / ".vibestack" / "checkpoint.json").write_text("{}")
    (project / "app.db").write_text("binary")

    import io
    import zipfile

    names = zipfile.ZipFile(io.BytesIO(build_zip_archive(project))).namelist()

    assert "app/main.py" in names
    assert not any(name.startswith(".vibestack") for name in names)
    assert "app.db" not in names
