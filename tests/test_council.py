"""Tests for the review council."""

from vibestack.review import CouncilReport, LensReview, ReviewFinding, ReviewLens, Severity
from vibestack.spec import Entity, EntityField, FieldType, ProjectSpec
from vibestack.stages.council import (
    FILE_BUDGET_CHARACTERS,
    run_council,
    select_files_for_review,
)
from vibestack.state import GenerationState


def build_state(files: dict[str, str]) -> GenerationState:
    """Build a state carrying the given generated files."""
    spec = ProjectSpec(
        project_name="demo",
        description="",
        entities=[
            Entity(name="Note", fields=[EntityField(name="id", type=FieldType.INTEGER)])
        ],
    )
    state = GenerationState(spec=spec)
    state.generated_files.update(files)
    return state


class RecordingCouncilLLM:
    """Returns a prepared review per lens and records which lenses ran."""

    def __init__(self, review_by_lens: dict[str, LensReview] | None = None) -> None:
        self._review_by_lens = review_by_lens or {}
        self.prompts: list[str] = []

    def structured_completion(self, system_prompt, user_prompt, response_model, tier=None):
        self.prompts.append(user_prompt)
        for lens_value, review in self._review_by_lens.items():
            if f"Your perspective: {lens_value}" in user_prompt:
                return review
        return LensReview()


def test_every_lens_is_reviewed():
    """All five perspectives should run."""
    state = build_state({"app/main.py": "code"})
    llm = RecordingCouncilLLM()

    run_council(state, llm)

    assert len(llm.prompts) == len(list(ReviewLens))
    for lens in ReviewLens:
        assert any(f"Your perspective: {lens.value}" in prompt for prompt in llm.prompts)


def test_findings_are_collected_and_labelled_with_their_lens():
    """A finding must carry the lens that produced it."""
    state = build_state({"app/security.py": "code"})
    review = LensReview(
        findings=[
            ReviewFinding(
                lens=ReviewLens.ARCHITECTURE,  # deliberately wrong; council corrects it
                severity=Severity.HIGH,
                file_path="app/security.py",
                summary="Weak default secret",
                recommendation="Require the secret to be set",
            )
        ],
        overall_note="One issue found.",
    )
    llm = RecordingCouncilLLM({ReviewLens.SECURITY.value: review})

    report = run_council(state, llm)

    assert len(report.findings) == 1
    assert report.findings[0].lens is ReviewLens.SECURITY
    assert report.notes[ReviewLens.SECURITY.value] == "One issue found."


def test_findings_about_unknown_files_are_discarded():
    """A reviewer that invents a path must not mislead the user."""
    state = build_state({"app/main.py": "code"})
    review = LensReview(
        findings=[
            ReviewFinding(
                lens=ReviewLens.TESTING,
                severity=Severity.LOW,
                file_path="app/does_not_exist.py",
                summary="Missing tests",
                recommendation="Add some",
            )
        ]
    )
    llm = RecordingCouncilLLM({ReviewLens.TESTING.value: review})

    report = run_council(state, llm)

    assert report.findings == []


def test_findings_are_sorted_worst_first():
    """The most serious problems should appear at the top."""
    state = build_state({"app/main.py": "code"})

    def finding(severity: Severity) -> ReviewFinding:
        return ReviewFinding(
            lens=ReviewLens.ARCHITECTURE,
            severity=severity,
            file_path="app/main.py",
            summary="x",
            recommendation="y",
        )

    llm = RecordingCouncilLLM(
        {
            ReviewLens.TESTING.value: LensReview(findings=[finding(Severity.LOW)]),
            ReviewLens.SECURITY.value: LensReview(findings=[finding(Severity.HIGH)]),
            ReviewLens.PERFORMANCE.value: LensReview(findings=[finding(Severity.MEDIUM)]),
        }
    )

    report = run_council(state, llm)
    severities = [finding.severity for finding in report.findings]

    assert severities == [Severity.HIGH, Severity.MEDIUM, Severity.LOW]


class PartlyFailingLLM:
    """Fails for one lens and succeeds for the rest."""

    def __init__(self, failing_lens: ReviewLens) -> None:
        self._failing_lens = failing_lens

    def structured_completion(self, system_prompt, user_prompt, response_model, tier=None):
        if f"Your perspective: {self._failing_lens.value}" in user_prompt:
            raise RuntimeError("the model refused")
        return LensReview()


def test_one_failing_reviewer_does_not_lose_the_others():
    """A single bad model call must not discard four good reviews."""
    state = build_state({"app/main.py": "code"})

    report = run_council(state, PartlyFailingLLM(ReviewLens.PERFORMANCE))

    assert report.failed_lenses == [ReviewLens.PERFORMANCE.value]


def test_review_is_skipped_when_there_is_nothing_to_read():
    """An empty project needs no review."""
    state = build_state({})
    llm = RecordingCouncilLLM()

    report = run_council(state, llm)

    assert report.findings == []
    assert llm.prompts == []


def test_file_selection_prefers_application_code_and_respects_the_budget():
    """Reviewers see the important files, and never an unbounded amount."""
    state = build_state(
        {
            "app/security.py": "security code",
            "app/main.py": "main code",
            "README.md": "x" * FILE_BUDGET_CHARACTERS,
        }
    )

    selected = select_files_for_review(state)

    assert "app/security.py" in selected
    assert "app/main.py" in selected
    # The oversized README cannot fit alongside the code, so it is left out.
    assert "README.md" not in selected


def test_report_summarises_severities():
    """The report can answer how bad things are at a glance."""
    report = CouncilReport(
        findings=[
            ReviewFinding(
                lens=ReviewLens.SECURITY,
                severity=Severity.HIGH,
                file_path="a.py",
                summary="s",
                recommendation="r",
            ),
            ReviewFinding(
                lens=ReviewLens.TESTING,
                severity=Severity.LOW,
                file_path="a.py",
                summary="s",
                recommendation="r",
            ),
        ]
    )

    assert report.highest_severity() is Severity.HIGH
    assert report.count_by_severity() == {"high": 1, "low": 1}


def test_empty_report_has_no_highest_severity():
    assert CouncilReport().highest_severity() is None
