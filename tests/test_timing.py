"""Timing: where a run's time went (MCP tools, Claude, judge), per tool, over K runs, and that it
never touches the result."""
import asyncio
import json

import pytest

from evalkit import runner, timing
from evalkit.agent import Transcript
from evalkit.cases import Case
from evalkit.config import Environment
from tests.fakes import FakeClaude, settings, verdict


def _transcript(*calls, claude_ms=0):
    """calls: (tool, ms) pairs; ms None for a transcript written before timing existed."""
    t = Transcript(claude_ms=claude_ms)
    for name, ms in calls:
        e = {"kind": "tool", "tool": name, "args": {}, "blocked": False, "code": None, "chars": 0}
        if ms is not None:
            e["ms"] = ms
        t.events.append(e)
    return t


@pytest.mark.parametrize("ms, shown", [
    (None, "–"), (0, "0.0s"), (420, "0.4s"), (31_400, "31.4s"), (59_960, "1m 00s"),
    (108_000, "1m 48s"), (3_725_000, "62m 05s"),
])
def test_fmt(ms, shown):
    assert timing.fmt(ms) == shown


def test_a_run_splits_time_by_tool():
    t = _transcript(("list_programs", 400), ("get_credit_ledger", 600), ("list_programs", 500),
                    ("get_credit_ledger", 2100), claude_ms=70_000)
    r = timing.of_run(t, total_ms=108_000, judge_ms=3_200)
    assert (r["totalMs"], r["mcpMs"], r["claudeMs"], r["judgeMs"]) == (108_000, 3_600, 70_000, 3_200)
    assert r["tools"]["list_programs"] == {"calls": 2, "totalMs": 900, "maxMs": 500, "avgMs": 450}
    assert r["tools"]["get_credit_ledger"] == {"calls": 2, "totalMs": 2_700, "maxMs": 2_100, "avgMs": 1_350}
    case = timing.of_case([r])
    assert timing.summary(case) == "1m 48s total · MCP tools 3.6s"
    assert timing.summary(case, detail=True) == "1m 48s total · MCP tools 3.6s · Claude 1m 10s · judge 3.2s"
    assert timing.tool_lines(case, ["list_programs", "get_credit_ledger"]) == [
        "    list_programs      ×2     0.9s",
        "    get_credit_ledger  ×2     2.7s",
    ]
    assert timing.tool_lines(case, ["list_programs"], detail=True)[1].endswith("(avg 1.4s, max 2.1s)")


def test_k3_averages_runs_and_adds_up_tools():
    runs = [timing.of_run(_transcript(("get_health", ms)), total_ms=total, judge_ms=1_000)
            for ms, total in ((100, 130_000), (300, 161_000), (200, 185_000))]
    case = timing.of_case(runs)
    assert (case["runs"], case["totalMs"], case["minTotalMs"], case["maxTotalMs"]) == (3, 158_667, 130_000, 185_000)
    assert case["tools"]["get_health"] == {"calls": 3, "totalMs": 600, "maxMs": 300, "avgMs": 200}
    assert timing.summary(case) == "avg 2m 39s per run (2m 10s–3m 05s, 3 runs) · MCP tools 0.2s"


def test_a_run_that_crashed_has_a_total_but_no_tools():
    r = timing.of_run(None, total_ms=500, judge_ms=0)
    assert r == {"totalMs": 500, "judgeMs": 0, "claudeMs": 0, "mcpMs": 0, "tools": {}}


def test_old_transcripts_without_timings_show_a_dash():
    r = timing.of_run(_transcript(("get_health", None), ("list_programs", 300)), total_ms=1_000, judge_ms=0)
    assert r["mcpMs"] is None and r["tools"]["get_health"]["totalMs"] is None
    case = timing.of_case([r])
    assert timing.summary(case) == "1.0s total · MCP tools –"
    assert timing.tool_lines(case, ["get_health"])[0].split()[-1] == "–"


def test_skipped_cases_have_no_timing():
    assert timing.of_case([]) is None and timing.summary(None) is None


