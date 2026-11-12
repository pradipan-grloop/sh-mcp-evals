"""MCP tool usage rating: bands, counting from the run, K runs, and that it never touches the result."""
import io
import json

import pytest

from evalkit import runner, usage
from evalkit.cases import Case
from evalkit.config import Environment
from tests.fakes import FakeClaude, settings, verdict

STUB_TOOLS = ("get_health", "list_programs", "get_program_readiness", "search_learners")


# --- bands ---

@pytest.mark.parametrize("distinct, rating", [
    (0, "No MCP tools"), (1, "Best"), (2, "Best"), (3, "Good"), (5, "Good"),
    (6, "Concerning"), (8, "Concerning"), (9, "Risky"), (15, "Risky"),
])
def test_bands(distinct, rating):
    u = usage.of_calls([f"tool_{i}" for i in range(distinct)])
    assert (u["distinct"], u["calls"], u["rating"]) == (distinct, distinct, rating)


def test_repeated_calls_count_once_for_the_rating_but_all_for_calls():
    u = usage.of_calls(["list_programs", "list_programs", "get_program", "list_programs"])
    assert u == {"rating": "Best", "distinct": 2, "calls": 4, "tools": ["list_programs", "get_program"]}
    assert usage.describe(usage.of_case([u])) == "2 distinct (4 calls) → Best"


def test_one_run_reads_like_the_spec():
    u = usage.of_case([usage.of_calls(["list_programs", "get_case_studies", "get_engagement_metrics",
                                       "get_case_studies", "list_programs"])])
    assert usage.describe(u) == "3 distinct (5 calls) → Good"


def test_k_runs_show_the_worst_and_the_range():
    runs = [usage.of_calls([f"t{i}" for i in range(n)]) for n in (4, 7, 5)]
    assert usage.describe(usage.of_case(runs)) == "4–7 tools (4–7 calls) → Concerning (worst of 3)"


def test_no_tools_in_any_run_ranks_worst():
    runs = [usage.of_calls([f"t{i}" for i in range(12)]), usage.of_calls([])]
    assert usage.of_case(runs)["rating"] == "No MCP tools"


def test_skipped_and_errored_runs_are_not_rated():
    assert usage.of_case([], skipped="needs write access")["rating"] == "not run"
    assert usage.describe(usage.of_case([None, None])) == "not rated"
    partly = usage.of_case([None, usage.of_calls(["get_health"])])
    assert usage.describe(partly) == "1 tool (1 call) → Best (worst of 1 rated, 2 runs)"


# --- colour ---

