"""How long a run took, and where the time went: the MCP server (each tool call), Claude's
model calls and the judge. Measured during the run (agent.py, runner.py); informational only,
never part of the result.

A run's timing (of_run) is stored in its run record and transcript as `timing`; a case's
(of_case) sums its K runs.
"""


def of_run(transcript, total_ms, judge_ms):
    """One run. `transcript` may be None when the run stopped on an API or network error."""
    events = [e for e in (transcript.events if transcript else []) if e.get("kind") == "tool"]
    tools = {}
    for e in events:
        ms = e.get("ms")
        t = tools.setdefault(e["tool"], {"calls": 0, "totalMs": 0, "maxMs": 0, "timed": True})
        t["calls"] += 1
        if ms is None:  # a transcript written before timing existed
            t["timed"] = False
            continue
        t["totalMs"] += ms
        t["maxMs"] = max(t["maxMs"], ms)
    for t in tools.values():
        t["avgMs"] = round(t["totalMs"] / t["calls"]) if t["timed"] and t["calls"] else None
        if not t.pop("timed"):
            t["totalMs"] = t["maxMs"] = None
    timed = all(t["totalMs"] is not None for t in tools.values())
    return {"totalMs": round(total_ms), "judgeMs": round(judge_ms),
            "claudeMs": round(transcript.claude_ms) if transcript else 0,
            "mcpMs": round(sum(t["totalMs"] for t in tools.values())) if timed else None,
            "tools": tools}


def of_case(runs):
    """A case over its runs: the average, fastest and slowest run, and per tool the calls and
    time over all runs together. None when no run has a timing (a SKIPPED case)."""
    runs = [r for r in runs if r]
    if not runs:
        return None
    totals = [r["totalMs"] for r in runs]

    def avg(key):
        values = [r[key] for r in runs]
        return None if any(v is None for v in values) else round(sum(values) / len(values))

    return {"runs": len(runs), "totalMs": avg("totalMs"), "minTotalMs": min(totals), "maxTotalMs": max(totals),
            "mcpMs": avg("mcpMs"), "claudeMs": avg("claudeMs"), "judgeMs": avg("judgeMs"),
            "tools": _merge(r["tools"] for r in runs)}


def _merge(tool_maps):
    """Add up {tool: {calls, totalMs, maxMs}} maps. A tool with any untimed call has no time."""
    out = {}
    for tools in tool_maps:
        for name, t in tools.items():
            o = out.setdefault(name, {"calls": 0, "totalMs": 0, "maxMs": 0})
            o["calls"] += t["calls"]
            if t["totalMs"] is None or o["totalMs"] is None:
                o["totalMs"] = o["maxMs"] = None
            else:
                o["totalMs"] += t["totalMs"]
                o["maxMs"] = max(o["maxMs"], t["maxMs"])
    for o in out.values():
        o["avgMs"] = round(o["totalMs"] / o["calls"]) if o["totalMs"] is not None and o["calls"] else None
    return out


def fmt(ms):
    """0.4s · 31.4s · 1m 48s · – (unknown)."""
    if ms is None:
        return "–"
    s = ms / 1000
    if round(s, 1) < 60:
        return f"{s:.1f}s"
    m, s = divmod(round(s), 60)
    return f"{m}m {s:02d}s"


def summary(t, detail=False):
    """The Time line: '1m 48s total · MCP tools 31.4s'. Over K runs the average per run and the
    range. `detail` adds Claude's and the judge's time."""
    if t is None:
        return None
    if t["runs"] == 1:
        head = f"{fmt(t['totalMs'])} total"
    else:
        head = f"avg {fmt(t['totalMs'])} per run ({fmt(t['minTotalMs'])}–{fmt(t['maxTotalMs'])}, {t['runs']} runs)"
    parts = [head, f"MCP tools {fmt(t['mcpMs'])}"]
    if detail:
        parts += [f"Claude {fmt(t['claudeMs'])}", f"judge {fmt(t['judgeMs'])}"]
    return " · ".join(parts)


def tool_lines(t, order, indent="    ", detail=False):
    """One line per tool, in the order first called: name, calls and time over all runs."""
    if not t or not t["tools"]:
        return []
    names = [n for n in order if n in t["tools"]] + [n for n in t["tools"] if n not in order]
    width = max(len(n) for n in names)
    counts = max(len(str(t["tools"][n]["calls"])) for n in names) + 1
    lines = []
    for n in names:
        s = t["tools"][n]
        line = f"{indent}{n:<{width}}  {'×' + str(s['calls']):<{counts}}  {fmt(s['totalMs']):>7}"
        if detail:
            line += f"  (avg {fmt(s['avgMs'])}, max {fmt(s['maxMs'])})"
        lines.append(line)
    return lines


def totals(results):
    """Per tool over every case in a run report: calls, total, avg, max. For report.md."""
    out = _merge(c.timing["tools"] for c in results if c.timing)
    return dict(sorted(out.items(), key=lambda kv: -(kv[1]["totalMs"] or 0)))
