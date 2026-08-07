"""Tests for the persistent change ledger."""

from vibestack.ledger_store import LedgerStore
from vibestack.review import CouncilReport, ReviewFinding, ReviewLens, Severity
from vibestack.spec import Entity, EntityField, FieldType, ProjectSpec
from vibestack.state import GenerationState


def build_state() -> GenerationState:
    """Build a state with a couple of ledger entries."""
    spec = ProjectSpec(
        project_name="blog_api",
        description="A blog",
        entities=[
            Entity(name="Note", fields=[EntityField(name="id", type=FieldType.INTEGER)])
        ],
    )
    state = GenerationState(spec=spec)
    state.generated_files["app/main.py"] = "code"
    state.record_change("app", "app/main.py", "Creates the FastAPI application.")
    state.record_change("self-heal", "app/main.py", "undefined_name: added an import.")
    state.build_passed = True
    state.heal_attempts = 1
    return state


def example_report() -> CouncilReport:
    """Build a report with one finding."""
    return CouncilReport(
        findings=[
            ReviewFinding(
                lens=ReviewLens.SECURITY,
                severity=Severity.HIGH,
                file_path="app/main.py",
                summary="Default secret key",
                recommendation="Require it to be configured",
            )
        ]
    )


def test_saving_and_reading_a_run(tmp_path):
    """A saved run should come back exactly as it went in."""
    store = LedgerStore(tmp_path / "ledger.db")
    state = build_state()

    store.save_run("job-1", state, prompt="a blog API", report=example_report())

    run = store.get_run("job-1")
    assert run["project_name"] == "blog_api"
    assert run["prompt"] == "a blog API"
    assert run["file_count"] == 1
    assert run["build_passed"] == 1
    assert run["heal_attempts"] == 1


def test_ledger_entries_keep_their_order(tmp_path):
    """The audit trail must read in the order things happened."""
    store = LedgerStore(tmp_path / "ledger.db")

    store.save_run("job-1", build_state())
    entries = store.get_entries("job-1")

    assert [entry.stage for entry in entries] == ["app", "self-heal"]
    assert "added an import" in entries[1].rationale


def test_review_findings_round_trip(tmp_path):
    """Findings should survive being written and read back."""
    store = LedgerStore(tmp_path / "ledger.db")

    store.save_run("job-1", build_state(), report=example_report())
    findings = store.get_findings("job-1")

    assert len(findings) == 1
    assert findings[0].lens is ReviewLens.SECURITY
    assert findings[0].severity is Severity.HIGH


def test_saving_the_same_run_twice_does_not_duplicate_entries(tmp_path):
    """A run is saved after generation and again after review."""
    store = LedgerStore(tmp_path / "ledger.db")
    state = build_state()

    store.save_run("job-1", state)
    store.save_run("job-1", state, report=example_report())

    assert len(store.get_entries("job-1")) == 2
    assert len(store.get_findings("job-1")) == 1


def test_runs_are_listed_and_unknown_ids_return_nothing(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    store.save_run("job-1", build_state())

    assert len(store.list_runs()) == 1
    assert store.get_run("missing") is None
    assert store.get_entries("missing") == []


def test_a_new_store_reads_an_existing_database(tmp_path):
    """The ledger outlives the process that wrote it."""
    database_path = tmp_path / "ledger.db"
    LedgerStore(database_path).save_run("job-1", build_state())

    reopened = LedgerStore(database_path)

    assert reopened.get_run("job-1") is not None
    assert len(reopened.get_entries("job-1")) == 2
