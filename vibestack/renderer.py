"""Rendering of Jinja2 templates into source files."""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATE_DIRECTORY = Path(__file__).parent / "templates"


def build_environment() -> Environment:
    """StrictUndefined makes a missing template variable an error, not an empty string."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIRECTORY)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


class TemplateRenderer:
    """Renders the generator's templates."""

    def __init__(self) -> None:
        self._environment = build_environment()

    def render(self, template_name: str, **context: Any) -> str:
        template = self._environment.get_template(template_name)
        return template.render(**context)
