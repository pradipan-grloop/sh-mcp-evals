"""Layer 1: spec lint over a tools/list result. Rules adapted from the FC validator's descriptions."""
import re
from dataclasses import dataclass

SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")
JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
              "array": list, "object": dict}
MIN_DESC = 20


@dataclass
class Finding:
    rule: str
    severity: str  # error | warning
    tool: str
    message: str


def lint_tools(tools):
    out = []
    names = [t.get("name", "") for t in tools]
    for t in tools:
        out += _lint_tool(t)
    for n in {n for n in names if names.count(n) > 1}:
        out.append(Finding("name-unique", "error", n, "tool name appears more than once"))
    return out


def _lint_tool(t):
    name = t.get("name", "")
    f = []

    def add(rule, sev, msg):
        f.append(Finding(rule, sev, name, msg))

    if not SNAKE.match(name):
        add("name-snake-case", "warning", f"{name!r} is not snake_case")
    if len((t.get("description") or "").strip()) < MIN_DESC:
        add("tool-description", "error", f"description missing or under {MIN_DESC} characters")
    schema = t.get("inputSchema") or {}
    if schema.get("type") != "object":
        add("schema-object", "error", "inputSchema type must be 'object'")
    props = schema.get("properties") or {}
    for req in schema.get("required") or []:
        if req not in props:
            add("required-unknown", "error", f"required {req!r} is not a property")
    for p, spec in props.items():
        if "type" not in spec and "anyOf" not in spec and "enum" not in spec:
            add("param-type", "error", f"{p}: no type")
        if not (spec.get("description") or "").strip():
            add("param-description", "error", f"{p}: no description")
        if "enum" in spec and not spec["enum"]:
            add("enum-empty", "error", f"{p}: enum is empty")
        lo, hi = spec.get("minimum"), spec.get("maximum")
        if lo is not None and hi is not None and lo > hi:
            add("min-gt-max", "error", f"{p}: minimum {lo} > maximum {hi}")
        py = JSON_TYPES.get(spec.get("type"))
        if "default" in spec and py and not isinstance(spec["default"], py):
            add("default-type", "error", f"{p}: default {spec['default']!r} is not {spec['type']}")
    return f
