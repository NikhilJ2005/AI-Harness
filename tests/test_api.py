"""End-to-end tests for the HTTP API, including accounts and isolation."""

import time

import pytest

pytest.importorskip("fastapi", reason="the API needs FastAPI")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from vibestack.api import build_zip_archive, create_app  # noqa: E402
from vibestack.config import Settings  # noqa: E402
from vibestack.db.session import Database  # noqa: E402
from vibestack.review import LensReview, ReviewFinding, ReviewLens, Severity  # noqa: E402
from vibestack.validators import SandboxKind  # noqa: E402

JOB_TIMEOUT_SECONDS = 120
SECRET_KEY = "test-secret"

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
    def structured_completion(self, system_prompt, user_prompt, response_model, tier=None):
        if "Your perspective: security" in user_prompt:
            return LensReview(
                findings=[
                    ReviewFinding(
                        lens=ReviewLens.SECURITY,
                        severity=Severity.MEDIUM,
                        file_path="app/config.py",
                        summary="The secret key has a default value",
                        recommendation="Require it from the environment",
                    )
                ]
            )
        return LensReview()


@pytest.fixture
def database(tmp_path):
    db = Database(url=f"sqlite:///{tmp_path}/api.db")
    db.create_all()
    return db


@pytest.fixture
def client(database):
    app = create_app(
        database=database,
        settings=Settings(_env_file=None, secret_key=SECRET_KEY),
        llm=StubReviewLLM(),
        sandbox=SandboxKind.SUBPROCESS,
    )
    with TestClient(app) as test_client:
        yield test_client


def sign_up(client: TestClient, email: str) -> dict[str, str]:
    """Register an account and return the auth header for it."""
    response = client.post(
        "/api/auth/register", json={"email": email, "password": "super-secret"}
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def wait_for_job(client: TestClient, job_id: str, headers: dict) -> dict:
    deadline = time.time() + JOB_TIMEOUT_SECONDS
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}", headers=headers).json()
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish in time")


# --- accounts ---------------------------------------------------------------


def test_register_then_read_own_account(client):
    headers = sign_up(client, "nikhil@example.com")

    me = client.get("/api/auth/me", headers=headers)

    assert me.status_code == 200
    assert me.json()["email"] == "nikhil@example.com"


def test_login_returns_a_working_token(client):
    sign_up(client, "nikhil@example.com")

    response = client.post(
        "/api/auth/login",
        json={"email": "nikhil@example.com", "password": "super-secret"},
    )

    assert response.status_code == 200
    token = response.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200


def test_wrong_password_is_refused(client):
    sign_up(client, "nikhil@example.com")

    response = client.post(
        "/api/auth/login", json={"email": "nikhil@example.com", "password": "wrong"}
    )

    assert response.status_code == 401


def test_duplicate_email_is_refused(client):
    sign_up(client, "nikhil@example.com")

    response = client.post(
        "/api/auth/register",
        json={"email": "nikhil@example.com", "password": "super-secret"},
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    "path", ["/api/jobs", "/api/auth/me", "/api/jobs/anything", "/api/jobs/anything/ledger"]
)
def test_endpoints_require_a_token(client, path):
    assert client.get(path).status_code == 401


def test_a_forged_token_is_refused(client):
    headers = {"Authorization": "Bearer not-a-real-token"}

    assert client.get("/api/jobs", headers=headers).status_code == 401


# --- generation and isolation ------------------------------------------------


def test_full_run_produces_a_validated_project_and_a_ledger(client):
    headers = sign_up(client, "nikhil@example.com")

    start = client.post("/api/generate", json={"spec": EXAMPLE_SPEC}, headers=headers)
    assert start.status_code == 202
    job_id = start.json()["job_id"]

    job = wait_for_job(client, job_id, headers)
    assert job["status"] == "completed", job["error"]
    assert job["build_passed"] is True, job["progress"]
    assert job["file_count"] > 0

    ledger = client.get(f"/api/jobs/{job_id}/ledger", headers=headers).json()
    assert len(ledger) >= job["file_count"]
    assert all(entry["rationale"].strip() for entry in ledger)

    review = client.get(f"/api/jobs/{job_id}/review", headers=headers).json()
    assert review["count"] == 1
    # Findings are counted from the database, so they survive a restart.
    assert job["review_counts"] == {"medium": 1}


def test_one_user_cannot_see_anothers_job(client):
    alice = sign_up(client, "alice@example.com")
    bob = sign_up(client, "bob@example.com")

    job_id = client.post(
        "/api/generate", json={"spec": EXAMPLE_SPEC}, headers=alice
    ).json()["job_id"]
    wait_for_job(client, job_id, alice)

    # Bob gets a 404 rather than a 403: he should not learn the job exists.
    assert client.get(f"/api/jobs/{job_id}", headers=bob).status_code == 404
    assert client.get(f"/api/jobs/{job_id}/ledger", headers=bob).status_code == 404
    assert client.get(f"/api/jobs/{job_id}/download", headers=bob).status_code == 404
    assert client.get("/api/jobs", headers=bob).json() == []


