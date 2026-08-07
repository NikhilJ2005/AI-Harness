"""Name conversions used when turning a spec into Python code.

Entity names in a ``ProjectSpec`` are written however the parser produced them
("User", "blog post", "Comment"). Generated code needs consistent class names,
module names, table names, and URL paths. Every conversion lives here so the
whole generator agrees on how a given entity is spelled.
"""

import re

# Words whose plural is not formed by the regular rules below.
IRREGULAR_PLURALS = {
    "person": "people",
    "child": "children",
    "man": "men",
    "woman": "women",
    "mouse": "mice",
    "goose": "geese",
}

# Endings that take "es" instead of a bare "s".
SIBILANT_ENDINGS = ("s", "x", "z", "ch", "sh")


def to_snake_case(name: str) -> str:
    """Convert a name to snake_case.

    Handles spaces, hyphens, and CamelCase, so "BlogPost", "blog post", and
    "blog-post" all become "blog_post".
    """
    # Split a run of capitals from a following word, so "HTTPResponse" becomes
    # "HTTP Response" rather than one unreadable word.
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    # Separate a lowercase letter or digit followed by an uppercase letter.
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", spaced)
    # Treat any run of non-alphanumeric characters as a word separator.
    words = re.split(r"[^A-Za-z0-9]+", spaced)
    meaningful_words = [word.lower() for word in words if word]
    return "_".join(meaningful_words)


def to_class_name(name: str) -> str:
    """Convert a name to a Python class name, for example "blog post" -> "BlogPost"."""
    words = to_snake_case(name).split("_")
    capitalised_words = [word.capitalize() for word in words if word]
    return "".join(capitalised_words)


def pluralise(word: str) -> str:
    """Return the plural form of a single lowercase word.

    This covers the regular English rules plus a short list of irregular words.
    It does not need to be perfect: it only shapes table names and URL paths.
    """
    if word in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[word]

    # "category" -> "categories", but "day" -> "days".
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        return word[:-1] + "ies"

    for ending in SIBILANT_ENDINGS:
        if word.endswith(ending):
            return word + "es"

    return word + "s"


def to_table_name(entity_name: str) -> str:
    """Return the database table name for an entity, for example "User" -> "users"."""
    snake_name = to_snake_case(entity_name)
    words = snake_name.split("_")
    # Only the final word is pluralised: "blog_post" -> "blog_posts".
    words[-1] = pluralise(words[-1])
    return "_".join(words)


def to_module_name(entity_name: str) -> str:
    """Return the Python module name for an entity, for example "BlogPost" -> "blog_post"."""
    return to_snake_case(entity_name)


def to_route_prefix(entity_name: str) -> str:
    """Return the URL path segment for an entity, for example "User" -> "users"."""
    return to_table_name(entity_name).replace("_", "-")
