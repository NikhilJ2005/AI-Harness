"""The build plan derived from a ``ProjectSpec``."""

from dataclasses import dataclass, field as dataclass_field

from vibestack.naming import (
    to_class_name,
    to_module_name,
    to_route_prefix,
    to_snake_case,
    to_table_name,
)
from vibestack.spec import Entity, EntityField, FieldType, ProjectSpec, RelationshipType

# Field names that the database fills in automatically, so clients never send them.
AUTO_TIMESTAMP_FIELDS = ("created_at", "updated_at")

# Field names we accept as the login identifier, in order of preference.
LOGIN_FIELD_CANDIDATES = ("email", "username")

# The column that stores the hashed password.
PASSWORD_FIELD_NAME = "password_hash"

# Entity names that indicate the account table when authentication is enabled.
ACCOUNT_ENTITY_NAMES = ("user", "account", "member")


@dataclass(frozen=True)
class EntityNames:
    """Every spelling of one entity's name that generated code needs."""

    entity_name: str  # as written in the spec, e.g. "BlogPost"
    class_name: str  # "BlogPost"
    module_name: str  # "blog_post"
    table_name: str  # "blog_posts"
    route_prefix: str  # "blog-posts"
    singular: str  # "blog_post"  (used in function names)
    plural: str  # "blog_posts" (used in function names)


@dataclass(frozen=True)
class ForeignKeyColumn:
    """A foreign key column that a relationship requires."""

    column_name: str  # "author_id"
    target_table: str  # "users"


@dataclass(frozen=True)
class RelationshipAttribute:
    """One side of a relationship, as an ORM attribute."""

    attribute_name: str  # "posts" or "author"
    target_class: str  # "Post" or "User"
    back_populates: str  # the attribute name on the other side
    is_collection: bool  # True for the "many" side


@dataclass
class EntityPlan:
    """Everything the tools need in order to generate one entity."""

    entity: Entity
    names: EntityNames
    foreign_keys: list[ForeignKeyColumn] = dataclass_field(default_factory=list)
    relationships: list[RelationshipAttribute] = dataclass_field(default_factory=list)


@dataclass(frozen=True)
class AuthPlan:
    """How authentication maps onto the account entity."""

    entity_plan: EntityPlan
    login_field: str  # "email"
    password_field: str  # "password_hash"


@dataclass
class Blueprint:
    """The complete plan for one generated project."""

    spec: ProjectSpec
    project_slug: str
    project_title: str
    entity_plans: list[EntityPlan]
    auth: AuthPlan | None = None
    notes: list[str] = dataclass_field(default_factory=list)

    def plan_for(self, entity_name: str) -> EntityPlan | None:
        wanted = to_snake_case(entity_name)
        for plan in self.entity_plans:
            if to_snake_case(plan.names.entity_name) == wanted:
                return plan
        return None

    def router_modules(self) -> list[str]:
        modules = [plan.names.module_name for plan in self.entity_plans]
        if self.auth is not None:
            # Authentication routes are registered first so they appear at the
            # top of the generated API documentation.
            modules.insert(0, "auth")
        return modules


def build_entity_names(entity_name: str) -> EntityNames:
    return EntityNames(
        entity_name=entity_name,
        class_name=to_class_name(entity_name),
        module_name=to_module_name(entity_name),
        table_name=to_table_name(entity_name),
        route_prefix=to_route_prefix(entity_name),
        singular=to_snake_case(entity_name),
        plural=to_table_name(entity_name),
    )


def _has_field(entity: Entity, field_name: str) -> bool:
    for existing_field in entity.fields:
        if existing_field.name == field_name:
            return True
    return False


def _ensure_primary_key(entity: Entity, notes: list[str]) -> None:
    for existing_field in entity.fields:
        if existing_field.primary_key:
            return

    entity.fields.insert(
        0,
        EntityField(
            name="id", type=FieldType.INTEGER, primary_key=True, nullable=False
        ),
    )
    notes.append(f"Added an 'id' primary key to {entity.name}.")


def _add_relationship_pair(
    owner_plan: EntityPlan,
    other_plan: EntityPlan,
    owner_attribute: str,
    other_attribute: str,
    owner_holds_foreign_key: bool,
) -> None:
    """The side holding the foreign key is the scalar side of the pair."""
    owner_plan.relationships.append(
        RelationshipAttribute(
            attribute_name=owner_attribute,
            target_class=other_plan.names.class_name,
            back_populates=other_attribute,
            is_collection=not owner_holds_foreign_key,
        )
    )
    other_plan.relationships.append(
        RelationshipAttribute(
            attribute_name=other_attribute,
            target_class=owner_plan.names.class_name,
            back_populates=owner_attribute,
            is_collection=owner_holds_foreign_key,
        )
    )

    # The scalar side stores the foreign key.
    if owner_holds_foreign_key:
        owner_plan.foreign_keys.append(
            ForeignKeyColumn(
                column_name=f"{owner_attribute}_id",
                target_table=other_plan.names.table_name,
            )
        )
    else:
        other_plan.foreign_keys.append(
            ForeignKeyColumn(
                column_name=f"{other_attribute}_id",
                target_table=owner_plan.names.table_name,
            )
        )


def _attribute_is_free(plan: EntityPlan, attribute_name: str) -> bool:
    if _has_field(plan.entity, attribute_name):
        return False
    for relationship in plan.relationships:
        if relationship.attribute_name == attribute_name:
            return False
    return True