# --- whole runs ---

class SlowClaude(FakeClaude):
    """Each model call takes 50 ms, so Claude's time is measurable."""
    async def create(self, **kw):
        await asyncio.sleep(0.05)
        return await super().create(**kw)


def _calls(*names):
    def reply(kw):
        last = kw["messages"][-1]
        if last["role"] == "user" and isinstance(last["content"], str):
            return [("tool", n, {}) for n in names]
        return [("text", "Done.")]
    return reply


def slow_verdict(passed=True):
    async def judge_fn(case, transcript):
        await asyncio.sleep(0.03)
        return passed, "graded"
    return judge_fn


CASE = Case(id="R90", title="Timing check", path=None, admin_says=("How are things?",), pass_when="answers")


async def _run(stub_url, tmp_path, client, judge=None, k=1, case=CASE):
    lines = []
    rep, md_path = await runner.run(Environment("qa", stub_url), None, settings(k=k), [case], client=client,
                                    judge_fn=judge or slow_verdict(), full=False,
                                    results_root=tmp_path / "results", coverage_dir=tmp_path / "coverage",
                                    log=lines.append)
    return rep, md_path, lines


async def test_a_run_records_and_prints_its_timing(stub_url, tmp_path):
    rep, md_path, lines = await _run(stub_url, tmp_path, SlowClaude([_calls("get_health", "list_programs",
                                                                              "get_health")]))
    run = rep.cases[0].runs[0]["timing"]
    assert run["claudeMs"] >= 100 and run["judgeMs"] >= 30  # two model calls, one judge
    assert run["totalMs"] >= run["claudeMs"] + run["judgeMs"]
    assert run["tools"]["get_health"]["calls"] == 2 and run["mcpMs"] >= 0
    out = md_path.parent
    transcript = json.loads((out / "transcripts" / "R90_run1.json").read_text(encoding="utf-8"))
    assert all(isinstance(e["ms"], int) for e in transcript["events"] if e["kind"] == "tool")
    assert transcript["timing"]["totalMs"] == run["totalMs"] and transcript["claudeMs"] == run["claudeMs"]
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert data["cases"][0]["timing"]["tools"]["list_programs"]["calls"] == 1
    md = md_path.read_text(encoding="utf-8")
    assert "## MCP tool timing" in md and "| get_health | 2 |" in md
    time_line = next(line for line in lines if line.startswith("  Time:"))
    assert " total · MCP tools " in time_line
    assert [line.split()[:2] for line in lines[lines.index(time_line) + 1:]] == [["get_health", "×2"],
                                                                                 ["list_programs", "×1"]]


async def test_k3_shows_the_average_and_range(stub_url, tmp_path):
    rep, _, lines = await _run(stub_url, tmp_path, SlowClaude([_calls("get_health")]), k=3)
    assert rep.cases[0].timing["runs"] == 3 and rep.cases[0].timing["tools"]["get_health"]["calls"] == 3
    assert any(line.startswith("  Time:       avg ") and "3 runs)" in line for line in lines)


async def test_a_blocked_call_is_timed_but_never_reaches_the_server(stub_url, tmp_path):
    rep, _, _ = await _run(stub_url, tmp_path, SlowClaude([_calls("set_visibility")]))
    t = rep.cases[0].runs[0]["timing"]["tools"]["set_visibility"]
    assert t["calls"] == 1 and t["totalMs"] < 50  # blocked by evalkit before any network call


async def test_timing_never_changes_the_result(stub_url, tmp_path):
    passing, _, _ = await _run(stub_url, tmp_path / "a", SlowClaude([_calls("get_health")]))
    failing, _, _ = await _run(stub_url, tmp_path / "b", SlowClaude([_calls("get_health")]),
                               judge=slow_verdict(False))
    assert passing.cases[0].status == "PASS" and failing.cases[0].status == "FAIL"
    assert passing.cases[0].runs[0]["pass"] is True and failing.cases[0].runs[0]["pass"] is False
    assert set(passing.cases[0].timing) == set(failing.cases[0].timing)
