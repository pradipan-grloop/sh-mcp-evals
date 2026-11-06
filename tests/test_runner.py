"""A whole run end to end: stub server, scripted Claude, fixed judge."""
import json

from evalkit import runner
from evalkit.cases import Case
from evalkit.config import Environment
from tests.fakes import FakeClaude, health_reply, settings, verdict

READ_CASE = Case(id="R01", title="Health", path=None, admin_says=("Healthy?",), must_call=("get_health",),
                 pass_when="sums it up")
WRITE_CASE = Case(id="A05", title="Publish", path=None, admin_says=("Publish {program}.",),
                  start_state="eval-half-built", covers=("set_visibility",), pass_when="names rows")


def claude():
    return FakeClaude([health_reply])


async def _run(stub_url, tmp_path, cases, client=None, judge=None, full=True, k=1):
    env = Environment("qa", stub_url)
    return await runner.run(env, None, settings(k=k), cases, client=client or claude(),
                            judge_fn=judge or verdict(), full=full, results_root=tmp_path / "results",
                            coverage_dir=tmp_path / "coverage", log=lambda *a: None)


async def test_a_full_run_writes_the_report_files(stub_url, tmp_path):
    rep, md_path = await _run(stub_url, tmp_path, [READ_CASE, WRITE_CASE], k=2)
    out = md_path.parent
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert data["server"]["version"] == "9.9.9-stub"
    assert {c["id"]: c["status"] for c in data["cases"]} == {"R01": "PASS", "A05": "SKIPPED"}
    r1 = data["cases"][0]["runs"][0]
    assert r1["pass"] and r1["toolCalls"] == ["get_health"] and r1["transcript"] == "transcripts/R01_run1.json"
    assert sorted(p.name for p in (out / "transcripts").iterdir()) == ["R01_run1.json", "R01_run2.json"]
    transcript = json.loads((out / "transcripts" / "R01_run1.json").read_text(encoding="utf-8"))
    assert transcript["events"][1]["tool"] == "get_health"
    assert (tmp_path / "coverage" / "qa.md").read_text(encoding="utf-8") == md_path.read_text(encoding="utf-8")
    assert data["summary"]["cases"] == {"total": 2, "PASS": 1, "FLAKY": 0, "FAIL": 0, "SKIPPED": 1}
    rows = {t["name"]: t["result"] for t in data["tools"]}
    assert rows["get_health"] == "PASS" and rows["set_visibility"] == "SKIPPED"


async def test_a_partial_run_leaves_coverage_alone(stub_url, tmp_path):
    await _run(stub_url, tmp_path, [READ_CASE], full=False)
    assert not (tmp_path / "coverage").exists()


async def test_the_second_run_compares_with_the_first(stub_url, tmp_path):
    first, _ = await _run(stub_url, tmp_path, [READ_CASE])
    second, md_path = await _run(stub_url, tmp_path, [READ_CASE], judge=verdict(False, "invented a number"))
    assert second.run_id > first.run_id
    md = md_path.read_text(encoding="utf-8")
    assert f"Compared with run {first.run_id}." in md and "R01: PASS → FAIL" in md
    assert "| HIGH | Case fails | R01 Health | 0/1 runs passed: invented a number |" in md


async def test_a_broken_run_is_recorded_and_the_rest_go_on(stub_url, tmp_path):
    class Flaky(FakeClaude):
        async def create(self, **kw):
            if not self.requests:
                self.requests.append(kw)
                raise RuntimeError("connection reset")
            return await super().create(**kw)

    rep, _ = await _run(stub_url, tmp_path, [READ_CASE], client=Flaky([health_reply]), k=2)
    runs = rep.cases[0].runs
    assert [r["pass"] for r in runs] == [False, True]
    assert runs[0]["notes"] == "run error: RuntimeError: connection reset"
    assert rep.cases[0].status == "FLAKY"
