import json

import pytest

from evalkit import connect
from evalkit.client import CassetteMiss


async def test_live_call_parses_json_text(stub_url, tmp_path):
    mcp = await connect("prometheus-main", mode="live", url=stub_url, fixtures_dir=tmp_path)
    r = await mcp.call("execute_query", {"query": "count(up)"})
    assert r.ok and not r.is_error
    assert r.data["result"][0]["value"][1] == "12"
    assert mcp.calls == [("execute_query", {"query": "count(up)"})]


async def test_tool_error_surfaces_as_is_error(stub_url, tmp_path):
    mcp = await connect("prometheus-main", mode="live", url=stub_url, fixtures_dir=tmp_path)
    r = await mcp.call("execute_query", {"query": "nonsense("})
    assert r.is_error and not r.ok
    assert "not supported" in r.text


async def test_record_then_replay_without_server(stub_url, tmp_path):
    rec = await connect("prometheus-main", mode="record", case="T-1", url=stub_url, fixtures_dir=tmp_path)
    await rec.list_tools()
    await rec.call("health_check", {})
    await rec.call("execute_query", {"query": "count(up)"})
    cassette = json.loads((tmp_path / "prometheus-main" / "T-1.json").read_text())
    assert len(cassette["calls"]) == 2

    rep = await connect("prometheus-main", mode="replay", case="T-1", fixtures_dir=tmp_path)
    assert [t["name"] for t in await rep.list_tools()][0] == "health_check"
    r = await rep.call("execute_query", {"query": "count(up)"})
    assert r.data["result"][0]["value"][1] == "12"


async def test_replay_miss_raises_with_the_call_named(stub_url, tmp_path):
    rec = await connect("prometheus-main", mode="record", case="T-2", url=stub_url, fixtures_dir=tmp_path)
    await rec.call("health_check", {})
    rep = await connect("prometheus-main", mode="replay", case="T-2", fixtures_dir=tmp_path)
    with pytest.raises(CassetteMiss, match="count\\(up\\)"):
        await rep.call("execute_query", {"query": "count(up)"})


async def test_replay_miss_soft_returns_error_result(stub_url, tmp_path):
    rec = await connect("prometheus-main", mode="record", case="T-3", url=stub_url, fixtures_dir=tmp_path)
    await rec.call("health_check", {})
    rep = await connect("prometheus-main", mode="replay", case="T-3", fixtures_dir=tmp_path)
    r = await rep.call("execute_query", {"query": "up"}, strict=False)
    assert r.is_error and r.off_recording


async def test_unknown_server_name_is_clear(tmp_path):
    with pytest.raises(KeyError, match="no-such-server"):
        await connect("no-such-server", mode="live", fixtures_dir=tmp_path)
