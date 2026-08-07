"""Rendering of Jinja2 templates into source files.

Generated code comes from templates rather than from a language model. That
makes generation fast, free, reproducible, and unit-testable: the same spec
always produces the same files. The language model is used where it genuinely
helps — understanding the user's prose (stage 1) and repairing build failures
(the self-healing loop) — not for laying out boilerplate.
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATE_DIRECTORY = Path(__file__).parent / "templates"


def build_environment() -> Environment:
    """Create the Jinja2 environment used for all code generation.

    ``StrictUndefined`` makes a missing template variable raise an error instead
    of silently rendering an empty string, so template bugs surface immediately.
    """
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
        """Render one template with the given variables and return the text."""
        template = self._environment.get_template(template_name)
        return template.render(**context)
