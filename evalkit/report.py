"""The run report, laid out like a Trivy scan: summary, findings by severity, then detail.
Written as report.md (people) and report.json (comparing runs)."""
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from evalkit import usage as mcp_usage

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
RESULT_ORDER = {"FAIL": 0, "FLAKY": 1, "UNTESTED": 2, "SKIPPED": 3, "PASS": 4}


@dataclass
class CaseResult:
    case: object  # cases.Case
    runs: list = field(default_factory=list)  # one dict per run; see runner._run_record
    skipped: str | None = None

    @property
    def passed(self):
        return sum(r["pass"] for r in self.runs)

    @property
    def status(self):
        if self.skipped:
            return "SKIPPED"
        if self.passed == len(self.runs):
            return "PASS"
        return "FAIL" if self.passed == 0 else "FLAKY"

    @property
    def usage(self):
        """MCP tool usage over the runs (evalkit.usage). Informational: never part of status."""
        return mcp_usage.of_case([r.get("mcpUsage") for r in self.runs], self.skipped)

    @property
    def reason(self):
        if self.skipped:
            return self.skipped
        failing = [(i, r) for i, r in enumerate(self.runs, 1) if not r["pass"]]
        text = ""
        if failing and self.status == "FAIL":
            text = failing[0][1]["notes"]
        elif failing:
            text = f"run {failing[0][0]}: {failing[0][1]['notes']}"
        fell_back = sorted({m for r in self.runs for m in r["fallbacks"]})
        if fell_back:
            text += f" (some replies came from {', '.join(fell_back)} after a refusal)"
        return text.strip()


@dataclass
class Report:
    env: str
    url: str
    run_id: str
    started: str
    finished: str
    evalkit: str
    server: dict
    settings: object  # config.Settings
    tools: list  # tools/list entries
    lint: list  # lint.Finding
    cases: list  # CaseResult
    full: bool
    write_tools: frozenset = frozenset()  # names of listed tools that change data
    previous: dict | None = None  # the last report.json for this environment


# --- derived views ---

def tool_rows(rep):
    rows = []
    for t in rep.tools:
        name = t["name"]
        mine = [c for c in rep.cases if name in c.case.tools]
        ran = [c for c in mine if c.status != "SKIPPED"]
        if ran:
            worst = min(ran, key=lambda c: RESULT_ORDER[c.status])
            result = worst.status if worst.status == "PASS" else f"{worst.status} ({worst.case.id})"
        else:
            result = "SKIPPED" if mine else "UNTESTED"
        rows.append({"name": name, "write": name in rep.write_tools, "cases": [c.case.id for c in mine],
                     "result": result})
    return sorted(rows, key=lambda r: (not r["write"], r["name"]))


def unlisted_tools(rep):
    """Tools that cases name but this token was not offered: {tool: [case ids]}."""
    listed = {t["name"] for t in rep.tools}
    out = {}
    for c in rep.cases:
        for tool in sorted(c.case.tools - listed):
            out.setdefault(tool, []).append(c.case.id)
    return out


def findings(rep):
    out = []

    def add(sev, kind, item, detail):
        out.append({"severity": sev, "kind": kind, "item": item, "detail": detail})

    for c in rep.cases:
        if c.status == "SKIPPED":
            continue
        label = f"{c.case.id} {c.case.title}"
        for msg in dict.fromkeys(m for r in c.runs for m in r["critical"]):
            add("CRITICAL", "Unsafe write", label, msg)
        k = len(c.runs)
        if c.status == "FAIL":
            add("HIGH", "Case fails", label, f"0/{k} runs passed: {c.reason}")
        elif c.status == "FLAKY":
            add("MEDIUM", "Flaky", label, f"{c.passed}/{k} runs passed; {c.reason}")
    for row in tool_rows(rep):
        if row["result"] == "UNTESTED":
            if row["write"]:
                add("HIGH", "Untested", row["name"], "write tool, no case")
            else:
                add("LOW", "Untested", row["name"], "read tool, no case")
    grouped = {}
    for f in rep.lint:
        grouped.setdefault((f.tool, f.rule, f.severity), []).append(f.message)
    for (tool, rule, sev), msgs in grouped.items():
        add("MEDIUM" if sev == "error" else "LOW", "Spec lint", tool, f"{rule}: {'; '.join(msgs)}")
    return sorted(out, key=lambda f: (SEVERITIES.index(f["severity"]), f["kind"], f["item"]))


