"""Agent loop against a scripted fake model and the stub server (no API key needed)."""
from types import SimpleNamespace as NS

from evalkit import agent, connect


class FakeModel:
    """Asks for count(up), then answers with `final`."""

    def __init__(self, final):
        self.final, self.turn = final, 0
        self.messages = self

    async def create(self, **kw):
        self.turn += 1
        usage = NS(input_tokens=10, output_tokens=5)
        if self.turn % 2 == 1:
            return NS(content=[NS(type="tool_use", id="t1", name="execute_query",
                                  input={"query": "count(up)"})], usage=usage)
        return NS(content=[NS(type="text", text=self.final)], usage=usage)


def check(answer, calls, results):
    assert "12" in answer, "total missing"


async def test_passing_runs_give_pass_hat_k(stub_url, tmp_path):
    mcp = await connect("prometheus-main", mode="live", url=stub_url, fixtures_dir=tmp_path)
    rep = await agent.run(mcp, "how many targets?", check, model="m", k=2, client=FakeModel("12 targets"))
    assert rep.pass_hat_k and rep.pass_rate == 1.0
    assert rep.runs[0].calls == [("execute_query", {"query": "count(up)"})]
    assert rep.runs[0].tokens == 30


async def test_failing_check_is_recorded_not_raised(stub_url, tmp_path):
    mcp = await connect("prometheus-main", mode="live", url=stub_url, fixtures_dir=tmp_path)
    rep = await agent.run(mcp, "how many targets?", check, model="m", k=1, client=FakeModel("I don't know"))
    assert not rep.pass_hat_k
    assert rep.runs[0].error == "total missing"
