"""Test doubles for the Claude API. No API key needed."""
from types import SimpleNamespace as NS

from evalkit.config import Settings


def settings(**kw):
    return Settings(**{"k": 1, "max_steps": 5, **kw})


class FakeClaude:
    """Stands in for anthropic.AsyncAnthropic. `script` is a list of replies, each a list of
    ("text", str) / ("tool", name, input) parts, or a callable(kwargs) returning one. The last
    reply repeats once the script runs out. Every request's kwargs are kept in .requests."""

    def __init__(self, script, model="claude-opus-5-5", stop_reason=None, fallback=False):
        self.script, self.model, self.forced_stop, self.fallback = list(script), model, stop_reason, fallback
        self.requests = []
        self.beta = NS(messages=self)

    async def create(self, **kw):
        self.requests.append({**kw, "messages": list(kw.get("messages", []))})  # as sent, not as it grows
        step = self.script[min(len(self.requests) - 1, len(self.script) - 1)]
        if callable(step):
            step = step(kw)
        content = []
        for i, part in enumerate(step):
            if part[0] == "text":
                content.append(NS(type="text", text=part[1]))
            else:
                content.append(NS(type="tool_use", id=f"tu{len(self.requests)}_{i}", name=part[1], input=part[2]))
        stop = self.forced_stop or ("tool_use" if any(b.type == "tool_use" for b in content) else "end_turn")
        iterations = [NS(type="message"), NS(type="fallback_message")] if self.fallback else None
        usage = NS(input_tokens=100, output_tokens=20, cache_read_input_tokens=0,
                   cache_creation_input_tokens=0, iterations=iterations)
        return NS(content=content, stop_reason=stop, usage=usage, model=self.model, stop_details=None)


def health_reply(kw):
    """A FakeClaude step for any number of runs: call get_health when the admin has just
    spoken, answer once the result is back."""
    last = kw["messages"][-1]
    if last["role"] == "user" and isinstance(last["content"], str):
        return [("tool", "get_health", {})]
    return [("text", "All healthy, nothing stuck.")]


def verdict(passed=True, reason="looked right"):
    """A judge_fn that always answers the same and records what it was asked."""
    asked = []

    async def judge_fn(case, transcript):
        asked.append((case.id, transcript))
        return passed, reason

    judge_fn.asked = asked
    return judge_fn
