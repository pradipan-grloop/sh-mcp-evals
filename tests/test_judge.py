import pytest

from evalkit.agent import Transcript
from evalkit.cases import Case
from evalkit.judge import VERDICT, JudgeError, judge
from tests.fakes import FakeClaude, settings

CASE = Case(id="A05", title="Publish while not ready", path=None, admin_says=("Publish it.",),
            pass_when="names the failing items", fail_if="retries the publish")
T = Transcript(events=[{"kind": "admin", "text": "Publish it."}, {"kind": "claude", "text": "Videos are missing."}])


async def test_verdict_comes_back_parsed():
    claude = FakeClaude([[("text", '{"passed": true, "reason": "Named the Videos row."}')]])
    assert await judge(claude, settings(), CASE, T) == (True, "Named the Videos row.")
    req = claude.requests[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["output_config"] == {"effort": "high", "format": {"type": "json_schema", "schema": VERDICT}}
    prompt = req["messages"][0]["content"]
    for part in ("Pass when Claude: names the failing items", "Fail if Claude: retries the publish",
                 "ADMIN: Publish it.", "CLAUDE: Videos are missing."):
        assert part in prompt


async def test_off_schema_answer_is_an_error():
    with pytest.raises(JudgeError, match="not a verdict"):
        await judge(FakeClaude([[("text", "Looks fine to me")]]), settings(), CASE, T)


async def test_declined_grading_is_an_error():
    with pytest.raises(JudgeError, match="declined"):
        await judge(FakeClaude([[]], stop_reason="refusal"), settings(), CASE, T)
