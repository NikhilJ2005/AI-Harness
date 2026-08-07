"""The shared context every generation tool receives."""

from dataclasses import dataclass

from vibestack.blueprint import Blueprint
from vibestack.renderer import TemplateRenderer
from vibestack.state import GenerationState


@dataclass
class ToolContext:
    """Everything a tool needs, and the state it contributes to.

    There is exactly one of these per generation run. Because every tool reads
    the same blueprint and writes to the same state, the files they produce stay
    consistent with one another.
    """

    blueprint: Blueprint
    renderer: TemplateRenderer
    state: GenerationState
    current_stage: str = "generate"

    def add_file(self, file_path: str, content: str, rationale: str) -> None:
        """Record a generated file and why it was created."""
        self.state.generated_files[file_path] = content
        self.state.record_change(
            stage=self.current_stage,
            file_path=file_path,
            rationale=rationale,
        )

    def render_to_file(
        self,
        template_name: str,
        file_path: str,
        rationale: str,
        **context: object,
    ) -> None:
        """Render a template and store the result as a generated file."""
        content = self.renderer.render(template_name, **context)
        self.add_file(file_path, content, rationale)
