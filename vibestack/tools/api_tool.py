"""Generate the Pydantic schemas and CRUD routers."""

from vibestack.blueprint import AUTO_TIMESTAMP_FIELDS, Blueprint, EntityPlan
from vibestack.spec import EntityField, FieldType
from vibestack.tools.context import ToolContext
from vibestack.tools.field_types import PYTHON_TYPE_NAMES


def build_field_line(name: str, python_type: str, optional: bool) -> str:
    if optional:
        return f"{name}: {python_type} | None = None"
    return f"{name}: {python_type}"


def is_client_supplied(field: EntityField) -> bool:
    """False for primary keys and auto timestamps: returned to clients, never accepted."""
    if field.primary_key:
        return False
    if field.type is FieldType.DATETIME and field.name in AUTO_TIMESTAMP_FIELDS:
        return False
    return True


def hidden_field_names(blueprint: Blueprint, plan: EntityPlan) -> set[str]:
    """The password hash is stored but must never appear in a request or response."""
    if blueprint.auth is not None and blueprint.auth.entity_plan is plan:
        return {blueprint.auth.password_field}
    return set()


def build_schema_context(blueprint: Blueprint, plan: EntityPlan) -> dict[str, object]:
    hidden_fields = hidden_field_names(blueprint, plan)

    base_field_lines: list[str] = []
    update_field_lines: list[str] = []
    read_extra_field_lines: list[str] = []
    uses_datetime = False

    for field in plan.entity.fields:
        if field.name in hidden_fields:
            continue

        python_type = PYTHON_TYPE_NAMES[field.type]
        if field.type is FieldType.DATETIME:
            uses_datetime = True

        if is_client_supplied(field):
            base_field_lines.append(
                build_field_line(field.name, python_type, optional=field.nullable)
            )
            update_field_lines.append(
                build_field_line(field.name, python_type, optional=True)
            )
        else:
            read_extra_field_lines.append(
                build_field_line(field.name, python_type, optional=False)
            )

    # Foreign keys are optional so a record can be created before it is linked.
    for foreign_key in plan.foreign_keys:
        base_field_lines.append(
            build_field_line(foreign_key.column_name, "int", optional=True)
        )
        update_field_lines.append(
            build_field_line(foreign_key.column_name, "int", optional=True)
        )

    # The account entity accepts a plain password, which is hashed before storage.
    create_extra_field_lines: list[str] = []
    if blueprint.auth is not None and blueprint.auth.entity_plan is plan:
        create_extra_field_lines.append(build_field_line("password", "str", optional=False))

    return {
        "entity_name": plan.names.entity_name,
        "class_name": plan.names.class_name,
        "base_field_lines": base_field_lines,
        "create_extra_field_lines": create_extra_field_lines,
        "update_field_lines": update_field_lines,
        "read_extra_field_lines": read_extra_field_lines,
        "needs_datetime": uses_datetime,
    }


def run(context: ToolContext) -> None:
    blueprint = context.blueprint

    for plan in blueprint.entity_plans:
        context.render_to_file(
            template_name="app/schemas/schema.py.jinja",
            file_path=f"app/schemas/{plan.names.module_name}.py",
            rationale=(
                f"Validates {plan.names.entity_name} requests and shapes responses, "
                "keeping internal columns out of the API."
            ),
            **build_schema_context(blueprint, plan),
        )

        context.render_to_file(
            template_name="app/routers/crud.py.jinja",
            file_path=f"app/routers/{plan.names.module_name}.py",
            rationale=(
                f"Exposes create, read, update, and delete endpoints for "
                f"{plan.names.entity_name}."
            ),
            entity_name=plan.names.entity_name,
            class_name=plan.names.class_name,
            module_name=plan.names.module_name,
            route_prefix=plan.names.route_prefix,
            singular=plan.names.singular,
            plural=plan.names.plural,
        )

    context.render_to_file(
        template_name="app/schemas/__init__.py.jinja",
        file_path="app/schemas/__init__.py",
        rationale="Marks the schemas directory as a package.",
    )
    context.render_to_file(
        template_name="app/routers/__init__.py.jinja",
        file_path="app/routers/__init__.py",
        rationale="Marks the routers directory as a package.",
    )
