"""Tests for the planning step that turns a spec into a build plan."""

from vibestack.blueprint import build_blueprint
from vibestack.spec import (
    AuthConfig,
    Entity,
    EntityField,
    FieldType,
    ProjectSpec,
    Relationship,
    RelationshipType,
)


def _user_entity(fields: list[EntityField] | None = None) -> Entity:
    """Build a User entity, with sensible defaults for the tests."""
    if fields is None:
        fields = [
            EntityField(name="id", type=FieldType.INTEGER, primary_key=True),
            EntityField(name="email", type=FieldType.STRING, unique=True),
        ]
    return Entity(name="User", fields=fields)


def test_missing_primary_key_is_added():
    """An entity without a primary key should be given an id column."""
    spec = ProjectSpec(
        project_name="demo",
        description="",
        entities=[Entity(name="Note", fields=[EntityField(name="body", type=FieldType.TEXT)])],
        auth=AuthConfig(enabled=False),
    )

    blueprint = build_blueprint(spec)
    note_plan = blueprint.plan_for("Note")

    assert note_plan is not None
    assert note_plan.entity.fields[0].name == "id"
    assert note_plan.entity.fields[0].primary_key is True


def test_planning_does_not_modify_the_caller_spec():
    """Planning works on a copy, so the caller's spec is left untouched."""
    original = ProjectSpec(
        project_name="demo",
        description="",
        entities=[Entity(name="Note", fields=[EntityField(name="body", type=FieldType.TEXT)])],
        auth=AuthConfig(enabled=False),
    )

    build_blueprint(original)

    assert [field.name for field in original.entities[0].fields] == ["body"]


def test_one_to_many_creates_both_sides_and_a_foreign_key():
    """A one-to-many relationship should produce a foreign key on the child."""
    spec = ProjectSpec(
        project_name="blog",
        description="",
        entities=[
            _user_entity(),
            Entity(
                name="Post",
                fields=[
                    EntityField(name="id", type=FieldType.INTEGER, primary_key=True),
                    EntityField(name="title", type=FieldType.STRING),
                ],
            ),
        ],
        auth=AuthConfig(enabled=False),
    )
    spec.entities[0].relationships.append(
        Relationship(
            target_entity="Post",
            type=RelationshipType.ONE_TO_MANY,
            back_populates="author",
        )
    )

    blueprint = build_blueprint(spec)
    user_plan = blueprint.plan_for("User")
    post_plan = blueprint.plan_for("Post")

    # The parent holds a collection.
    assert user_plan.relationships[0].attribute_name == "posts"
    assert user_plan.relationships[0].is_collection is True

    # The child holds the scalar side and the foreign key.
    assert post_plan.relationships[0].attribute_name == "author"
    assert post_plan.relationships[0].is_collection is False
    assert post_plan.foreign_keys[0].column_name == "author_id"
    assert post_plan.foreign_keys[0].target_table == "users"


def test_many_to_many_is_skipped_with_a_note():
    """Unsupported relationships are skipped and reported, not silently dropped."""
    spec = ProjectSpec(
        project_name="blog",
        description="",
        entities=[
            _user_entity(),
            Entity(
                name="Group",
                fields=[EntityField(name="id", type=FieldType.INTEGER, primary_key=True)],
            ),
        ],
        auth=AuthConfig(enabled=False),
    )
    spec.entities[0].relationships.append(
        Relationship(
            target_entity="Group",
            type=RelationshipType.MANY_TO_MANY,
            back_populates="users",
        )
    )

    blueprint = build_blueprint(spec)

    assert blueprint.plan_for("User").relationships == []
    assert any("many-to-many" in note for note in blueprint.notes)


def test_relationship_to_unknown_entity_is_reported():
    """A relationship pointing at a missing entity should be noted, not crash."""
    spec = ProjectSpec(
        project_name="blog",
        description="",
        entities=[_user_entity()],
        auth=AuthConfig(enabled=False),
    )
    spec.entities[0].relationships.append(
        Relationship(
            target_entity="Ghost",
            type=RelationshipType.ONE_TO_MANY,
            back_populates="user",
        )
    )

    blueprint = build_blueprint(spec)

    assert any("Ghost" in note for note in blueprint.notes)


def test_auth_plan_adds_a_password_hash_column():
    """Enabling auth should give the account entity somewhere to store passwords."""
    spec = ProjectSpec(
        project_name="blog",
        description="",
        entities=[_user_entity()],
    )

    blueprint = build_blueprint(spec)

    assert blueprint.auth is not None
    assert blueprint.auth.login_field == "email"
    assert blueprint.auth.password_field == "password_hash"

    field_names = [field.name for field in blueprint.auth.entity_plan.entity.fields]
    assert "password_hash" in field_names


def test_plain_password_field_is_replaced_with_a_hash():
    """A clear-text password column must never survive into the generated model."""
    spec = ProjectSpec(
        project_name="blog",
        description="",
        entities=[
            _user_entity(
                fields=[
                    EntityField(name="id", type=FieldType.INTEGER, primary_key=True),
                    EntityField(name="email", type=FieldType.STRING, unique=True),
                    EntityField(name="password", type=FieldType.STRING),
                ]
            )
        ],
    )

    blueprint = build_blueprint(spec)
    field_names = [field.name for field in blueprint.auth.entity_plan.entity.fields]

    assert "password" not in field_names
    assert "password_hash" in field_names
    assert any("clear text" in note for note in blueprint.notes)


def test_auth_without_a_user_entity_is_disabled_with_a_note():
    """Auth cannot be generated when there is no account table."""
    spec = ProjectSpec(
        project_name="blog",
        description="",
        entities=[
            Entity(
                name="Post",
                fields=[EntityField(name="id", type=FieldType.INTEGER, primary_key=True)],
            )
        ],
    )

    blueprint = build_blueprint(spec)

    assert blueprint.auth is None
    assert any("no user entity" in note for note in blueprint.notes)


def test_account_entity_is_found_by_its_login_field():
    """An account called something other than "User" must still get auth.

    Real specifications say Customer, Attendee, or Chef. Matching only on the
    word "user" silently skipped authentication for all of them.
    """
    spec = ProjectSpec(
        project_name="shop",
        description="",
        entities=[
            Entity(
                name="Customer",
                fields=[
                    EntityField(name="id", type=FieldType.INTEGER, primary_key=True),
                    EntityField(name="email", type=FieldType.STRING, unique=True),
                ],
            )
        ],
    )

    blueprint = build_blueprint(spec)

    assert blueprint.auth is not None
    assert blueprint.auth.entity_plan.names.class_name == "Customer"
    assert blueprint.auth.login_field == "email"
    # The choice is explained, because it was inferred rather than stated.
    assert any("account entity" in note for note in blueprint.notes)


def test_a_named_user_entity_wins_over_one_with_a_login_field():
    """An explicit User entity is a stronger signal than a login field."""
    spec = ProjectSpec(
        project_name="shop",
        description="",
        entities=[
            Entity(
                name="Contact",
                fields=[
                    EntityField(name="id", type=FieldType.INTEGER, primary_key=True),
                    EntityField(name="email", type=FieldType.STRING),
                ],
            ),
            _user_entity(),
        ],
    )

    blueprint = build_blueprint(spec)

    assert blueprint.auth.entity_plan.names.class_name == "User"
