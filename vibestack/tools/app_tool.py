"""Generate the application wiring: entry point, settings, and database setup."""

from vibestack.tools.context import ToolContext


def run(context: ToolContext) -> None:
    blueprint = context.blueprint
    has_auth = blueprint.auth is not None

    context.render_to_file(
        template_name="app/__init__.py.jinja",
        file_path="app/__init__.py",
        rationale="Marks the application directory as a package.",
        project_title=blueprint.project_title,
    )

    context.render_to_file(
        template_name="app/config.py.jinja",
        file_path="app/config.py",
        rationale="Reads configuration from the environment so no secrets are hard-coded.",
        project_name=blueprint.project_title,
        project_slug=blueprint.project_slug,
        has_auth=has_auth,
    )

    context.render_to_file(
        template_name="app/database.py.jinja",
        file_path="app/database.py",
        rationale="Creates the database engine and session factory shared by all routes.",
    )

    context.render_to_file(
        template_name="app/dependencies.py.jinja",
        file_path="app/dependencies.py",
        rationale="Supplies a database session per request and closes it afterwards.",
    )

    context.render_to_file(
        template_name="app/main.py.jinja",
        file_path="app/main.py",
        rationale="Creates the FastAPI application and registers every router.",
        project_name=blueprint.project_title,
        project_title=blueprint.project_title,
        description=blueprint.spec.description,
        router_modules=blueprint.router_modules(),
    )