def counts(rep, found=None):
    found = findings(rep) if found is None else found
    by_status = {s: sum(c.status == s for c in rep.cases) for s in ("PASS", "FLAKY", "FAIL", "SKIPPED")}
    rows = tool_rows(rep)
    untested = [r for r in rows if r["result"] == "UNTESTED"]
    lint_tools = {f.tool for f in rep.lint if f.severity == "error"}
    return {
        "cases": {"total": len(rep.cases), **by_status},
        "tools": {"listed": len(rows), "covered": sum(bool(r["cases"]) for r in rows),
                  "untestedWrite": sum(r["write"] for r in untested),
                  "untestedRead": sum(not r["write"] for r in untested)},
        "lint": {"cleanTools": len(rows) - len(lint_tools),
                 "errors": sum(f.severity == "error" for f in rep.lint),
                 "warnings": sum(f.severity == "warning" for f in rep.lint)},
        "findings": {s: sum(f["severity"] == s for f in found) for s in SEVERITIES},
    }


def changes(rep):
    """What moved since the last report for this environment, as bullet lines."""
    prev = rep.previous
    if not prev:
        return [f"First recorded run for {rep.env}."]
    lines = [f"Compared with run {prev['runId']}."]
    before = {t["name"] for t in prev.get("tools", [])}
    now = {r["name"]: r for r in tool_rows(rep)}
    for name in sorted(set(now) - before):
        covered = ", ".join(now[name]["cases"])
        lines.append(f"New tool `{name}`: " + (f"covered by {covered}" if covered else "no case covers it"))
    for name in sorted(before - set(now)):
        lines.append(f"Tool `{name}` is no longer listed")
    was = {c["id"]: c["status"] for c in prev.get("cases", [])}
    for c in rep.cases:
        old = was.get(c.case.id)
        if old is None:
            lines.append(f"New case {c.case.id}: {c.status}")
        elif old != c.status:
            lines.append(f"{c.case.id}: {old} → {c.status}")
    if prev.get("server", {}).get("version") != rep.server.get("version"):
        lines.append(f"Server version {prev.get('server', {}).get('version')} → {rep.server.get('version')}")
    if len(lines) == 1:
        lines.append("No change in tools or case results.")
    return lines


