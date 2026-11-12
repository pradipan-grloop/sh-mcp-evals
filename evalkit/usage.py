"""MCP tool usage rating: how many different server tools Claude called in a run.

Counted from the run itself (the transcript's tool events, every turn of a multi-turn case
together, calls evalkit blocked included), never from the case file. It is separate from the
result: a case can PASS and still be Risky. Fewer distinct tools for the same answer is better.
"""
import os
import sys

# The bands: (fewest distinct tools, rating), checked from the top. Change them here.
BANDS = (
    (9, "Risky"),
    (6, "Concerning"),
    (3, "Good"),
    (1, "Best"),
)
NO_TOOLS = "No MCP tools"  # 0 tools: the case probably did not do its job
NOT_RUN = "not run"  # a SKIPPED case
NOT_RATED = "not rated"  # every run stopped on an API or network error, so there is no transcript

# Worst last. A case is shown with the worst rating of its runs.
RANK = ("Best", "Good", "Concerning", "Risky", NO_TOOLS)
FLAGGED = ("Concerning", "Risky", NO_TOOLS)  # the summary names these cases

COLOURS = {"Best": "32", "Good": "34", "Concerning": "33", "Risky": "31", NO_TOOLS: "35"}


def rating(distinct):
    if distinct <= 0:
        return NO_TOOLS
    return next(label for fewest, label in BANDS if distinct >= fewest)


def of_calls(names):
    """One run, from the names of the tools Claude called, in order."""
    tools = list(dict.fromkeys(names))  # distinct, in the order first called
    return {"rating": rating(len(tools)), "distinct": len(tools), "calls": len(names), "tools": tools}


def of_transcript(transcript):
    """One run's usage, or None when the run left no transcript (an API or network error)."""
    if transcript is None:
        return None
    return of_calls([name for name, _ in transcript.calls])


def of_case(runs, skipped=None):
    """A case over its K runs: the worst rating, the range of distinct tools and of calls, and
    every tool called in any run. `runs` holds each run's of_transcript() result."""
    if skipped:
        return {"rating": NOT_RUN}
    rated = [u for u in runs if u]
    if not rated:
        return {"rating": NOT_RATED, "runs": len(runs), "rated": 0}
    worst = max(rated, key=lambda u: RANK.index(u["rating"]))
    distinct = [u["distinct"] for u in rated]
    calls = [u["calls"] for u in rated]
    return {"rating": worst["rating"], "distinct": max(distinct), "minDistinct": min(distinct),
            "calls": max(calls), "minCalls": min(calls), "runs": len(runs), "rated": len(rated),
            "tools": list(dict.fromkeys(t for u in rated for t in u["tools"]))}


def _span(low, high):
    return f"{low}" if low == high else f"{low}–{high}"


def describe(u, paint=None):
    """'3 distinct (5 calls) → Good', or over K runs '4–7 tools (5–12 calls) → Concerning (worst of 3)'."""
    paint = paint or plain
    if u["rating"] in (NOT_RUN, NOT_RATED):
        return u["rating"]
    label = paint(u["rating"])
    if u["runs"] == 1:
        return f"{u['distinct']} distinct ({u['calls']} call{'' if u['calls'] == 1 else 's'}) → {label}"
    of = f"worst of {u['runs']}" if u["rated"] == u["runs"] else f"worst of {u['rated']} rated, {u['runs']} runs"
    tools = f"{_span(u['minDistinct'], u['distinct'])} tool{'' if u['distinct'] == 1 else 's'}"
    calls = f"{_span(u['minCalls'], u['calls'])} call{'' if u['calls'] == 1 else 's'}"
    return f"{tools} ({calls}) → {label} ({of})"


def tally(results):
    """{rating: [case ids]} over CaseResults, every rating present, in RANK order."""
    out = {label: [] for label in RANK}
    for c in results:
        out.setdefault(c.usage["rating"], []).append(c.case.id)
    return out


def summary_lines(results, paint=None):
    paint = paint or plain
    lines = ["MCP tool usage"]
    for label, ids in tally(results).items():
        if label in (NOT_RUN, NOT_RATED) and not ids:
            continue
        named = f"  ({', '.join(ids)})" if ids and label in FLAGGED + (NOT_RATED,) else ""
        lines.append(f"  {paint(label, f'{label}:'.ljust(14))}{len(ids):>3}{named}")
    return lines


def summary_line(results, paint=None):
    """'MCP tool usage: Best 10 · Good 8 · Concerning 2 (R08, R17) · Risky 0 · No MCP tools 0'."""
    paint = paint or plain
    parts = []
    for label, ids in tally(results).items():
        if label in (NOT_RUN, NOT_RATED) and not ids:
            continue
        named = f" ({', '.join(ids)})" if ids and label in FLAGGED + (NOT_RATED,) else ""
        parts.append(f"{paint(label, f'{label} {len(ids)}')}{named}")
    return "MCP tool usage: " + " · ".join(parts)


# --- colour ---

def plain(label, text=None):
    return label if text is None else text


def painter(stream=None):
    """A paint(label, text=None) that colours by rating when `stream` is a terminal that shows
    colour, and returns the text unchanged otherwise (files, pipes, NO_COLOR)."""
    stream = stream or sys.stdout
    if not colour_supported(stream):
        return plain

    def paint(label, text=None):
        code = COLOURS.get(label)
        text = label if text is None else text
        return f"\033[{code}m{text}\033[0m" if code else text
    return paint


def colour_supported(stream):
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return _windows_vt() if os.name == "nt" else True


def _windows_vt():
    """Turn on ANSI colour in the Windows console (PowerShell, cmd, VS Code). False if it can't."""
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        return False
