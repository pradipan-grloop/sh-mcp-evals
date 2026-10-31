from evalkit.lint import lint_tools
from tests.stub_server import TOOLS


def rules(findings):
    return {(f.rule, f.tool) for f in findings}


def test_clean_tools_have_no_errors():
    assert [f for f in lint_tools(TOOLS) if f.severity == "error"] == []


def test_missing_descriptions_and_types():
    bad = [{"name": "doThing", "description": "",
            "inputSchema": {"type": "object", "properties": {"x": {}}, "required": ["x", "y"]}}]
    got = rules(lint_tools(bad))
    assert ("tool-description", "doThing") in got
    assert ("param-type", "doThing") in got
    assert ("param-description", "doThing") in got
    assert ("required-unknown", "doThing") in got
    assert ("name-snake-case", "doThing") in got


def test_enum_and_range_rules():
    bad = [{"name": "pick", "description": "Pick an option from the allowed list.",
            "inputSchema": {"type": "object", "properties": {
                "a": {"type": "string", "description": "a", "enum": []},
                "n": {"type": "integer", "description": "n", "minimum": 5, "maximum": 1, "default": "x"}}}}]
    got = rules(lint_tools(bad))
    assert {("enum-empty", "pick"), ("min-gt-max", "pick"), ("default-type", "pick")} <= got
