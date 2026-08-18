"""The shared context every generation tool receives."""

from dataclasses import dataclass

from vibestack.blueprint import Blueprint
from vibestack.renderer import TemplateRenderer
from vibestack.state import GenerationState


@dataclass
class ToolContext:
    """One per run. Every tool reads the same blueprint and writes the same state."""

    blueprint: Blueprint
    renderer: TemplateRenderer
    state: GenerationState
    current_stage: str = "generate"

    def add_file(self, file_path: str, content: str, rationale: str) -> None:
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
        content = self.renderer.render(template_name, **context)
        self.add_file(file_path, content, rationale)
