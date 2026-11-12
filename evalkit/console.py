"""What `evalkit run` prints. Short by default: per test its name, result, the MCP tool rating,
the time taken and the EPs the answer came from; then a summary of how many tests passed,
failed or were flaky, and where the full report is. `--details` adds everything report.md holds."""
import os
import shutil

from evalkit import sources, timing, usage
from evalkit.report import terminal

# The summary's rows: (status, label). Colours are in usage.COLOURS.
OUTCOMES = (("PASS", "Passed"), ("FAIL", "Failed"), ("FLAKY", "Flaky"), ("SKIPPED", "Skipped"))


def result_text(result):
    """'PASS (1 of 1 runs passed)', 'FLAKY (2 of 3 runs passed)', 'SKIPPED (not run)'."""
    if result.skipped:
        return "SKIPPED (not run)"
    return f"{result.status} ({result.passed} of {len(result.runs)} runs passed)"


def case_block(result, paint=None, detail=False):
    """The lines printed once a test has finished."""
    paint = paint or usage.plain
    c, u, t = result.case, result.usage, result.timing
    label = dict(OUTCOMES)[result.status]
    lines = ["", f"Test:       {c.id} · {c.title}",
             f"  Result:     {paint(label, result_text(result))}"]
    if result.status != "PASS" and result.reason:
        lines.append(f"  Reason:     {result.reason}")
    lines.append(f"  MCP tools:  {usage.describe(u, paint)}")
    if t:
        lines.append(f"  Time:       {timing.summary(t, detail)}")
        lines += timing.tool_lines(t, u.get("tools") or [], detail=detail)
    s = result.sources
    if s:
        if len(result.runs) > 1:
            s = {**s, "measure": f"{s['measure']} (run 1)" if s.get("measure") else "run 1"}
        lines += sources.lines(s)
    return lines


def summary(rep, paint=None):
    """How many tests passed, failed, were flaky or skipped, each with its tests by name; then
    the MCP tool usage and the total time."""
    paint = paint or usage.plain
    n = len(rep.cases)
    width = max(40, shutil.get_terminal_size((100, 20)).columns - 1)
    lines = ["", f"Summary · {rep.env} · {n} test{'' if n == 1 else 's'}"]
    for status, label in OUTCOMES:
        tests = [c for c in rep.cases if c.status == status]
        if status == "SKIPPED" and not tests:
            continue
        lines.append(f"  {paint(label, f'{label}:'.ljust(9))}{len(tests):>3}")
        for c in tests:
            name = f"{c.case.id}  {c.case.title}"
            lines.append(f"      {name if len(name) <= width - 6 else name[:width - 7] + '…'}")
    lines.append(f"  {usage.summary_line(rep.cases, paint)}")
    ran = [c for c in rep.cases if c.timing]
    if ran:
        total = sum(c.timing["totalMs"] * c.timing["runs"] for c in ran)
        mcp = [c.timing["mcpMs"] for c in ran]
        mcp_total = None if None in mcp else sum(m * c.timing["runs"] for m, c in zip(mcp, ran))
        lines.append(f"  Time:     {timing.fmt(total)} total · MCP tools {timing.fmt(mcp_total)}")
    return lines


def footer(rep, report_path, paint=None, detail=False):
    """Printed after the last test."""
    paint = paint or usage.plain
    head = [terminal(rep, report_path), "", *usage.summary_lines(rep.cases, paint)] if detail else []
    return "\n".join([*head, *summary(rep, paint), f"Full report: {_short(report_path)}"])


def _short(path):
    """The path relative to where the command was run, when that is shorter."""
    try:
        rel = os.path.relpath(path)
    except ValueError:  # another drive on Windows
        return str(path)
    return rel if len(rel) < len(str(path)) else str(path)
