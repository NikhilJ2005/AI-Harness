"""Tests for the ProjectSpec data models."""

from vibestack.spec import (
    AuthConfig,
    Entity,
    EntityField,
    FieldType,
    ProjectSpec,
)


def test_project_spec_round_trips_through_json():
    """A spec should survive a dump-then-load cycle unchanged."""
    spec = ProjectSpec(
        project_name="blog_api",
        description="A simple blog",
        entities=[
            Entity(
                name="User",
                fields=[
                    EntityField(name="id", type=FieldType.INTEGER, primary_key=True),
                    EntityField(name="email", type=FieldType.STRING, unique=True),
                ],
            )
        ],
    )

    dumped = spec.model_dump_json()
    reloaded = ProjectSpec.model_validate_json(dumped)

    assert reloaded == spec


def test_auth_defaults_are_independent_between_instances():
    """Each spec must get its own auth config, not a shared one."""
    first = ProjectSpec(project_name="a", description="", entities=[])
    second = ProjectSpec(project_name="b", description="", entities=[])

    first.auth.endpoints.append("logout")

    # Mutating the first spec's endpoints must not affect the second.
    assert "logout" not in second.auth.endpoints


def test_auth_config_defaults():
    """By default authentication is JWT with the standard endpoints."""
    auth = AuthConfig()
    assert auth.enabled is True
    assert auth.strategy == "jwt"
    assert auth.endpoints == ["register", "login", "me"]
