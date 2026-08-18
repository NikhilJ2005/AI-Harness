"""The generation agent: one reasoning thread that routes through its tools."""

from collections.abc import Callable
from dataclasses import dataclass

from vibestack.blueprint import build_blueprint
from vibestack.renderer import TemplateRenderer
from vibestack.spec import ProjectSpec
from vibestack.state import GenerationState
from vibestack.tools import api_tool, app_tool, auth_tool, devops_tool, schema_tool
from vibestack.tools.context import ToolContext


@dataclass(frozen=True)
class Tool:
    """One capability the agent can call."""

    name: str
    description: str
    run: Callable[[ToolContext], None]


def build_default_tools() -> list[Tool]:
    """The tools in the order they must run; the order is the dependency chain."""
    return [
        Tool(
            name="schema",
            description="Create SQLAlchemy models for every entity.",
            run=schema_tool.run,
        ),
        Tool(
            name="api",
            description="Create Pydantic schemas and CRUD routers.",
            run=api_tool.run,
        ),
        Tool(
            name="auth",
            description="Create password hashing, tokens, and auth routes.",
            run=auth_tool.run,
        ),
        Tool(
            name="app",
            description="Wire the FastAPI application, settings, and database.",
            run=app_tool.run,
        ),
        Tool(
            name="devops",
            description="Create packaging, Docker, documentation, and tests.",
            run=devops_tool.run,
        ),
    ]


class GenerationAgent:
    """Runs the generation tools over a single shared state."""

    def __init__(self, tools: list[Tool] | None = None) -> None:
        # Allowing tools to be injected keeps the agent easy to test and makes
        # it simple to add a tool later without changing this class.
        self._tools = tools if tools is not None else build_default_tools()

    def run(self, spec: ProjectSpec) -> GenerationState:
        """Generate a project. Returns state holding every file and a ledger entry for each."""
        blueprint = build_blueprint(spec)

        # The blueprint's spec is used, not the caller's: planning may have added
        # fields such as a primary key, and the rest of the run must see those.
        state = GenerationState(spec=blueprint.spec)

        context = ToolContext(
            blueprint=blueprint,
            renderer=TemplateRenderer(),
            state=state,
        )

        # Decisions taken while planning are recorded before any file is written,
        # so the ledger explains changes the user did not explicitly ask for.
        for note in blueprint.notes:
            state.record_change(stage="plan", file_path="(specification)", rationale=note)

        for tool in self._tools:
            context.current_stage = tool.name
            tool.run(context)

        return state