def test_colour_only_on_a_terminal(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert usage.painter(io.StringIO())("Risky") == "Risky"  # a file or pipe: plain
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert usage.painter(io.StringIO())("Risky") == "\033[31mRisky\033[0m"
    monkeypatch.setenv("NO_COLOR", "1")
    assert usage.painter(io.StringIO())("Risky") == "Risky"


def test_summary_lines_up_with_and_without_colour(monkeypatch):
    class R:
        def __init__(self, cid, rating):
            self.case, self.usage = Case(id=cid, title="t", path=None, admin_says=("hi",)), {"rating": rating}
    results = [R("R01", "Best"), R("R02", "Best"), R("R08", "Concerning"), R("A06", "Risky")]
    assert usage.summary_lines(results) == [
        "MCP tool usage",
        "  Best:           2",
        "  Good:           0",
        "  Concerning:     1  (R08)",
        "  Risky:          1  (A06)",
        "  No MCP tools:   0",
    ]
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    coloured = usage.summary_lines(results, usage.painter(io.StringIO()))
    strip = [line.replace("\033[0m", "").split("m", 1)[-1] if "\033[" in line else line for line in coloured]
    assert [s.strip() for s in strip] == [s.strip() for s in usage.summary_lines(results)]


# --- whole runs, counted from the transcript ---

def _tools_per_run(*per_run):
    """A FakeClaude that, in run i, calls per_run[i] (all at once) after each admin message,
    then answers. A list of lists gives a different set per admin turn."""
    seen = {"admin": 0}

    def reply(kw):
        last = kw["messages"][-1]
        if last["role"] == "user" and isinstance(last["content"], str):
            seen["admin"] += 1
            names = per_run[seen["admin"] - 1]
            return [("tool", n, {}) for n in names]
        return [("text", "Done.")]
    return FakeClaude([reply])


async def _run(stub_url, tmp_path, cases, client, judge=None, k=1):
    lines = []
    rep, md_path = await runner.run(Environment("qa", stub_url), None, settings(k=k), cases, client=client,
                                    judge_fn=judge or verdict(), full=False, results_root=tmp_path / "results",
                                    coverage_dir=tmp_path / "coverage", log=lines.append)
    return rep, md_path, lines


CASE = Case(id="R90", title="Usage check", path=None, admin_says=("How are things?",), pass_when="answers")


async def test_a_run_is_rated_from_what_claude_called(stub_url, tmp_path):
    client = _tools_per_run(["list_programs", "get_health", "list_programs", "get_program_readiness",
                             "list_programs"])
    rep, md_path, lines = await _run(stub_url, tmp_path, [CASE], client)
    assert rep.cases[0].usage["rating"] == "Good"
    block = lines[lines.index("R90  Usage check — PASS"):]
    assert block[1] == "  MCP tools:  3 distinct (5 calls) → Good"
    assert block[2].startswith("  Time:       ") and " total · MCP tools " in block[2]
    assert [line.split()[:2] for line in block[3:]] == [  # tools in first-call order, with call counts
        ["list_programs", "×3"], ["get_health", "×1"], ["get_program_readiness", "×1"]]
    out = md_path.parent
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert data["cases"][0]["mcpUsage"]["rating"] == "Good"
    assert data["cases"][0]["runs"][0]["mcpUsage"] == {
        "rating": "Good", "distinct": 3, "calls": 5,
        "tools": ["list_programs", "get_health", "get_program_readiness"]}
    assert data["mcpUsage"]["Good"] == ["R90"]
    transcript = json.loads((out / "transcripts" / "R90_run1.json").read_text(encoding="utf-8"))
    assert transcript["mcpUsage"]["distinct"] == 3
    md = md_path.read_text(encoding="utf-8")
    assert "| R90 | Usage check | 1/1 | PASS | 3 distinct (5 calls) → Good |" in md
    assert "## MCP tool usage" in md and "| Good | 1 | R90 |" in md


async def test_multi_turn_counts_every_turn_together(stub_url, tmp_path):
    case = Case(id="R91", title="Two turns", path=None, admin_says=("First?", "And then?"), pass_when="ok")
    client = _tools_per_run(["get_health", "list_programs"], ["list_programs", "search_learners"])
    rep, _, _ = await _run(stub_url, tmp_path, [case], client)
    u = rep.cases[0].usage
    assert (u["distinct"], u["calls"], u["rating"]) == (3, 4, "Good")
    assert u["tools"] == ["get_health", "list_programs", "search_learners"]


async def test_k3_rates_each_run_and_shows_the_worst(stub_url, tmp_path):
    client = _tools_per_run(["get_health"], list(STUB_TOOLS), ["get_health", "list_programs", "get_health"])
    rep, _, lines = await _run(stub_url, tmp_path, [CASE], client, k=3)
    c = rep.cases[0]
    assert [r["mcpUsage"]["distinct"] for r in c.runs] == [1, 4, 2]
    assert c.usage["rating"] == "Good" and c.status == "PASS"
    assert "  MCP tools:  1–4 tools (1–4 calls) → Good (worst of 3)" in lines


async def test_the_rating_never_changes_the_result(stub_url, tmp_path):
    many = list(STUB_TOOLS)  # 4 distinct
    passing, _, _ = await _run(stub_url, tmp_path / "a", [CASE], _tools_per_run(many))
    failing, _, _ = await _run(stub_url, tmp_path / "b", [CASE], _tools_per_run(many),
                               judge=verdict(False, "made it up"))
    assert passing.cases[0].status == "PASS" and failing.cases[0].status == "FAIL"
    assert passing.cases[0].usage == failing.cases[0].usage
    none, _, _ = await _run(stub_url, tmp_path / "c", [CASE], _tools_per_run([]))
    assert none.cases[0].status == "PASS" and none.cases[0].usage["rating"] == "No MCP tools"


async def test_a_skipped_case_shows_not_run(stub_url, tmp_path):
    case = Case(id="A05", title="Publish", path=None, admin_says=("Publish it.",),
                start_state="eval-half-built", pass_when="ok")
    rep, _, lines = await _run(stub_url, tmp_path, [case], _tools_per_run([]))
    assert rep.cases[0].status == "SKIPPED"
    assert "A05  Publish — SKIPPED" in lines and "  MCP tools:  not run" in lines
    assert not any(line.startswith("  Time:") for line in lines)  # nothing ran, so no time


def test_summary_line_for_several_cases():
    class R:
        def __init__(self, cid, rating):
            self.case, self.usage = Case(id=cid, title="t", path=None, admin_says=("hi",)), {"rating": rating}
    results = [R("R01", "Best"), R("R08", "Concerning"), R("R17", "Concerning"), R("A06", "Risky")]
    assert usage.summary_line(results) == (
        "MCP tool usage: Best 1 · Good 0 · Concerning 2 (R08, R17) · Risky 1 (A06) · No MCP tools 0")
