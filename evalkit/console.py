"""What `evalkit run` prints. Short by default: per case its result, the MCP tool rating and the
time taken, then where the full report is. `--details` prints everything, as report.md holds."""
import os

from evalkit import timing, usage
from evalkit.report import terminal


def case_block(result, paint=None, detail=False):
    """The lines printed once a case has finished."""
    paint = paint or usage.plain
    c, u, t = result.case, result.usage, result.timing
    status = result.status
    if status == "FLAKY":
        status = f"FLAKY ({result.passed}/{len(result.runs)} passed)"
    lines = ["", f"{c.id}  {c.title} — {status}"]
    if result.status != "PASS" and result.reason:
        lines.append(f"  Reason:     {result.reason}")
    lines.append(f"  MCP tools:  {usage.describe(u, paint)}")
    if t:
        lines.append(f"  Time:       {timing.summary(t, detail)}")
        lines += timing.tool_lines(t, u.get("tools") or [], detail=detail)
    return lines


def footer(rep, report_path, paint=None, detail=False):
    """Printed after the last case."""
    paint = paint or usage.plain
    if detail:
        return "\n".join([terminal(rep, report_path), "", *usage.summary_lines(rep.cases, paint)])
    lines = [""]
    ran = [c for c in rep.cases if c.timing]
    if len(rep.cases) > 1:
        lines.append(usage.summary_line(rep.cases, paint))
        if ran:
            total = sum(c.timing["totalMs"] * c.timing["runs"] for c in ran)
            mcp = [c.timing["mcpMs"] for c in ran]
            mcp_total = None if None in mcp else sum(m * c.timing["runs"] for m, c in zip(mcp, ran))
            lines.append(f"Time: {timing.fmt(total)} total · MCP tools {timing.fmt(mcp_total)}")
    lines.append(f"Full report: {_short(report_path)}")
    return "\n".join(lines)


def _short(path):
    """The path relative to where the command was run, when that is shorter."""
    try:
        rel = os.path.relpath(path)
    except ValueError:  # another drive on Windows
        return str(path)
    return rel if len(rel) < len(str(path)) else str(path)
