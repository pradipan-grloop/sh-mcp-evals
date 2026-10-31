"""Assertion helpers for case notebooks (the role assertions_utils played in the Colabs)."""
import re


def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().casefold()


def compare_strings(a, b):
    return norm(a) == norm(b)


def mentions(text, value):
    """True if value appears in text as a whole token (so '2' does not match '12')."""
    return re.search(rf"(?<![\w.]){re.escape(norm(value))}(?![\w.])", norm(text)) is not None


def called(calls, tool, min=1):
    return sum(1 for name, _ in calls if name == tool) >= min


def scalar(result):
    """The single value of an instant-query vector result, as a float."""
    vec = result.data["result"]
    assert len(vec) == 1, f"expected one sample, got {len(vec)}"
    return float(vec[0]["value"][1])
