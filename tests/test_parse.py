"""Tests for the natural-language parsing stage.

These tests use a fake LLM client so they run instantly with no network access.
The fake records what it was asked and returns a canned spec, letting us verify
that ``parse_prompt_to_spec`` wires the request together correctly.
"""

from vibestack.llm_protocol import ModelTier
from vibestack.spec import Entity, EntityField, FieldType, ProjectSpec
from vibestack.stages.parse import parse_prompt_to_spec


class FakeLLM:
    """A stand-in for the real LLM client that returns a fixed spec."""

    def __init__(self, spec_to_return: ProjectSpec) -> None:
        self._spec_to_return = spec_to_return
        self.last_user_prompt: str | None = None
        self.last_response_model: type | None = None
        self.last_tier: ModelTier | None = None

    def structured_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type,
        tier: ModelTier = ModelTier.MID,
    ):
        self.last_user_prompt = user_prompt
        self.last_response_model = response_model
        self.last_tier = tier
        return self._spec_to_return


def _example_spec() -> ProjectSpec:
    return ProjectSpec(
        project_name="blog_api",
        description="A blog API",
        entities=[
            Entity(
                name="Post",
                fields=[
                    EntityField(name="id", type=FieldType.INTEGER, primary_key=True),
                    EntityField(name="title", type=FieldType.STRING),
                ],
            )
        ],
    )


def test_parse_returns_the_spec_from_the_llm():
    """The parser should return whatever spec the LLM produced."""
    expected = _example_spec()
    fake = FakeLLM(expected)

    result = parse_prompt_to_spec("a blog API with posts", fake)

    assert result == expected


def test_parse_passes_prompt_and_requests_project_spec():
    """The parser should forward the user's prompt and ask for a ProjectSpec."""
    fake = FakeLLM(_example_spec())

    parse_prompt_to_spec("a blog API with posts", fake)

    assert fake.last_user_prompt == "a blog API with posts"
    assert fake.last_response_model is ProjectSpec
