"""Tests for the rule table."""

from __future__ import annotations

import pytest

from devdust import rules as rules_mod
from devdust.rules import REVIEW, RULES, SAFE, Rule


def test_rule_matching_is_exact_by_name():
    assert rules_mod.match("node_modules").kind == "node"
    assert rules_mod.match("__pycache__").kind == "python"
    assert rules_mod.match("src") is None
    assert rules_mod.match("node_modules_backup") is None


def test_glob_patterns_match_generated_names():
    rule = rules_mod.match("my_package.egg-info")
    assert rule is not None
    assert rule.kind == "python"
    assert rule.pattern == "*.egg-info"


def test_patterns_are_unique():
    patterns = [rule.pattern for rule in RULES]
    assert len(patterns) == len(set(patterns))


def test_every_rule_is_well_formed():
    for rule in RULES:
        assert rule.pattern
        assert rule.kind
        assert rule.kind == rule.kind.lower()
        assert rule.description
        assert rule.confidence in rules_mod.CONFIDENCES


def test_kinds_are_sorted_and_derived_from_the_table():
    kinds = rules_mod.kinds()
    assert kinds == tuple(sorted(kinds))
    assert {"node", "python", "rust", "java", "dotnet"} <= set(kinds)


def test_select_excludes_review_by_default():
    selected = rules_mod.select()
    assert selected
    assert all(rule.confidence == SAFE for rule in selected)
    assert not any(rule.pattern in {"build", "target", "vendor"} for rule in selected)


def test_select_can_include_review():
    patterns = {rule.pattern for rule in rules_mod.select(include_review=True)}
    assert {"build", "target", "bin"} <= patterns


def test_select_filters_by_kind():
    selected = rules_mod.select(kinds_in=["python"])
    assert selected
    assert {rule.kind for rule in selected} == {"python"}


def test_select_can_be_empty():
    assert (
        rules_mod.select(kinds_in=["node"], include_review=False, rules=[Rule("x", "python", "y")])
        == ()
    )


@pytest.mark.parametrize(
    "name, expected_kind",
    [
        ("node_modules", "node"),
        (".tox", "python"),
        (".terraform", "terraform"),
        ("Pods", "ios"),
        ("target", "rust"),
        ("obj", "dotnet"),
    ],
)
def test_known_directories(name, expected_kind):
    rule = rules_mod.match(name)
    assert rule is not None and rule.kind == expected_kind


def test_review_rules_are_marked():
    review = [rule for rule in RULES if rule.confidence == REVIEW]
    assert review
    assert all(isinstance(rule.confidence, str) for rule in review)
