"""What the review council looks for and what it reports."""

from enum import Enum

from pydantic import BaseModel, Field


class ReviewLens(str, Enum):
    """The five review perspectives. Deliberately independent of each other."""

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
    """What one reviewer returns. Excludes the lens: the council knows who it asked."""

    findings: list[ReviewFinding] = Field(default_factory=list)
    overall_note: str = ""


class CouncilReport(BaseModel):
    """The merged result of every reviewer."""

    findings: list[ReviewFinding] = Field(default_factory=list)
    notes: dict[str, str] = Field(default_factory=dict)  # lens -> overall note
    failed_lenses: list[str] = Field(default_factory=list)

    def highest_severity(self) -> Severity | None:
        for severity in SEVERITY_ORDER:
            for finding in self.findings:
                if finding.severity is severity:
                    return severity
        return None

    def count_by_severity(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.severity.value] = counts.get(finding.severity.value, 0) + 1
        return counts