def previous_report(results_root, env, before_run_id):
    best = None
    for path in Path(results_root).glob("*/report.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("env") == env and data.get("runId", "") < before_run_id:
            if best is None or data["runId"] > best["runId"]:
                best = data
    return best


def fails_threshold(rep, severities):
    """True if any finding has one of `severities` (for --fail-on)."""
    wanted = {s.strip().upper() for s in severities if s.strip()}
    return any(f["severity"] in wanted for f in findings(rep))


# --- output ---

def _cell(value):
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def _summary_rows(rep, n):
    c, t, li, f = n["cases"], n["tools"], n["lint"], n["findings"]
    pct = f" ({t['covered'] / t['listed']:.0%})" if t["listed"] else ""
    return [
        ["Cases", f"{c['total']} · {c['PASS']} PASS · {c['FLAKY']} FLAKY · {c['FAIL']} FAIL · {c['SKIPPED']} SKIPPED"],
        ["Tool coverage", f"{t['covered']} / {t['listed']} tools have a case{pct} · untested: "
                          f"{t['untestedWrite']} write, {t['untestedRead']} read"],
        ["Spec lint", f"{li['cleanTools']} / {t['listed']} tools clean · {li['errors']} errors, "
                      f"{li['warnings']} warnings"],
        ["**Findings**", " · ".join(f"{s} {f[s]}" for s in SEVERITIES)],
    ]


def _findings_table(found):
    if not found:
        return "No findings."
    return table(["Severity", "Kind", "Item", "Detail"],
                  [[f["severity"], f["kind"], f["item"], f["detail"]] for f in found])


def markdown(rep):
    s = rep.settings
    found = findings(rep)
    n = counts(rep, found)
    server = " ".join(str(v) for v in (rep.server.get("name"), rep.server.get("version")) if v) or "unknown"
    scope = "all cases" if rep.full else "some cases: " + ", ".join(c.case.id for c in rep.cases)
    out = [
        f"# MCP eval report · {rep.env}",
        "",
        table(["", ""], [
            ["Environment", f"{rep.env} · {rep.url}"],
            ["Server", server],
            ["Run", f"{rep.started} → {rep.finished} · evalkit {rep.evalkit} · {rep.run_id}"],
            ["Model", f"{s.model} (effort {s.effort}) · K={s.k} · judge {s.judge_model} (effort {s.judge_effort})"],
            ["Scope", scope],
        ]),
        "",
        "## Summary",
        "",
        table(["Check", "Result"], _summary_rows(rep, n)),
        "",
        "## Findings",
        "",
        _findings_table(found),
        "",
        "## Case results",
        "",
    ]
    if rep.cases:
        out.append(table(["Case", "Title", "Runs", "Status", "MCP tools", "Reason"], [
            [c.case.id, c.case.title, "–" if c.skipped else f"{c.passed}/{len(c.runs)}", c.status,
             mcp_usage.describe(c.usage), c.reason]
            for c in rep.cases]))
        out += ["", "## MCP tool usage", "",
                "Distinct server tools Claude called per run, worst run per case. Informational: "
                "a case can PASS and still be Risky.", "",
                table(["Rating", "Cases", "Which"], [
                    [label, len(ids), ", ".join(ids) or "–"]
                    for label, ids in mcp_usage.tally(rep.cases).items()
                    if ids or label in mcp_usage.RANK])]
    else:
        out.append("No cases ran.")
    out += ["", "## Tool coverage", "",
            table(["Tool", "Type", "Cases", "Result"], [
                [r["name"], "write" if r["write"] else "read", ", ".join(r["cases"]) or "–", r["result"]]
                for r in tool_rows(rep)])]
    hidden = unlisted_tools(rep)
    if hidden:
        out += ["", "Cases name tools this token was not offered: "
                + "; ".join(f"`{tool}` ({', '.join(ids)})" for tool, ids in hidden.items()) + "."]
    out += ["", "## Spec lint", ""]
    if rep.lint:
        out.append(table(["Tool", "Rule", "Severity", "Detail"],
                          [[f.tool, f.rule, f.severity.upper(), f.message] for f in rep.lint]))
    else:
        out.append(f"All {len(rep.tools)} tools pass the spec lint.")
    out += ["", f"## Changes since the last {rep.env} run", ""]
    out += [f"- {line}" for line in changes(rep)]
    out += ["", f"Transcripts: `results/{rep.run_id}/transcripts/` (kept out of git).", ""]
    return "\n".join(out)


def as_json(rep):
    found = findings(rep)
    return {
        "env": rep.env, "url": rep.url, "runId": rep.run_id, "started": rep.started,
        "finished": rep.finished, "evalkit": rep.evalkit, "server": rep.server,
        "settings": asdict(rep.settings), "full": rep.full,
        "summary": counts(rep, found),
        "findings": found,
        "cases": [{"id": c.case.id, "title": c.case.title, "status": c.status, "skipped": c.skipped,
                   "passRate": (c.passed / len(c.runs)) if c.runs else None, "runs": c.runs,
                   "mcpUsage": c.usage}
                  for c in rep.cases],
        "mcpUsage": {label: ids for label, ids in mcp_usage.tally(rep.cases).items()},
        "tools": tool_rows(rep),
        "lint": [asdict(f) for f in rep.lint],
    }


def terminal(rep, report_path):
    found = findings(rep)
    return "\n".join([
        "",
        f"MCP eval · {rep.env} · {rep.run_id}",
        "",
        table(["Check", "Result"], _summary_rows(rep, counts(rep, found))),
        "",
        _findings_table(found),
        "",
        f"Full report: {report_path}",
    ])


def answers(run_dir):
    """Each run's outcome in plain text: verdict, the judge's reason, the tools Claude called
    and Claude's final answer, read back from the run's transcripts."""
    files = sorted(Path(run_dir, "transcripts").glob("*.json"))
    runs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    runs.sort(key=lambda d: (d.get("case", ""), d.get("run", 0)))
    blocks = []
    for d in runs:
        tool_events = [e for e in d.get("events", []) if e.get("kind") == "tool"]
        used = {}
        for e in tool_events:
            used[e["tool"]] = used.get(e["tool"], 0) + 1
        said = [e["text"] for e in d.get("events", []) if e.get("kind") == "claude"]
        asked = [e["text"] for e in d.get("events", []) if e.get("kind") == "admin"]
        blocked = sum(1 for e in tool_events if e.get("blocked"))
        rule = "=" * 78
        lines = [
            "",
            rule,
            f"{d.get('case')} · run {d.get('run')} · {'PASS' if d.get('pass') else 'FAIL'} · {d.get('title', '')}",
            rule,
            f"Judge:  {d.get('reason', '')}",
            "Tools:  " + (", ".join(f"{n} ×{c}" for n, c in used.items()) or "none")
            + f"  ({len(tool_events)} calls, {d.get('modelCalls', 0)} model calls"
            + (f", {blocked} BLOCKED" if blocked else "") + ")",
        ]
        if d.get("error"):
            lines.append(f"Stopped: {d['error']}")
        for a in asked:
            lines.append(f"Admin:  {a}")
        lines += ["", "Claude's answer:", "", said[-1] if said else "(no answer)"]
        blocks.append("\n".join(lines))
    return "\n".join(blocks)
