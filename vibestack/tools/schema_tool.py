"""Generate the SQLAlchemy models — the first tool in the pipeline.

Models come first because every later tool depends on the tables: the Pydantic
schemas mirror their columns, and the routers query them by class name.
"""

from vibestack.blueprint import (
    AUTO_TIMESTAMP_FIELDS,
    EntityPlan,
    ForeignKeyColumn,
    RelationshipAttribute,
)
from vibestack.spec import EntityField, FieldType
from vibestack.tools.context import ToolContext
from vibestack.tools.field_types import SQLALCHEMY_COLUMN_TYPES, SQLALCHEMY_IMPORT_NAMES


def is_auto_timestamp(field: EntityField) -> bool:
    """Return True for datetime columns the database should fill in itself."""
    return field.type is FieldType.DATETIME and field.name in AUTO_TIMESTAMP_FIELDS


def build_column_line(field: EntityField) -> str:
    """Return the source line that declares one column."""
    arguments = [SQLALCHEMY_COLUMN_TYPES[field.type]]

    if field.primary_key:
        arguments.append("primary_key=True")
        arguments.append("index=True")
    else:
        if field.unique:
            arguments.append("unique=True")
            arguments.append("index=True")
        if not field.nullable:
            arguments.append("nullable=False")
        if is_auto_timestamp(field):
            arguments.append("default=utc_now")

    joined_arguments = ", ".join(arguments)
    return f"{field.name} = Column({joined_arguments})"


def build_foreign_key_line(foreign_key: ForeignKeyColumn) -> str:
    """Return the source line that declares a foreign key column."""
    target = f'"{foreign_key.target_table}.id"'
    return f"{foreign_key.column_name} = Column(Integer, ForeignKey({target}))"


def build_relationship_line(relationship: RelationshipAttribute) -> str:
    """Return the source line that declares an ORM relationship attribute."""
    return (
        f'{relationship.attribute_name} = relationship('
        f'"{relationship.target_class}", '
        f'back_populates="{relationship.back_populates}")'
    )


def collect_sqlalchemy_imports(plan: EntityPlan) -> str:
    """Return the comma-separated names to import from sqlalchemy."""
    needed_names = {"Column"}
    for field in plan.entity.fields:
        needed_names.add(SQLALCHEMY_IMPORT_NAMES[field.type])

    if plan.foreign_keys:
        needed_names.add("ForeignKey")
        needed_names.add("Integer")

    return ", ".join(sorted(needed_names))


def build_model_context(plan: EntityPlan) -> dict[str, object]:
    """Assemble the template variables for one model file."""
    column_lines = [build_column_line(field) for field in plan.entity.fields]
    for foreign_key in plan.foreign_keys:
        column_lines.append(build_foreign_key_line(foreign_key))

    relationship_lines = [
        build_relationship_line(relationship) for relationship in plan.relationships
    ]

    needs_datetime = any(is_auto_timestamp(field) for field in plan.entity.fields)

    return {
        "entity_name": plan.names.entity_name,
        "class_name": plan.names.class_name,
        "table_name": plan.names.table_name,
        "column_lines": column_lines,
        "relationship_lines": relationship_lines,
        "sqlalchemy_imports": collect_sqlalchemy_imports(plan),
        "needs_datetime": needs_datetime,
    }


def run(context: ToolContext) -> None:
    """Generate a model file for every entity, plus the package __init__."""
    for plan in context.blueprint.entity_plans:
        context.render_to_file(
            template_name="app/models/model.py.jinja",
            file_path=f"app/models/{plan.names.module_name}.py",
            rationale=(
                f"Defines the {plan.names.table_name} table so "
                f"{plan.names.entity_name} records can be stored."
            ),
            **build_model_context(plan),
        )

    models = [
        {
            "module_name": plan.names.module_name,
            "class_name": plan.names.class_name,
        }
        for plan in context.blueprint.entity_plans
    ]
    context.render_to_file(
        template_name="app/models/__init__.py.jinja",
        file_path="app/models/__init__.py",
        rationale="Imports every model so SQLAlchemy can create all tables.",
        models=models,
    )
