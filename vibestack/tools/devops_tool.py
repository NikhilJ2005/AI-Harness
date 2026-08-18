"""Generate packaging, container, and documentation files."""

from vibestack.blueprint import Blueprint
from vibestack.tools.context import ToolContext

# Dependencies every generated project needs.
BASE_DEPENDENCIES = [
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.29.0",
    "sqlalchemy>=2.0.0",
    "pydantic>=2.6.0",
    "pydantic-settings>=2.2.0",
    "psycopg[binary]>=3.1.0",
]

# Extra dependencies required only when authentication is generated.
AUTH_DEPENDENCIES = [
    "pyjwt>=2.8.0",
    "bcrypt>=4.1.0",
    "python-multipart>=0.0.9",
]


def build_dependency_list(blueprint: Blueprint) -> list[str]:
    dependencies = list(BASE_DEPENDENCIES)
    if blueprint.auth is not None:
        dependencies.extend(AUTH_DEPENDENCIES)
    return dependencies


def build_resource_list(blueprint: Blueprint) -> list[dict[str, str]]:
    return [
        {
            "entity_name": plan.names.entity_name,
            "route_prefix": plan.names.route_prefix,
            "plural": plan.names.plural,
        }
        for plan in blueprint.entity_plans
    ]


def run(context: ToolContext) -> None:
    blueprint = context.blueprint
    has_auth = blueprint.auth is not None
    resources = build_resource_list(blueprint)

    context.render_to_file(
        template_name="pyproject.toml.jinja",
        file_path="pyproject.toml",
        rationale="Declares dependencies and build settings in the modern Python format.",
        project_slug=blueprint.project_slug,
        description=blueprint.spec.description,
        dependencies=build_dependency_list(blueprint),
    )

    context.render_to_file(
        template_name="Dockerfile.jinja",
        file_path="Dockerfile",
        rationale=(
            "Builds a small image in two stages and runs the app as a "
            "non-root user."
        ),
    )

    context.render_to_file(
        template_name="docker-compose.yml.jinja",
        file_path="docker-compose.yml",
        rationale="Runs the API alongside PostgreSQL with a single command.",
        project_slug=blueprint.project_slug,
        has_auth=has_auth,
    )

    context.render_to_file(
        template_name="env.example.jinja",
        file_path=".env.example",
        rationale="Documents the environment variables the project expects.",
        project_slug=blueprint.project_slug,
        has_auth=has_auth,
    )

    context.render_to_file(
        template_name="README.md.jinja",
        file_path="README.md",
        rationale="Explains how to run the project and lists its endpoints.",
        project_title=blueprint.project_title,
        description=blueprint.spec.description,
        has_auth=has_auth,
        resources=resources,
    )

    context.render_to_file(
        template_name="tests/test_health.py.jinja",
        file_path="tests/test_health.py",
        rationale=(
            "Smoke tests that prove the app imports, serves its health check, "
            "and exposes each resource."
        ),
        project_title=blueprint.project_title,
        resources=resources,
    )
