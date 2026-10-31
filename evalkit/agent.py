"""Layer 3: run a case with a model connected to the MCP session, k times, graded by the case's check()."""
from dataclasses import dataclass, field


@dataclass
class Run:
    answer: str
    calls: list
    passed: bool
    error: str | None
    tokens: int
    off_recording: int


@dataclass
class Report:
    runs: list = field(default_factory=list)

    @property
    def pass_hat_k(self):
        return bool(self.runs) and all(r.passed for r in self.runs)

    @property
    def pass_rate(self):
        return sum(r.passed for r in self.runs) / len(self.runs)

    def print_summary(self):
        k = len(self.runs)
        print(f"pass^{k}: {self.pass_hat_k} · pass rate {self.pass_rate:.0%}")
        for i, r in enumerate(self.runs, 1):
            status = "PASS" if r.passed else f"FAIL ({r.error})"
            print(f"  run {i}: {status} · {len(r.calls)} calls · {r.tokens} tokens"
                  + (f" · {r.off_recording} calls not in recording" if r.off_recording else ""))
            print(f"    answer: {r.answer[:200]}")


async def run(session, query, check, model, k=3, max_steps=8, client=None):
    if client is None:
        import anthropic  # optional dependency: pip install -e '.[agent]'
        client = anthropic.AsyncAnthropic()
    tools = [{"name": t["name"], "description": t.get("description", ""), "input_schema": t["inputSchema"]}
             for t in await session.list_tools()]
    report = Report()
    for _ in range(k):
        report.runs.append(await _one(session, client, model, tools, query, check, max_steps))
    return report


async def _one(session, client, model, tools, query, check, max_steps):
    messages = [{"role": "user", "content": query}]
    calls, results, tokens = [], [], 0
    resp = None
    for _ in range(max_steps):
        resp = await client.messages.create(model=model, max_tokens=1024, tools=tools, messages=messages)
        tokens += resp.usage.input_tokens + resp.usage.output_tokens
        messages.append({"role": "assistant", "content": resp.content})
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            break
        outs = []
        for u in uses:
            r = await session.call(u.name, u.input, strict=False)
            calls.append((u.name, u.input))
            results.append(r)
            outs.append({"type": "tool_result", "tool_use_id": u.id, "content": r.text, "is_error": r.is_error})
        messages.append({"role": "user", "content": outs})
    answer = "".join(b.text for b in resp.content if b.type == "text")
    try:
        check(answer, calls, results)
        passed, error = True, None
    except AssertionError as e:
        passed, error = False, (str(e).splitlines() or ["assertion failed"])[0]
    return Run(answer, calls, passed, error, tokens, sum(r.off_recording for r in results))
