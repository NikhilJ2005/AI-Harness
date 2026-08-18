"""What the review council looks for and what it reports.

These models live apart from the council itself so that both the council and
``GenerationState`` can use them without importing each other.
"""

from enum import Enum

from pydantic import BaseModel, Field


class ReviewLens(str, Enum):
    """The perspectives a generated project is reviewed from.

    Each lens is a separate reviewer with its own brief. They are deliberately
    independent: an architecture reviewer should not be swayed by what the
    security reviewer happened to notice first.
    """

    ARCHITECTURE = "architecture"
    SECURITY = "security"
    TESTING = "testing"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"


class Severity(str, Enum):
    """How much a finding matters."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Ordered worst first, for sorting findings so the important ones surface.
SEVERITY_ORDER = [Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]


class ReviewFinding(BaseModel):
    """One observation about the generated project."""

    lens: ReviewLens
    severity: Severity
    file_path: str
    summary: str
    recommendation: str


class LensReview(BaseModel):
    """What a single reviewer reported.

    This is the shape the model is asked to return, so it excludes the lens
    itself — the council knows which reviewer it asked.
    """

    findings: list[ReviewFinding] = Field(default_factory=list)
    overall_note: str = ""


class CouncilReport(BaseModel):
    """The merged result of every reviewer."""

    findings: list[ReviewFinding] = Field(default_factory=list)
    notes: dict[str, str] = Field(default_factory=dict)  # lens -> overall note
    failed_lenses: list[str] = Field(default_factory=list)

    def highest_severity(self) -> Severity | None:
        """Return the worst severity present, or None when nothing was found."""
        for severity in SEVERITY_ORDER:
            for finding in self.findings:
                if finding.severity is severity:
                    return severity
        return None

    def count_by_severity(self) -> dict[str, int]:
        """Return how many findings there are at each severity."""
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.severity.value] = counts.get(finding.severity.value, 0) + 1
        return counts
