"""The pipeline that turns a prompt into a project on disk.

This function reads top to bottom on purpose: it *is* the architecture. Later
phases insert Docker validation and the self-healing loop between generation and
packaging, without changing the shape of this code.
"""

from pathlib import Path

from vibestack.agent import GenerationAgent
from vibestack.llm_protocol import StructuredLLM
from vibestack.spec import ProjectSpec
from vibestack.stages.parse import parse_prompt_to_spec
from vibestack.state import GenerationState
from vibestack.workspace import write_workspace


def generate_from_spec(spec: ProjectSpec, output_directory: Path) -> GenerationState:
    """Generate a project from an existing specification and write it to disk."""
    agent = GenerationAgent()
    state = agent.run(spec)
    write_workspace(state, output_directory)
    return state


def run_pipeline(
    prompt: str, llm: StructuredLLM, output_directory: Path
) -> GenerationState:
    """Turn a natural-language prompt into a generated project.

    Stage 1 uses the language model, because understanding informal prose is
    what models are good at. Everything after it is deterministic: the same
    specification always produces the same files.
    """
    spec = parse_prompt_to_spec(prompt, llm)
    return generate_from_spec(spec, output_directory)
