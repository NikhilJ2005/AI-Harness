"""Tests for token and cost accounting."""

import pytest

from vibestack.llm_client import MODE_CHAIN, build_mode_chain
from vibestack.spec import Entity, EntityField, FieldType, ProjectSpec
from vibestack.state import GenerationState
from vibestack.usage import (
    UsageRecord,
    calls_by_purpose,
    collect_usage,
    cost_by_purpose,
    purpose_for,
    summarise,
    total_cost,
    total_tokens,
)


class ProjectSpecLike:
    __name__ = "ProjectSpec"


@pytest.mark.parametrize(
    "model_name, expected",
    [("ProjectSpec", "parse"), ("FilePatch", "repair"), ("LensReview", "review")],
)
def test_purpose_is_derived_from_the_requested_shape(model_name, expected):
    """The response model identifies the stage, so callers need not declare it."""
    fake = type(model_name, (), {})
    assert purpose_for(fake) == expected


def test_unknown_response_model_is_other():
    assert purpose_for(type("Whatever", (), {})) == "other"


def _records() -> list[UsageRecord]:
    return [
        UsageRecord(purpose="parse", tier="mid", model="m", prompt_tokens=100,
                    completion_tokens=50, cost_usd=0.001),
        UsageRecord(purpose="review", tier="mid", model="m", prompt_tokens=200,
                    completion_tokens=20, cost_usd=0.002),
        UsageRecord(purpose="review", tier="mid", model="m", prompt_tokens=200,
                    completion_tokens=20, cost_usd=0.003),
    ]


def test_totals():
    records = _records()
    assert total_cost(records) == pytest.approx(0.006)
    assert total_tokens(records) == 590
    assert records[0].total_tokens == 150


def test_grouping_by_purpose():
    records = _records()
    assert cost_by_purpose(records) == pytest.approx({"parse": 0.001, "review": 0.005})
    assert calls_by_purpose(records) == {"parse": 1, "review": 2}


def test_summary():
    summary = summarise(_records())
    assert summary.calls == 3
    assert summary.prompt_tokens == 500
    assert summary.completion_tokens == 90
    assert summary.cost_usd == pytest.approx(0.006)


def test_empty_summary_is_all_zero():
    summary = summarise([])
    assert summary.calls == 0
    assert summary.cost_usd == 0.0


def _state() -> GenerationState:
    spec = ProjectSpec(
        project_name="demo", description="",
        entities=[Entity(name="Note", fields=[EntityField(name="id", type=FieldType.INTEGER)])],
    )
    return GenerationState(spec=spec)


class DrainableLLM:
    def __init__(self, records):
        self._records = records
        self.drained = 0

    def drain_usage(self):
        self.drained += 1
        records, self._records = self._records, []
        return records


def test_collect_usage_moves_records_onto_the_state():
    state = _state()
    llm = DrainableLLM(_records())

    collect_usage(state, llm)

    assert len(state.usage) == 3
    assert llm.drained == 1
    # Draining twice must not duplicate anything.
    collect_usage(state, llm)
    assert len(state.usage) == 3


def test_collect_usage_ignores_clients_that_do_not_track():
    """Every fake client in the test suite is one of these."""
    state = _state()

    collect_usage(state, object())

    assert state.usage == []


def test_usage_survives_a_state_round_trip():
    """Usage has to survive checkpointing like everything else on the state."""
    state = _state()
    state.usage.extend(_records())

    restored = GenerationState.model_validate_json(state.model_dump_json())

    assert total_cost(restored.usage) == pytest.approx(0.006)


def test_mode_chain_puts_the_configured_mode_first():
    assert build_mode_chain("json")[0] == "json"
    assert set(build_mode_chain("json")) == set(MODE_CHAIN)


def test_unknown_mode_falls_back_to_the_default_order():
    assert build_mode_chain("nonsense") == MODE_CHAIN
