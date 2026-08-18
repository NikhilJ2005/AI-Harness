"""What each model call cost, in tokens and dollars."""

from pydantic import BaseModel, Field

# Which stage a call belongs to, worked out from the shape it asked for. Doing
# it this way keeps the StructuredLLM protocol unchanged: callers do not have to
# remember to declare what they are doing.
PURPOSE_BY_RESPONSE_MODEL = {
    "ProjectSpec": "parse",
    "FilePatch": "repair",
    "LensReview": "review",
}


def purpose_for(response_model: type) -> str:
    return PURPOSE_BY_RESPONSE_MODEL.get(response_model.__name__, "other")


class UsageRecord(BaseModel):
    """One model call. Cost is 0.0 when the provider reports no price."""

    purpose: str
    tier: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def total_cost(records: list[UsageRecord]) -> float:
    return sum(record.cost_usd for record in records)


def total_tokens(records: list[UsageRecord]) -> int:
    return sum(record.total_tokens for record in records)


def cost_by_purpose(records: list[UsageRecord]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for record in records:
        totals[record.purpose] = totals.get(record.purpose, 0.0) + record.cost_usd
    return totals


def calls_by_purpose(records: list[UsageRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.purpose] = counts.get(record.purpose, 0) + 1
    return counts


class UsageSummary(BaseModel):
    """A run's cost, in the shape the API and the benchmark report it."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    cost_by_purpose: dict[str, float] = Field(default_factory=dict)
    calls_by_purpose: dict[str, int] = Field(default_factory=dict)


def summarise(records: list[UsageRecord]) -> UsageSummary:
    return UsageSummary(
        calls=len(records),
        prompt_tokens=sum(record.prompt_tokens for record in records),
        completion_tokens=sum(record.completion_tokens for record in records),
        cost_usd=total_cost(records),
        cost_by_purpose=cost_by_purpose(records),
        calls_by_purpose=calls_by_purpose(records),
    )


def collect_usage(state, llm) -> None:
    """Move any recorded usage off the client and onto the run state.

    Does nothing for clients that do not track usage, which is every fake used
    in the tests.
    """
    drain = getattr(llm, "drain_usage", None)
    if drain is None:
        return
    state.usage.extend(drain())
