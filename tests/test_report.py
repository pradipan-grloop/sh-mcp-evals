import json

from evalkit.cases import Case
from evalkit.config import Settings
from evalkit.lint import Finding
from evalkit.report import (CaseResult, Report, changes, fails_threshold, findings, markdown,
                            previous_report, tool_rows)

TOOLS = [{"name": n} for n in ("get_health", "get_jobs", "set_videos", "set_lock")]


def run(passed, notes="", critical=(), fallbacks=()):
    return {"pass": passed, "notes": notes, "critical": list(critical), "toolCalls": [], "codes": [],
            "responseChars": 0, "tokens": 0, "fallbacks": list(fallbacks), "transcript": "t.json"}


def result(cid, runs=(), skipped=None, **kw):
    c = Case(id=cid, title=f"case {cid}", path=None, admin_says=("hi",), pass_when="ok", **kw)
    return CaseResult(c, list(runs), skipped)


def report(cases, lint=(), previous=None, tools=TOOLS):
    return Report(env="qa", url="https://qa/mcp", run_id="2026-11-04_120000_qa", started="s", finished="f",
                  evalkit="abc", server={"name": "stitched-health", "version": "2"}, settings=Settings(),
                  tools=tools, lint=list(lint), cases=list(cases), full=True,
                  write_tools=frozenset({"set_videos", "set_lock"}), previous=previous)


def test_case_status_from_runs():
    assert result("P", [run(True)] * 3).status == "PASS"
    assert result("F", [run(False, "no")] * 3).status == "FAIL"
    flaky = result("K", [run(True), run(False, "dumped the checklist"), run(True)])
    assert flaky.status == "FLAKY" and flaky.reason == "run 2: dumped the checklist"
    assert result("S", skipped="needs writes").status == "SKIPPED"
    fell = result("B", [run(True, fallbacks=["claude-opus-4-8"])])
    assert "claude-opus-4-8 after a refusal" in fell.reason


def test_findings_are_ranked_like_trivy():
    rep = report(
        [result("A1", [run(False, "tried set_lock", critical=["called set_lock, which this case forbids"])] * 2,
                must_call=("get_health",)),
         result("A2", [run(True), run(False, "slow")], covers=("get_jobs",)),
         result("A3", skipped="needs writes", covers=("set_videos",))],
        lint=[Finding("param-description", "error", "set_lock", "reason: no description"),
              Finding("param-description", "error", "set_lock", "ifVersion: no description"),
              Finding("name-snake-case", "warning", "get_jobs", "not snake")])
    got = [(f["severity"], f["kind"], f["item"]) for f in findings(rep)]
    assert got == [
        ("CRITICAL", "Unsafe write", "A1 case A1"),
        ("HIGH", "Case fails", "A1 case A1"),
        ("HIGH", "Untested", "set_lock"),
        ("MEDIUM", "Flaky", "A2 case A2"),
        ("MEDIUM", "Spec lint", "set_lock"),
        ("LOW", "Spec lint", "get_jobs"),
    ]
    lint_detail = findings(rep)[4]["detail"]
    assert lint_detail == "param-description: reason: no description; ifVersion: no description"


def test_tool_rows_take_the_worst_result():
    rep = report([result("A1", [run(True)], must_call=("get_health",)),
                  result("A2", [run(False, "x")], must_call=("get_health",)),
                  result("A3", skipped="w", covers=("set_videos",))])
    rows = {r["name"]: r for r in tool_rows(rep)}
    assert rows["get_health"]["result"] == "FAIL (A2)" and rows["get_health"]["cases"] == ["A1", "A2"]
    assert rows["set_videos"]["result"] == "SKIPPED" and rows["set_videos"]["write"]
    assert rows["get_jobs"]["result"] == "UNTESTED"
    assert [r["name"] for r in tool_rows(rep)][:2] == ["set_lock", "set_videos"]  # writes first


def test_markdown_has_every_section_and_escapes_pipes():
    rep = report([result("A1", [run(False, "said a|b")], covers=("set_publish",))])
    md = markdown(rep)
    for heading in ("# MCP eval report · qa", "## Summary", "## Findings", "## Case results",
                    "## Tool coverage", "## Spec lint", "## Changes since the last qa run"):
        assert heading in md
    assert "said a\\|b" in md
    assert "| Cases | 1 · 0 PASS · 0 FLAKY · 1 FAIL · 0 SKIPPED |" in md
    assert "| Tool coverage | 0 / 4 tools have a case (0%) · untested: 2 write, 2 read |" in md
    assert "`set_publish` (A1)" in md  # named by a case, not offered to this token
    assert "All 4 tools pass the spec lint." in md


def test_changes_since_last_run():
    assert changes(report([])) == ["First recorded run for qa."]
    prev = {"runId": "2026-11-03_120000_qa", "server": {"version": "1"},
            "tools": [{"name": "get_health"}, {"name": "get_jobs"}, {"name": "set_videos"}, {"name": "old_tool"}],
            "cases": [{"id": "A1", "status": "PASS"}]}
    lines = changes(report([result("A1", [run(False, "x")]), result("A2", [run(True)])], previous=prev))
    assert lines == ["Compared with run 2026-11-03_120000_qa.",
                     "New tool `set_lock`: no case covers it",
                     "Tool `old_tool` is no longer listed",
                     "A1: PASS → FAIL",
                     "New case A2: PASS",
                     "Server version 1 → 2"]


def test_previous_report_is_the_latest_earlier_one_for_the_env(tmp_path):
    for run_id, env in [("2026-11-01_1_qa", "qa"), ("2026-11-02_1_qa", "qa"), ("2026-11-03_1_staging", "staging"),
                        ("2026-11-09_1_qa", "qa")]:
        (tmp_path / run_id).mkdir()
        (tmp_path / run_id / "report.json").write_text(json.dumps({"env": env, "runId": run_id}), encoding="utf-8")
    assert previous_report(tmp_path, "qa", "2026-11-04_1_qa")["runId"] == "2026-11-02_1_qa"
    assert previous_report(tmp_path, "dev", "2026-11-04_1_dev") is None


def test_fail_on_threshold():
    rep = report([result("A1", [run(False, "x")], covers=("get_health", "get_jobs", "set_videos", "set_lock"))])
    assert fails_threshold(rep, ["HIGH"]) and fails_threshold(rep, ["high", "CRITICAL"])
    assert not fails_threshold(rep, ["CRITICAL"])
