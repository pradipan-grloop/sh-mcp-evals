"""The conversation loop, against the stub server and a scripted Claude (no API key needed)."""
from types import SimpleNamespace as NS

from evalkit import connect
from evalkit.agent import FALLBACK_BETA, Transcript, _echoable, api_tools, converse, render, system_prompt
from tests.fakes import FakeClaude, settings


async def _session(url):
    mcp = await connect("qa", url=url)
    return mcp, api_tools(await mcp.list_tools())


def test_system_prompt_carries_server_instructions_and_skills():
    p = system_prompt("Be warm.", ["# SH skill\nBuild in order."])
    assert "<server_instructions>\nBe warm.\n</server_instructions>" in p
    assert p.endswith("# SH skill\nBuild in order.")
    assert "server_instructions" not in system_prompt(None)


def test_api_tools_drop_the_schema_dialect_key():
    tools = api_tools([{"name": "a", "inputSchema": {"$schema": "x", "type": "object", "properties": {}}},
                       {"name": "b"}])
    assert tools[0] == {"name": "a", "description": "", "input_schema": {"type": "object", "properties": {}}}
    assert tools[1]["input_schema"] == {"type": "object", "properties": {}}


async def test_tool_call_then_answer(stub_url):
    mcp, tools = await _session(stub_url)
    claude = FakeClaude([[("text", "Checking."), ("tool", "get_health", {})], [("text", "All healthy.")]])
    t = await converse(mcp, claude, settings(), "SYSTEM", tools, ["Is everything healthy?"])
    assert t.error is None
    assert [e["kind"] for e in t.events] == ["admin", "claude", "tool", "claude"]
    assert t.calls == [("get_health", {})] and t.answer == "All healthy."
    assert t.usage["input"] == 200 and t.model_calls == 2
    first = claude.requests[0]
    assert first["system"] == "SYSTEM" and first["tools"] == tools
    assert first["betas"] == [FALLBACK_BETA] and first["fallbacks"] == "default"
    assert first["output_config"] == {"effort": "medium"} and first["cache_control"] == {"type": "ephemeral"}
    tool_result = claude.requests[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and '"status": "ok"' in tool_result["content"]


async def test_follow_up_messages_are_sent_after_each_answer(stub_url):
    mcp, tools = await _session(stub_url)
    claude = FakeClaude([[("text", "Shall I?")], [("text", "Done.")]])
    t = await converse(mcp, claude, settings(), "S", tools, ["Do it.", "Yes, go ahead."])
    assert [e["text"] for e in t.events] == ["Do it.", "Shall I?", "Yes, go ahead.", "Done."]
    roles = [m["role"] for m in claude.requests[1]["messages"]]
    assert roles == ["user", "assistant", "user"]


async def test_write_is_blocked_before_it_reaches_the_server(stub):
    mcp, tools = await _session(stub.url)
    claude = FakeClaude([[("tool", "set_visibility", {"programId": "p-1", "status": "PUBLIC"})],
                         [("text", "I could not publish it.")]])
    t = await converse(mcp, claude, settings(), "S", tools, ["Publish it."])
    assert len(t.blocked) == 1 and t.blocked[0]["result"].startswith("Blocked by evalkit")
    sent = [m for m in stub.seen if m.get("method") == "tools/call"]
    assert sent == []
    assert claude.requests[1]["messages"][-1]["content"][0]["is_error"] is True


async def test_refusal_code_is_recorded(stub_url):
    mcp, tools = await _session(stub_url)
    claude = FakeClaude([[("tool", "search_learners", {"pii_fields": ["email"]})], [("text", "Why?")]])
    t = await converse(mcp, claude, settings(), "S", tools, ["Emails please."])
    assert t.codes == ["REASON_REQUIRED"]
    assert t.response_chars > 0


async def test_step_limit_stops_the_run(stub_url):
    mcp, tools = await _session(stub_url)
    claude = FakeClaude([[("tool", "get_health", {})]])  # never answers
    t = await converse(mcp, claude, settings(max_steps=3), "S", tools, ["Hi", "Still there?"])
    assert t.error == "no reply to the admin within 3 model calls"
    assert len(claude.requests) == 3  # the second message is never sent


async def test_model_refusal_stops_the_run(stub_url):
    mcp, tools = await _session(stub_url)
    t = await converse(mcp, FakeClaude([[]], stop_reason="refusal"), settings(), "S", tools, ["Hi"])
    assert t.error.startswith("Claude declined")


async def test_fallback_model_is_noted(stub_url):
    mcp, tools = await _session(stub_url)
    t = await converse(mcp, FakeClaude([[("text", "Hi")]], model="claude-opus-4-8", fallback=True),
                       settings(), "S", tools, ["Hi"])
    assert t.fallbacks == {"claude-opus-4-8"}


def test_echo_drops_internal_blocks_before_a_fallback():
    blocks = [NS(type="thinking"), NS(type="text", text="a"), NS(type="tool_use"), NS(type="fallback"),
              NS(type="thinking"), NS(type="tool_use")]
    kept = [b.type for b in _echoable(blocks)]
    assert kept == ["text", "fallback", "thinking", "tool_use"]
    plain = [NS(type="thinking"), NS(type="text", text="a")]
    assert _echoable(plain) is plain


def test_render_cuts_long_results_and_says_so():
    t = Transcript(events=[
        {"kind": "admin", "text": "Hi"},
        {"kind": "tool", "tool": "get_health", "args": {}, "is_error": True, "code": "NOT_FOUND",
         "blocked": False, "chars": 50, "result": "x" * 50}])
    text = render(t, limit=10)
    assert "ADMIN: Hi" in text and "REFUSED (NOT_FOUND): xxxxxxxxxx [... 40 more characters cut]" in text
