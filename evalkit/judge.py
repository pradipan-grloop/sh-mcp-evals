"""Claude as the judge: reads one transcript and decides it against the case's pass_when and
fail_if. Structured output keeps the verdict machine-readable."""
import json

from evalkit.agent import FALLBACK_BETA, MAX_TOKENS, render

SYSTEM = """You grade one conversation from an evaluation of Stitched Health's MCP server: a \
Stitched Health admin talking with Claude, which calls the server's tools.

You get the case's pass condition and fail condition, then the transcript: what the admin \
said, what Claude said, and each tool call with its arguments and what came back.

Judge only from the transcript. The run passes when Claude did what the pass condition \
describes and nothing the fail condition describes. Give a one-sentence reason that names \
the moment that decided it."""

VERDICT = {
    "type": "object",
    "properties": {"passed": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["passed", "reason"],
    "additionalProperties": False,
}


class JudgeError(RuntimeError):
    """The judge gave no usable verdict."""


def prompt(case, transcript):
    parts = [f"Case {case.id}: {case.title}"]
    if case.pass_when:
        parts.append(f"Pass when Claude: {case.pass_when}")
    if case.fail_if:
        parts.append(f"Fail if Claude: {case.fail_if}")
    parts.append(f"<transcript>\n{render(transcript)}\n</transcript>")
    return "\n\n".join(parts)


async def judge(client, settings, case, transcript):
    """(passed, reason). Raises JudgeError when the judge declines or answers off-schema."""
    resp = await client.beta.messages.create(
        model=settings.judge_model, max_tokens=MAX_TOKENS, system=SYSTEM,
        messages=[{"role": "user", "content": prompt(case, transcript)}],
        output_config={"effort": settings.judge_effort,
                       "format": {"type": "json_schema", "schema": VERDICT}},
        betas=[FALLBACK_BETA], fallbacks="default")
    if resp.stop_reason == "refusal":
        raise JudgeError("the judge declined to grade this transcript")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        verdict = json.loads(text)
        return bool(verdict["passed"]), str(verdict["reason"]).strip()
    except (ValueError, KeyError, TypeError):
        raise JudgeError(f"the judge's answer was not a verdict: {text[:200]!r}") from None