def test_jobs_are_listed_for_their_owner(client):
    headers = sign_up(client, "nikhil@example.com")
    job_id = client.post(
        "/api/generate", json={"spec": EXAMPLE_SPEC}, headers=headers
    ).json()["job_id"]
    wait_for_job(client, job_id, headers)

    jobs = client.get("/api/jobs", headers=headers).json()

    assert [job["job_id"] for job in jobs] == [job_id]


def test_generation_requires_a_prompt_or_a_spec(client):
    headers = sign_up(client, "nikhil@example.com")

    assert client.post("/api/generate", json={}, headers=headers).status_code == 400


# --- results -----------------------------------------------------------------


def test_files_and_download_come_from_the_database(client):
    headers = sign_up(client, "nikhil@example.com")
    job_id = client.post(
        "/api/generate", json={"spec": EXAMPLE_SPEC}, headers=headers
    ).json()["job_id"]
    wait_for_job(client, job_id, headers)

    files = client.get(f"/api/jobs/{job_id}/files", headers=headers).json()
    assert "app/main.py" in files["paths"]
    assert "FastAPI" in files["files"]["app/main.py"]

    download = client.get(f"/api/jobs/{job_id}/download", headers=headers)
    assert download.status_code == 200
    assert download.content[:2] == b"PK"


def test_usage_is_reported(client):
    headers = sign_up(client, "nikhil@example.com")
    job_id = client.post(
        "/api/generate", json={"spec": EXAMPLE_SPEC}, headers=headers
    ).json()["job_id"]
    wait_for_job(client, job_id, headers)

    usage = client.get(f"/api/jobs/{job_id}/usage", headers=headers).json()

    assert "summary" in usage
    assert usage["summary"]["cost_usd"] == 0.0  # the stub records nothing


# --- durability and secrets ---------------------------------------------------


def test_history_survives_a_restart(database):
    """A new app over the same database still sees the finished job."""
    settings = Settings(_env_file=None, secret_key=SECRET_KEY)
    first = create_app(database=database, settings=settings, llm=StubReviewLLM(),
                       sandbox=SandboxKind.SUBPROCESS)

    with TestClient(first) as client:
        headers = sign_up(client, "nikhil@example.com")
        job_id = client.post(
            "/api/generate", json={"spec": EXAMPLE_SPEC}, headers=headers
        ).json()["job_id"]
        wait_for_job(client, job_id, headers)

    second = create_app(database=database, settings=settings, llm=StubReviewLLM(),
                        sandbox=SandboxKind.SUBPROCESS)
    with TestClient(second) as client:
        login = client.post(
            "/api/auth/login",
            json={"email": "nikhil@example.com", "password": "super-secret"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        job = client.get(f"/api/jobs/{job_id}", headers=headers).json()
        assert job["status"] == "completed"
        assert job["file_count"] > 0

        ledger = client.get(f"/api/jobs/{job_id}/ledger", headers=headers).json()
        assert len(ledger) > 0


def test_a_supplied_api_key_never_reaches_the_database(client, database):
    """BYOK keys live in the browser. Ours must not keep a copy anywhere."""
    headers = sign_up(client, "nikhil@example.com")
    secret = "sk-or-v1-DO-NOT-STORE-THIS"

    job_id = client.post(
        "/api/generate",
        json={"spec": EXAMPLE_SPEC, "api_key": secret},
        headers=headers,
    ).json()["job_id"]
    wait_for_job(client, job_id, headers)

    # Search every text column of every table for the key.
    with database.session() as session:
        table_names = [
            row[0]
            for row in session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        ]
        for table_name in table_names:
            rows = session.execute(text(f"SELECT * FROM {table_name}")).fetchall()
            for row in rows:
                for value in row:
                    if isinstance(value, str):
                        assert secret not in value, f"key leaked into {table_name}"

    # And it must not come back out through the API either.
    job = client.get(f"/api/jobs/{job_id}", headers=headers).json()
    assert secret not in str(job)


def test_zip_archive_contains_the_generated_files():
    archive = build_zip_archive({"app/main.py": "code", "README.md": "docs"})

    import io
    import zipfile

    names = zipfile.ZipFile(io.BytesIO(archive)).namelist()
    assert sorted(names) == ["README.md", "app/main.py"]


def test_stale_jobs_are_reaped_on_start_up(database):
    """A job left running by a killed process must not sit there forever."""
    from datetime import datetime, timedelta, timezone

    from vibestack.db.models import Job as JobRow, User

    with database.session() as session:
        user = User(email="a@b.com", password_hash="x")
        session.add(user)
        session.flush()
        session.add(
            JobRow(
                id="stalejob0001",
                user_id=user.id,
                status="running",
                updated_at=datetime.now(timezone.utc) - timedelta(hours=2),
            )
        )

    create_app(
        database=database,
        settings=Settings(_env_file=None, secret_key=SECRET_KEY),
        llm=StubReviewLLM(),
        sandbox=SandboxKind.SUBPROCESS,
    )

    with database.session() as session:
        reaped = session.get(JobRow, "stalejob0001")
        assert reaped.status == "failed"
        assert "restart" in reaped.error
