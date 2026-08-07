"""Tests for the name conversion helpers."""

import pytest

from vibestack.naming import (
    pluralise,
    to_class_name,
    to_route_prefix,
    to_snake_case,
    to_table_name,
)


@pytest.mark.parametrize(
    "given, expected",
    [
        ("User", "user"),
        ("BlogPost", "blog_post"),
        ("blog post", "blog_post"),
        ("blog-post", "blog_post"),
        ("HTTPResponse", "http_response"),
    ],
)
def test_to_snake_case(given, expected):
    assert to_snake_case(given) == expected


@pytest.mark.parametrize(
    "given, expected",
    [
        ("user", "User"),
        ("blog post", "BlogPost"),
        ("blog_post", "BlogPost"),
    ],
)
def test_to_class_name(given, expected):
    assert to_class_name(given) == expected


@pytest.mark.parametrize(
    "given, expected",
    [
        ("post", "posts"),
        ("category", "categories"),
        ("day", "days"),
        ("address", "addresses"),
        ("box", "boxes"),
        ("person", "people"),
    ],
)
def test_pluralise(given, expected):
    assert pluralise(given) == expected


def test_to_table_name_pluralises_only_the_last_word():
    assert to_table_name("BlogPost") == "blog_posts"
    assert to_table_name("User") == "users"


def test_to_route_prefix_uses_hyphens():
    assert to_route_prefix("BlogPost") == "blog-posts"
