"""The build plan derived from a ``ProjectSpec``.

Before any file is written, the whole project is planned once: names for every
entity, which side of a relationship owns the foreign key, and which entity acts
as the account for authentication. Every tool then reads this same blueprint.

That single shared plan is what keeps the generated files consistent with each
other — the model, the schema, and the router all learn the class name from the
same place instead of each deciding for itself.
"""

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
        """Return the plan for an entity, matching names loosely."""
        wanted = to_snake_case(entity_name)
        for plan in self.entity_plans:
            if to_snake_case(plan.names.entity_name) == wanted:
                return plan
        return None

    def router_modules(self) -> list[str]:
        """Return the router module names to register on the application."""
        modules = [plan.names.module_name for plan in self.entity_plans]
        if self.auth is not None:
            # Authentication routes are registered first so they appear at the
            # top of the generated API documentation.
            modules.insert(0, "auth")
        return modules


def build_entity_names(entity_name: str) -> EntityNames:
    """Work out every spelling of an entity's name."""
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
    """Return True when the entity already declares a field with this name."""
    for existing_field in entity.fields:
        if existing_field.name == field_name:
            return True
    return False


def _ensure_primary_key(entity: Entity, notes: list[str]) -> None:
    """Give the entity an integer primary key if it does not have one."""
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
    """Record both sides of one relationship, plus the foreign key column.

    ``owner_plan`` is the entity that declared the relationship. The side that
    holds the foreign key is the "many" side of a one-to-many pair.
    """
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
    """Return True when the name is not already used by a field or relationship."""
    if _has_field(plan.entity, attribute_name):
        return False
    for relationship in plan.relationships:
        if relationship.attribute_name == attribute_name:
            return False
    return True


def _plan_relationships(plans: list[EntityPlan], notes: list[str]) -> None:
    """Turn the declared relationships into ORM attributes and foreign keys."""
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
    """Return the entity that represents a user account, and how it was found.

    Names are tried first, because "User" or "Account" is a clear signal. But
    plenty of real specifications call it Customer, Attendee, or Chef, so an
    entity that carries a login field is treated as the account too. Matching on
    shape rather than only on vocabulary is what stops authentication being
    silently skipped for a perfectly ordinary specification.

    Returns ``(plan, reason)`` where reason is "name", "login-field", or "" when
    nothing matched.
    """
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
    """Work out how authentication maps onto the account entity.

    Returns None when authentication is disabled or no account entity exists.
    The account entity is given the fields authentication needs if they are
    missing, which is recorded as a note so the change is visible to the user.
    """
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
    """Plan the whole project from its specification.

    The incoming spec is copied first, so planning never modifies the caller's
    object even though it may add fields such as a primary key.
    """
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
