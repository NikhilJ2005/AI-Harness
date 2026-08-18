"""The structured description of a backend project."""

from enum import Enum

from pydantic import BaseModel, Field


class FieldType(str, Enum):
    """The column types VibeStack knows how to generate."""

    INTEGER = "int"
    STRING = "str"
    BOOLEAN = "bool"
    DATETIME = "datetime"
    TEXT = "text"
    FLOAT = "float"


class EntityField(BaseModel):
    """One column on a database table."""

    name: str
    type: FieldType
    primary_key: bool = False
    unique: bool = False
    nullable: bool = True


class RelationshipType(str, Enum):
    """The kinds of relationship between two entities."""

    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"


class Relationship(BaseModel):
    """A link from one entity to another."""

    target_entity: str
    type: RelationshipType
    back_populates: str


class AuthConfig(BaseModel):
    """How authentication should be scaffolded for the project."""

    enabled: bool = True
    strategy: str = "jwt"  # "jwt" today; "oauth2" is planned for later.
    # A factory is used so every spec gets its own list rather than sharing one.
    endpoints: list[str] = Field(
        default_factory=lambda: ["register", "login", "me"]
    )


class Entity(BaseModel):
    """A single database table and its matching API resource."""

    name: str
    fields: list[EntityField]
    relationships: list[Relationship] = Field(default_factory=list)


class ProjectSpec(BaseModel):
    """A complete, structured description of the backend to generate."""

    project_name: str
    description: str
    entities: list[Entity]
    auth: AuthConfig = Field(default_factory=AuthConfig)
    features: list[str] = Field(default_factory=list)  # e.g. "pagination"