def _plan_relationships(plans: list[EntityPlan], notes: list[str]) -> None:
    plans_by_name = {to_snake_case(plan.names.entity_name): plan for plan in plans}

    for owner_plan in plans:
        for relationship in owner_plan.entity.relationships:
            target_plan = plans_by_name.get(to_snake_case(relationship.target_entity))
            if target_plan is None:
                notes.append(
                    f"Skipped a relationship on {owner_plan.names.entity_name}: "
                    f"no entity named '{relationship.target_entity}'."
                )
                continue

            if relationship.type is RelationshipType.MANY_TO_MANY:
                notes.append(
                    "Skipped a many-to-many relationship between "
                    f"{owner_plan.names.entity_name} and {target_plan.names.entity_name}: "
                    "association tables are not supported yet."
                )
                continue

            if relationship.type is RelationshipType.ONE_TO_MANY:
                # The owner has many of the target; the target holds the key.
                owner_attribute = target_plan.names.plural
                other_attribute = relationship.back_populates or owner_plan.names.singular
                owner_holds_foreign_key = False
            else:
                # Many of the owner belong to one target; the owner holds the key.
                owner_attribute = relationship.back_populates or target_plan.names.singular
                other_attribute = owner_plan.names.plural
                owner_holds_foreign_key = True

            if not _attribute_is_free(owner_plan, owner_attribute):
                continue
            if not _attribute_is_free(target_plan, other_attribute):
                continue

            _add_relationship_pair(
                owner_plan=owner_plan,
                other_plan=target_plan,
                owner_attribute=owner_attribute,
                other_attribute=other_attribute,
                owner_holds_foreign_key=owner_holds_foreign_key,
            )


def _find_account_plan(plans: list[EntityPlan]) -> tuple[EntityPlan | None, str]:
    """Returns (plan, reason) where reason is 'name', 'login-field', or ''."""
    for candidate_name in ACCOUNT_ENTITY_NAMES:
        for plan in plans:
            if candidate_name in to_snake_case(plan.names.entity_name):
                return plan, "name"

    for plan in plans:
        for candidate_field in LOGIN_FIELD_CANDIDATES:
            if _has_field(plan.entity, candidate_field):
                return plan, "login-field"

    return None, ""


def _plan_authentication(
    spec: ProjectSpec, plans: list[EntityPlan], notes: list[str]
) -> AuthPlan | None:
    """None when auth is off or no account entity exists. May add fields, each noted."""
    if not spec.auth.enabled:
        return None

    account_plan, matched_by = _find_account_plan(plans)
    if account_plan is not None and matched_by == "login-field":
        notes.append(
            f"Treated {account_plan.entity.name} as the account entity for "
            "authentication, because it carries a login field."
        )

    if account_plan is None:
        notes.append(
            "Authentication was requested but no user entity was found, "
            "so auth routes were not generated."
        )
        return None

    entity = account_plan.entity

    # Pick the field used to log in, adding an email field if neither exists.
    login_field = ""
    for candidate in LOGIN_FIELD_CANDIDATES:
        if _has_field(entity, candidate):
            login_field = candidate
            break

    if not login_field:
        login_field = "email"
        entity.fields.append(
            EntityField(
                name=login_field,
                type=FieldType.STRING,
                unique=True,
                nullable=False,
            )
        )
        notes.append(f"Added an '{login_field}' field to {entity.name} for logging in.")

    # A plain "password" field would store the password in clear text, so the
    # generator replaces it with a hashed column.
    if _has_field(entity, "password") and not _has_field(entity, PASSWORD_FIELD_NAME):
        entity.fields = [
            existing for existing in entity.fields if existing.name != "password"
        ]
        notes.append(
            f"Replaced the plain 'password' field on {entity.name} with "
            f"'{PASSWORD_FIELD_NAME}' so passwords are never stored in clear text."
        )

    if not _has_field(entity, PASSWORD_FIELD_NAME):
        entity.fields.append(
            EntityField(
                name=PASSWORD_FIELD_NAME, type=FieldType.STRING, nullable=False
            )
        )
        notes.append(f"Added '{PASSWORD_FIELD_NAME}' to {entity.name} to store passwords.")

    return AuthPlan(
        entity_plan=account_plan,
        login_field=login_field,
        password_field=PASSWORD_FIELD_NAME,
    )


def build_blueprint(spec: ProjectSpec) -> Blueprint:
    """Works on a copy, so planning never mutates the caller's spec."""
    planned_spec = spec.model_copy(deep=True)
    notes: list[str] = []

    entity_plans: list[EntityPlan] = []
    for entity in planned_spec.entities:
        _ensure_primary_key(entity, notes)
        entity_plans.append(
            EntityPlan(entity=entity, names=build_entity_names(entity.name))
        )

    _plan_relationships(entity_plans, notes)
    auth_plan = _plan_authentication(planned_spec, entity_plans, notes)

    project_slug = to_snake_case(planned_spec.project_name) or "generated_api"
    project_title = project_slug.replace("_", " ").title()

    return Blueprint(
        spec=planned_spec,
        project_slug=project_slug,
        project_title=project_title,
        entity_plans=entity_plans,
        auth=auth_plan,
        notes=notes,
    )
