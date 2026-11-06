import json

import httpx
import pytest

from evalkit import connect
from evalkit.client import AuthError, CassetteMiss, Result, Session
from tests.stub_server import INSTRUCTIONS, Stub


async def test_initialize_keeps_server_info_and_instructions(stub_url):
    mcp = await connect("qa", url=stub_url)
    assert mcp.server_info == {"name": "stitched-health", "version": "9.9.9-stub"}
    assert mcp.instructions == INSTRUCTIONS
    await mcp.close()


async def test_live_call_parses_json_text(stub_url):
    mcp = await connect("qa", url=stub_url)
    r = await mcp.call("list_programs")
    assert r.ok and r.data["programs"][0]["name"] == "Stub AFib"
    assert mcp.calls == [("list_programs", {})]


async def test_refusal_keeps_message_then_code_and_fix(stub_url):
    mcp = await connect("qa", url=stub_url)
    r = await mcp.call("set_visibility", {"programId": "p-1", "status": "PUBLIC"})
    assert r.is_error and r.code == "NOT_READY"
    assert r.text.splitlines() == ["Stub AFib is not ready to publish.",
                                   "Code: NOT_READY. Fix: Fix the failing checklist rows."]
    assert r.data["failing"] == [{"item": "Videos"}]


def test_code_is_read_from_text_without_structured_content():
    assert Result(text="Changed since.\nCode: STALE_VERSION. Fix: Re-read.", is_error=True).code == "STALE_VERSION"
    assert Result(text="Code: X. Fix: y", is_error=False).code is None


async def test_reads_and_writes_come_from_annotations(stub_url):
    mcp = await connect("qa", url=stub_url)
    await mcp.list_tools()
    assert not mcp.is_write("get_health")
    assert mcp.is_write("set_visibility")
    assert not mcp.is_write("no_such_tool")  # not listed: the server refuses it


def test_listed_tool_without_read_only_hint_counts_as_write():
    s = Session(server="qa", mode="live", cassette_path=None)
    s._tools = [{"name": "mystery"}, {"name": "reader", "annotations": {"readOnlyHint": True}}]
    assert s.is_write("mystery") and not s.is_write("reader")


async def test_token_is_sent_and_a_refused_one_is_explained():
    stub = Stub(token="sh_agent_good")
    try:
        ok = await connect("qa", url=stub.url, token="sh_agent_good")
        assert await ok.list_tools()
        await ok.close()
        with pytest.raises(AuthError, match="Agent token revoked"):
            await connect("qa", url=stub.url, token="sh_agent_bad")
    finally:
        stub.stop()


async def test_rate_limit_is_waited_out(stub):
    stub.throttle_next = 2
    mcp = await connect("qa", url=stub.url)
    assert mcp.instructions == INSTRUCTIONS


async def test_rate_limit_gives_up_eventually(stub):
    stub.throttle_next = 99
    with pytest.raises(httpx.HTTPStatusError):
        await connect("qa", url=stub.url)


async def test_record_then_replay_without_server(stub_url, tmp_path):
    rec = await connect("qa", mode="record", case="T-1", url=stub_url, fixtures_dir=tmp_path)
    await rec.list_tools()
    await rec.call("get_health")
    cassette = json.loads((tmp_path / "qa" / "T-1.json").read_text(encoding="utf-8"))
    assert len(cassette["calls"]) == 1 and cassette["server"]["instructions"] == INSTRUCTIONS

    rep = await connect("qa", mode="replay", case="T-1", fixtures_dir=tmp_path)
    assert rep.instructions == INSTRUCTIONS
    assert [t["name"] for t in await rep.list_tools()][0] == "get_health"
    assert (await rep.call("get_health")).data["status"] == "ok"


async def test_replay_miss_raises_or_soft_fails(stub_url, tmp_path):
    rec = await connect("qa", mode="record", case="T-2", url=stub_url, fixtures_dir=tmp_path)
    await rec.call("get_health")
    rep = await connect("qa", mode="replay", case="T-2", fixtures_dir=tmp_path)
    with pytest.raises(CassetteMiss, match="list_programs"):
        await rep.call("list_programs")
    r = await rep.call("list_programs", strict=False)
    assert r.is_error and r.off_recording


async def test_live_needs_a_url():
    with pytest.raises(ValueError, match="url"):
        await connect("qa", mode="live")
