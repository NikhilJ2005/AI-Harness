"""End-to-end checks of validation and self-healing on a real project.

These generate an actual project, run the real gates against it, and — in the
healing test — break it on purpose to prove the loop detects and repairs the
damage. Only the repair model is faked, because calling a real one would make
the test slow, costly, and non-deterministic.

The generated project needs FastAPI and SQLAlchemy installed to run, so these
tests skip when those are unavailable.
"""

import pytest

from vibestack.agent import GenerationAgent
from vibestack.healing import validate_and_heal
from vibestack.spec import (
    Entity,
    EntityField,
    FieldType,
    ProjectSpec,
    Relationship,
    RelationshipType,
)
from vibestack.stages.reflect import ErrorCategory, FilePatch, classify_build_error
from vibestack.validation import ValidationGate
from vibestack.validators import SubprocessValidator
from vibestack.workspace import write_workspace

pytest.importorskip("fastapi", reason="the generated project needs FastAPI to run")
pytest.importorskip("sqlalchemy", reason="the generated project needs SQLAlchemy to run")


def blog_spec() -> ProjectSpec:
    """A small blog specification with a relationship and authentication."""
    user = Entity(
        name="User",
        fields=[
            EntityField(name="id", type=FieldType.INTEGER, primary_key=True),
            EntityField(name="email", type=FieldType.STRING, unique=True, nullable=False),
        ],
        relationships=[
            Relationship(
                target_entity="Post",
                type=RelationshipType.ONE_TO_MANY,
                back_populates="author",
            )
        ],
    )
    post = Entity(
        name="Post",
        fields=[
            EntityField(name="id", type=FieldType.INTEGER, primary_key=True),
            EntityField(name="title", type=FieldType.STRING, nullable=False),
            EntityField(name="body", type=FieldType.TEXT),
        ],
    )
    return ProjectSpec(
        project_name="blog_api", description="A blog API", entities=[user, post]
    )


@pytest.fixture
def generated_project(tmp_path):
    """Generate the blog project into a temporary directory."""
    state = GenerationAgent().run(blog_spec())
    write_workspace(state, tmp_path)
    return state, tmp_path


def test_a_generated_project_passes_every_gate(generated_project):
    """The generator's own output must survive import, boot, and its tests."""
    _, project_directory = generated_project

    result = SubprocessValidator().validate(project_directory)

    assert result.passed is True, result.logs
    assert result.failed_gate is None


def test_a_broken_project_is_caught_at_the_right_gate(generated_project):
    """Removing an import should fail the import gate with a usable log."""
    state, project_directory = generated_project

    model_path = project_directory / "app" / "models" / "post.py"
    model_path.write_text(
        model_path.read_text().replace(", Text", ""), encoding="utf-8"
    )

    result = SubprocessValidator().validate(project_directory)

    assert result.passed is False
    assert result.failed_gate is ValidationGate.IMPORT
    assert classify_build_error(result.logs) is ErrorCategory.UNDEFINED_NAME
    # The log must name the file at fault, or repair has nothing to work with.
    assert "app/models/post.py" in result.logs


class RestoringRepairLLM:
    """Stands in for the repair model by restoring a known-good file."""

    def __init__(self, file_path: str, correct_content: str) -> None:
        self._file_path = file_path
        self._correct_content = correct_content
        self.call_count = 0
        self.last_prompt = ""

    def structured_completion(self, system_prompt, user_prompt, response_model, tier=None):
        self.call_count += 1
        self.last_prompt = user_prompt
        return FilePatch(
            file_path=self._file_path,
            new_content=self._correct_content,
            explanation="restored the missing Text import",
        )


def test_a_broken_project_is_detected_and_healed(generated_project):
    """The full loop: break a real project, then watch it repair itself."""
    state, project_directory = generated_project

    relative_path = "app/models/post.py"
    model_path = project_directory / relative_path
    correct_content = model_path.read_text()

    # Break it exactly as a model might: drop an import that is still used.
    broken_content = correct_content.replace(", Text", "")
    model_path.write_text(broken_content, encoding="utf-8")
    state.generated_files[relative_path] = broken_content

    llm = RestoringRepairLLM(relative_path, correct_content)
    messages: list[str] = []

    result = validate_and_heal(
        state,
        project_directory,
        SubprocessValidator(),
        llm,
        on_progress=messages.append,
    )

    # It recovered, and needed exactly one repair to do so.
    assert result.passed is True, result.logs
    assert state.build_passed is True
    assert state.heal_attempts == 1
    assert llm.call_count == 1

    # The repair reached the file on disk, not just the in-memory state.
    assert model_path.read_text() == correct_content

    # The model was told what kind of error it was, and shown the failing file.
    assert "undefined_name" in llm.last_prompt
    assert relative_path in llm.last_prompt

    # And the repair is recorded in the ledger for the user to review.
    heal_entries = [entry for entry in state.ledger if entry.stage == "self-heal"]
    assert len(heal_entries) == 1
    assert heal_entries[0].file_path == relative_path


def test_unfixable_project_trips_the_circuit_breaker(generated_project):
    """A repair model that cannot help must not cause an endless loop."""
    state, project_directory = generated_project

    relative_path = "app/models/post.py"
    model_path = project_directory / relative_path
    broken_content = model_path.read_text().replace(", Text", "")
    model_path.write_text(broken_content, encoding="utf-8")
    state.generated_files[relative_path] = broken_content

    # This "repair" never actually fixes anything.
    useless_llm = RestoringRepairLLM(relative_path, broken_content)

    result = validate_and_heal(
        state, project_directory, SubprocessValidator(), useless_llm
    )

    assert result.passed is False
    assert state.heal_attempts == 3
    assert useless_llm.call_count == 3
    assert "undefined_name" in state.error_log
