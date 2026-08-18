"""The pipeline that turns a prompt into a validated project on disk."""

from pathlib import Path

from vibestack.agent import GenerationAgent
from vibestack.checkpoint import save_checkpoint
from vibestack.healing import ProgressCallback, validate_and_heal
from vibestack.llm_protocol import StructuredLLM
from vibestack.spec import ProjectSpec
from vibestack.stages.parse import parse_prompt_to_spec
from vibestack.state import GenerationState
from vibestack.validation import Validator
from vibestack.workspace import write_workspace


def generate_from_spec(
    spec: ProjectSpec,
    output_directory: Path,
    validator: Validator | None = None,
    llm: StructuredLLM | None = None,
    on_progress: ProgressCallback | None = None,
) -> GenerationState:
    """Generate, write to disk, then validate and repair if a validator is given."""
    agent = GenerationAgent()
    state = agent.run(spec)

    write_workspace(state, output_directory)
    save_checkpoint(state, output_directory)

    if validator is not None:
        validate_and_heal(state, output_directory, validator, llm, on_progress)
        save_checkpoint(state, output_directory)

    return state


def run_pipeline(
    prompt: str,
    llm: StructuredLLM,
    output_directory: Path,
    validator: Validator | None = None,
    on_progress: ProgressCallback | None = None,
) -> GenerationState:
    """Prompt to validated project. Only stage 1 and the repairs use a model."""
    spec = parse_prompt_to_spec(prompt, llm)
    return generate_from_spec(
        spec,
        output_directory,
        validator=validator,
        llm=llm,
        on_progress=on_progress,
    )
