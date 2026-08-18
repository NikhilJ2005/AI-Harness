"""The review council: five independent reviewers, read-only, run in parallel."""

from concurrent.futures import ThreadPoolExecutor

from vibestack.llm_protocol import ModelTier, StructuredLLM
from vibestack.review import (
    SEVERITY_ORDER,
    CouncilReport,
    LensReview,
    ReviewFinding,
    ReviewLens,
)
from vibestack.state import GenerationState

# How much source code to show a reviewer. Each reviewer gets the same budget,
# and they run at the same time, so this directly bounds the cost of a review.
FILE_BUDGET_CHARACTERS = 12000

# Files worth reviewing first, as prefixes. Packaging and documentation are
# included only if there is room left over.
PRIORITY_PREFIXES = (
    "app/security.py",
    "app/routers/",
    "app/models/",
    "app/schemas/",
    "app/main.py",
    "app/",
)

# What each reviewer is asked to look for.
LENS_BRIEFS: dict[ReviewLens, str] = {
    ReviewLens.ARCHITECTURE: (
        "Review the structure. Look for layers that leak into each other, "
        "duplicated responsibilities, circular imports, and models, schemas, or "
        "routers that disagree with one another."
    ),
    ReviewLens.SECURITY: (
        "Review for security problems. Look for credentials or secrets that "
        "could be exposed in responses or committed to source, missing "
        "authentication on routes that change data, weak password handling, and "
        "unsafe defaults."
    ),
    ReviewLens.TESTING: (
        "Review the tests. Look for behaviour that is generated but never "
        "exercised, especially authentication, error paths, and validation."
    ),
    ReviewLens.PERFORMANCE: (
        "Review for performance problems. Look for queries inside loops, "
        "list endpoints with no pagination, and missing indexes on columns that "
        "are filtered or joined on."
    ),
    ReviewLens.MAINTAINABILITY: (
        "Review for maintainability. Look for unclear names, missing docstrings "
        "or type hints, values that should be named constants, and code that "
        "would be hard for a new developer to follow."
    ),
}

REVIEW_SYSTEM_PROMPT = """
You are one reviewer on a code review council for a generated FastAPI backend.
Review only from the perspective you are given; other reviewers cover the rest.

Rules:
- Report only real problems you can point at in the code you were shown.
- Every finding must name a file you were shown.
- Say what is wrong and what to do about it, in one clear sentence each.
- Report nothing rather than padding the list. An empty list is a valid answer.
- You are reviewing, not editing. Do not return code.
""".strip()


def select_files_for_review(state: GenerationState) -> dict[str, str]:
    """App code first, capped so a large project cannot make review unbounded."""
    all_paths = sorted(state.generated_files)

    ordered_paths: list[str] = []
    for prefix in PRIORITY_PREFIXES:
        for path in all_paths:
            if path.startswith(prefix) and path not in ordered_paths:
                ordered_paths.append(path)

    # Anything not matched by a prefix goes last.
    for path in all_paths:
        if path not in ordered_paths:
            ordered_paths.append(path)

    selected: dict[str, str] = {}
    characters_used = 0
    for path in ordered_paths:
        content = state.generated_files[path]
        if characters_used + len(content) > FILE_BUDGET_CHARACTERS:
            continue
        selected[path] = content
        characters_used += len(content)

    return selected


def build_review_prompt(
    lens: ReviewLens, files_to_show: dict[str, str], all_paths: list[str]
) -> str:
    sections = [
        f"Your perspective: {lens.value}.",
        LENS_BRIEFS[lens],
        "",
        "Every file in the project:",
        ", ".join(all_paths),
        "",
        "The files to review:",
    ]

    for path, content in files_to_show.items():
        sections.append(f"\n--- {path} ---\n{content}")

    return "\n".join(sections)


def review_with_lens(
    lens: ReviewLens,
    files_to_show: dict[str, str],
    all_paths: list[str],
    llm: StructuredLLM,
) -> LensReview:
    return llm.structured_completion(
        system_prompt=REVIEW_SYSTEM_PROMPT,
        user_prompt=build_review_prompt(lens, files_to_show, all_paths),
        response_model=LensReview,
        # Reviewing is a reading task, so a mid-tier model is enough.
        tier=ModelTier.MID,
    )


def _keep_findings_about_real_files(
    review: LensReview, lens: ReviewLens, known_paths: set[str]
) -> list[ReviewFinding]:
    """Reviewers occasionally invent a path; those findings are dropped."""
    kept: list[ReviewFinding] = []
    for finding in review.findings:
        if finding.file_path not in known_paths:
            continue
        kept.append(finding.model_copy(update={"lens": lens}))
    return kept


def run_council(
    state: GenerationState,
    llm: StructuredLLM,
    lenses: list[ReviewLens] | None = None,
) -> CouncilReport:
    """A failing reviewer is recorded and skipped, never losing the other four."""
    chosen_lenses = lenses if lenses is not None else list(ReviewLens)
    files_to_show = select_files_for_review(state)
    all_paths = sorted(state.generated_files)
    known_paths = set(all_paths)

    report = CouncilReport()
    if not files_to_show:
        return report

    # The reviewers are independent, so they run at the same time. Threads are
    # the right tool here because each one is waiting on a network call.
    with ThreadPoolExecutor(max_workers=len(chosen_lenses)) as executor:
        futures = {
            lens: executor.submit(
                review_with_lens, lens, files_to_show, all_paths, llm
            )
            for lens in chosen_lenses
        }

        for lens, future in futures.items():
            try:
                review = future.result()
            except Exception:
                # Deliberately broad: any reviewer failure is survivable.
                report.failed_lenses.append(lens.value)
                continue

            report.findings.extend(
                _keep_findings_about_real_files(review, lens, known_paths)
            )
            if review.overall_note:
                report.notes[lens.value] = review.overall_note

    report.findings.sort(key=_severity_sort_key)
    return report


def _severity_sort_key(finding: ReviewFinding) -> int:
    return SEVERITY_ORDER.index(finding.severity)
