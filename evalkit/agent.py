"""Runs one conversation: the admin's messages in order, Claude calling the server's tools
until it answers each one. Returns the transcript for grading."""
import json
import time
from dataclasses import dataclass, field

from evalkit.client import Result
from evalkit.guard import why_blocked
from evalkit.progress import QUIET

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000
PREAMBLE = ("You are Claude, connected to Stitched Health's MCP server and talking with a "
            "Stitched Health admin. The server's own instructions follow.")


def system_prompt(instructions, skills=()):
    """What a host such as claude.ai gives Claude: the server's instructions, plus any
    Stitched Health skill text from skills/*.md."""
    parts = [PREAMBLE]
    if instructions:
        parts.append(f"<server_instructions>\n{instructions}\n</server_instructions>")
    parts += [s for s in skills if s]
    return "\n\n".join(parts)


def api_tools(listed):
    """tools/list entries as Claude API tool definitions."""
    out = []
    for t in listed:
        schema = dict(t.get("inputSchema") or {"type": "object", "properties": {}})
        schema.pop("$schema", None)
        out.append({"name": t["name"], "description": t.get("description") or "", "input_schema": schema})
    return out


@dataclass
class Transcript:
    events: list = field(default_factory=list)  # admin / claude / tool, in order
    usage: dict = field(default_factory=lambda: {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0})
    model_calls: int = 0
    fallbacks: set = field(default_factory=set)  # models that answered after the requested one declined
    error: str | None = None  # why the conversation stopped early, if it did
    claude_ms: float = 0  # time spent waiting on Claude's model calls; tool calls carry their own `ms`

    def _tool_events(self):
        return [e for e in self.events if e["kind"] == "tool"]

    @property
    def calls(self):
        """Every call Claude made, blocked ones included, as (name, args)."""
        return [(e["tool"], e["args"]) for e in self._tool_events()]

    @property
    def blocked(self):
        return [e for e in self._tool_events() if e["blocked"]]

    @property
    def codes(self):
        return [e["code"] for e in self._tool_events() if e["code"]]

    @property
    def response_chars(self):
        return sum(e["chars"] for e in self._tool_events())

    @property
    def tokens(self):
        return sum(self.usage.values())

    @property
    def answer(self):
        said = [e["text"] for e in self.events if e["kind"] == "claude"]
        return said[-1] if said else ""

    def to_json(self):
        return {"events": self.events, "usage": self.usage, "modelCalls": self.model_calls,
                "fallbacks": sorted(self.fallbacks), "error": self.error, "claudeMs": round(self.claude_ms)}


async def converse(session, client, settings, system, tools, admin_says, progress=None):
    """One run of a case. Never raises for something Claude or the server did; an API or
    network failure propagates for the runner to record."""
    t = Transcript()
    messages = []
    progress = progress or QUIET
    for said in admin_says:
        t.events.append({"kind": "admin", "text": said})
        messages.append({"role": "user", "content": said})
        if not await _answer(session, client, settings, system, tools, messages, t, progress):
            break
    return t


async def _answer(session, client, settings, system, tools, messages, t, progress=QUIET):
    """Let Claude work until it replies to the admin. False if it could not."""
    for step in range(1, settings.max_steps + 1):
        progress.step(step)
        started = time.perf_counter()
        resp = await client.beta.messages.create(
            model=settings.model, max_tokens=MAX_TOKENS, system=system, tools=tools,
            messages=messages, output_config={"effort": settings.effort},
            cache_control={"type": "ephemeral"}, betas=[FALLBACK_BETA], fallbacks="default")
        t.claude_ms += (time.perf_counter() - started) * 1000
        t.model_calls += 1
        _add_usage(t, resp)
        messages.append({"role": "assistant", "content": _echoable(resp.content)})
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if text:
            t.events.append({"kind": "claude", "text": text})
        if resp.stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            t.error = f"Claude declined (category: {getattr(details, 'category', None)})"
            return False
        if resp.stop_reason == "max_tokens":
            t.error = f"Claude's reply was cut off at {MAX_TOKENS} tokens"
            return False
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            return True
        results = []
        for u in uses:
            progress.tool(u.name)
            started = time.perf_counter()
            r = await _call(session, u.name, u.input)
            ms = round((time.perf_counter() - started) * 1000)
            t.events.append({"kind": "tool", "tool": u.name, "args": u.input, "is_error": r.is_error,
                             "code": r.code, "blocked": r.blocked, "chars": len(r.text), "result": r.text,
                             "ms": ms})
            results.append({"type": "tool_result", "tool_use_id": u.id,
                            "content": r.text or "(empty result)", "is_error": r.is_error})
        messages.append({"role": "user", "content": results})
    t.error = f"no reply to the admin within {settings.max_steps} model calls"
    return False


async def _call(session, name, args):
    why = why_blocked(session, name)
    if why:
        return Result(text=f"Blocked by evalkit: {why}.", is_error=True, blocked=True)
    return await session.call(name, args, strict=False)


def _add_usage(t, resp):
    u = resp.usage
    t.usage["input"] += getattr(u, "input_tokens", 0) or 0
    t.usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
    t.usage["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
    t.usage["output"] += getattr(u, "output_tokens", 0) or 0
    if any(getattr(i, "type", None) == "fallback_message" for i in getattr(u, "iterations", None) or []):
        t.fallbacks.add(getattr(resp, "model", "unknown"))


def _echoable(content):
    """The reply as it must be sent back. After a fallback, model-internal blocks from before
    the last switch point are dropped, as the fallback docs require; text is kept."""
    marks = [i for i, b in enumerate(content) if b.type == "fallback"]
    if not marks:
        return content
    cut = marks[-1]
    internal = {"thinking", "redacted_thinking", "tool_use"}
    return [b for i, b in enumerate(content) if i >= cut or b.type not in internal]


def render(t, limit=4000):
    """The transcript as plain text for the judge. Long tool results are cut, and say so."""
    lines = []
    for e in t.events:
        if e["kind"] == "admin":
            lines.append(f"ADMIN: {e['text']}")
        elif e["kind"] == "claude":
            lines.append(f"CLAUDE: {e['text']}")
        else:
            lines.append(f"TOOL CALL {e['tool']} {json.dumps(e['args'], ensure_ascii=False)}")
            label = "BLOCKED" if e["blocked"] else ("REFUSED" if e["is_error"] else "RESULT")
            if e["code"]:
                label += f" ({e['code']})"
            body = e["result"]
            if len(body) > limit:
                body = body[:limit] + f" [... {len(body) - limit} more characters cut]"
            lines.append(f"{label}: {body}")
    if t.error:
        lines.append(f"(the run stopped early: {t.error})")
    return "\n".join(lines)
