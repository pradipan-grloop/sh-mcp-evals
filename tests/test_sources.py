"""EP and case-study sources: names from the tool results, numbers only when the answer states
them, a fallback to names when the extraction fails, and never a change to the result."""
import json

from evalkit import runner, sources
from evalkit.agent import Transcript
from evalkit.cases import Case
from evalkit.config import Environment
from tests.fakes import FakeClaude, settings, verdict

P1, P2, P3 = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222",
              "33333333-3333-4333-8333-333333333333")
PROGRAMS = {"programs": [
    {"id": P1, "customId": "EP-646", "name": "Default EP & CS test", "status": "PUBLIC"},
    {"id": P2, "customId": "EP-693", "name": "Translating Adult Women's Migraine Evidence", "status": "PUBLIC"},
    {"id": P3, "customId": "EP-695", "name": "Elevating Multiple Myeloma Care", "status": "PUBLIC"}]}
ANSWER = ("Across the 3 live programs, 36 clinicians completed 43 case studies.\n"
          "| EP-646 Default | 29 | 31 |\n| EP-693 Migraine | 7 | 12 |\nMigraine Recognition: 3 completed.")


def _ledger(pid, *titles):
    return {"programId": pid, "learners": [{"learnerId": "x", "activities": [
        {"kind": "CASE_STUDY", "caseStudyId": f"cs-{i}", "title": t, "completedAt": "2026-10-01"}
        for i, t in enumerate(titles)]}]}


def transcript(answer=ANSWER):
    t = Transcript()
    calls = [("list_programs", {"status": "PUBLIC"}, PROGRAMS),
             ("get_credit_ledger", {"programId": P1}, _ledger(P1, "Managing Grade 3 Adverse Events")),
             ("get_credit_ledger", {"programId": P2}, _ledger(P2, "Migraine Recognition in Hormonal Contexts",
                                                              "Preventive Switch Decisioning")),
             ("get_credit_ledger", {"programId": P3}, _ledger(P3))]
    for name, args, result in calls:
        t.events.append({"kind": "tool", "tool": name, "args": args, "blocked": False, "code": None,
                         "chars": 0, "result": json.dumps(result), "ms": 100})
    t.events.append({"kind": "claude", "text": answer})
    return t


def test_index_names_every_ep_and_case_study_from_the_tool_results():
    idx = sources.index(transcript())
    assert {v["code"]: v["name"] for v in idx.values()} == {
        "EP-646": "Default EP & CS test", "EP-693": "Translating Adult Women's Migraine Evidence",
        "EP-695": "Elevating Multiple Myeloma Care"}
    assert idx[P2]["caseStudies"] == ["Migraine Recognition in Hormonal Contexts", "Preventive Switch Decisioning"]
    assert idx[P2]["queried"] and idx[P3]["caseStudies"] == []


def test_numbers_are_kept_only_when_the_answer_states_them():
    extracted = {"headline": "36 clinicians completed 43 case studies", "measure": "case studies completed",
                 "eps": [{"ep": "EP-646", "count": 31, "case_studies": []},
                         {"ep": "EP-693", "count": 12, "case_studies": [
                             {"title": "Migraine Recognition in Hormonal Contexts", "count": 3},
                             {"title": "Preventive Switch Decisioning", "count": 9}]},  # 9 is not in the answer
                         {"ep": "EP-999", "count": 5, "case_studies": []}]}  # not an EP the tools returned
    s = sources.build(sources.index(transcript()), ANSWER, extracted)
    assert [(r["code"], r["count"]) for r in s["eps"]] == [("EP-646", 31), ("EP-693", 12)]
    assert s["eps"][1]["caseStudies"] == [{"title": "Migraine Recognition in Hormonal Contexts", "count": 3},
                                          {"title": "Preventive Switch Decisioning", "count": None}]
    assert s["eps"][0]["caseStudies"] == [{"title": "Managing Grade 3 Adverse Events", "count": None}]
    assert s["noResults"] == ["EP-695"] and s["queried"] == 3
    assert s["headline"] == "36 clinicians completed 43 case studies"


def test_an_ep_with_a_bare_zero_goes_under_no_results():
    extracted = {"headline": "", "measure": "case studies completed",
                 "eps": [{"ep": "EP-693", "count": 12, "case_studies": []},
                         {"ep": "EP-695", "count": 0, "case_studies": []}]}
    s = sources.build(sources.index(transcript()), ANSWER + " EP-695: 0.", extracted)
    assert [r["code"] for r in s["eps"]] == ["EP-693"] and "EP-695" in s["noResults"]


def test_a_headline_with_a_number_the_answer_lacks_is_dropped():
    s = sources.build(sources.index(transcript()), ANSWER, {"headline": "40 clinicians did it", "measure": "",
                                                            "eps": []})
    assert s["headline"] is None


def test_without_an_extraction_the_names_still_show():
    s = sources.build(sources.index(transcript()), ANSWER, None)
    assert [r["code"] for r in s["eps"]] == ["EP-646", "EP-693"] and all(r["count"] is None for r in s["eps"])
    assert s["numbers"] is False and s["noResults"] == ["EP-695"]
    text = "\n".join(sources.lines(s))
    assert "Data from 3 EPs:" in text and "EP-693  Translating Adult Women's Migraine Evidence" in text
    assert "· Preventive Switch Decisioning" in text and "No results (1): EP-695" in text


def test_lines_show_counts_aligned_and_shorten_long_names():
    extracted = {"headline": "36 clinicians completed 43 case studies", "measure": "case studies completed",
                 "eps": [{"ep": "EP-693", "count": 12, "case_studies": [
                     {"title": "Migraine Recognition in Hormonal Contexts", "count": 3}]},
                         {"ep": "EP-646", "count": 31, "case_studies": []}]}
    out = sources.lines(sources.build(sources.index(transcript()), ANSWER, extracted))
    assert out[0] == "  Answer:     36 clinicians completed 43 case studies"
    assert out[1] == "  Data from 3 EPs · numbers = case studies completed:"
    assert out[2].startswith("    EP-646  Default EP & CS test ..") and out[2].endswith("  31")
    assert out[4].startswith("    EP-693  ") and out[4].endswith("  12")
    assert len({len(line) for line in (out[2], out[4])}) == 1  # the counts line up


def test_a_run_that_touched_no_ep_has_no_sources():
    t = Transcript()
    t.events.append({"kind": "tool", "tool": "get_health", "args": {}, "blocked": False, "code": None,
                     "chars": 0, "result": '{"api": "ok"}', "ms": 5})
    assert sources.index(t) == {} and sources.lines(None) == []


# --- the extraction call, end to end ---

class Extracting(FakeClaude):
    """Answers the extraction call (it asks for a JSON schema) with `extracted`; otherwise acts
    as the scripted conversation."""
    def __init__(self, script, extracted):
        super().__init__(script)
        self.extracted = extracted

    async def create(self, **kw):
        if "format" in kw.get("output_config", {}):
            self.requests.append(kw)
            from types import SimpleNamespace as NS
            text = self.extracted if isinstance(self.extracted, str) else json.dumps(self.extracted)
            return NS(content=[NS(type="text", text=text)], stop_reason="end_turn")
        return await super().create(**kw)


async def test_collect_asks_the_sources_model_and_falls_back_on_bad_output():
    good = {"headline": "36 clinicians completed 43 case studies", "measure": "case studies completed",
            "eps": [{"ep": "EP-693", "count": 12, "case_studies": []}]}
    client = Extracting([], good)
    s = await sources.collect(client, settings(), transcript())
    asked = client.requests[-1]
    assert asked["model"] == "claude-haiku-5-5" and asked["output_config"]["effort"] == "low"
    assert "fallbacks" not in asked  # Haiku 5.5 has no server-side refusal fallback
    assert s["eps"][0]["count"] == 12 and s["numbers"] is True
    broken = await sources.collect(Extracting([], "not json"), settings(), transcript())
    assert broken["numbers"] is False and [r["code"] for r in broken["eps"]] == ["EP-646", "EP-693"]
    off = await sources.collect(Extracting([], good), settings(sources_model=""), transcript())
    assert off["numbers"] is False  # turned off: names only, no call


def _program_calls(kw):
    last = kw["messages"][-1]
    if last["role"] == "user" and isinstance(last["content"], str):
        return [("tool", "list_programs", {})]
    return [("text", "Stub AFib has 4 learners.")]


async def _run(stub_url, tmp_path, client, judge=None, with_sources=True):
    case = Case(id="R92", title="Sources check", path=None, admin_says=("Which programs?",), pass_when="ok")
    lines = []
    rep, md_path = await runner.run(Environment("qa", stub_url), None, settings(), [case], client=client,
                                    judge_fn=judge or verdict(), full=False, results_root=tmp_path / "results",
                                    coverage_dir=tmp_path / "coverage", log=lines.append,
                                    with_sources=with_sources)
    return rep, md_path, lines


async def test_a_run_shows_and_saves_its_sources(stub_url, tmp_path):
    extracted = {"headline": "Stub AFib has 4 learners", "measure": "learners",
                 "eps": [{"ep": "p-1", "count": 4, "case_studies": []}]}
    rep, md_path, lines = await _run(stub_url, tmp_path, Extracting([_program_calls], extracted))
    s = rep.cases[0].sources
    assert s["headline"] == "Stub AFib has 4 learners" and s["eps"][0]["name"] == "Stub AFib"
    assert "  Answer:     Stub AFib has 4 learners" in lines
    assert any(line.startswith("    Stub AFib ..") and line.endswith("   4") for line in lines)
    data = json.loads((md_path.parent / "report.json").read_text(encoding="utf-8"))
    assert data["cases"][0]["sources"]["eps"][0]["count"] == 4
    transcript_json = json.loads((md_path.parent / "transcripts" / "R92_run1.json").read_text(encoding="utf-8"))
    assert transcript_json["sources"]["headline"] == "Stub AFib has 4 learners"
    assert "## Data from (EPs and case studies)" in md_path.read_text(encoding="utf-8")


async def test_sources_never_change_the_result_and_can_be_turned_off(stub_url, tmp_path):
    extracted = {"headline": "", "measure": "", "eps": []}
    passing, _, _ = await _run(stub_url, tmp_path / "a", Extracting([_program_calls], extracted))
    failing, _, _ = await _run(stub_url, tmp_path / "b", Extracting([_program_calls], extracted),
                               judge=verdict(False, "made it up"))
    assert passing.cases[0].status == "PASS" and failing.cases[0].status == "FAIL"
    client = Extracting([_program_calls], extracted)
    off, _, lines = await _run(stub_url, tmp_path / "c", client, with_sources=False)
    assert off.cases[0].sources is None and not any("Data from" in line for line in lines)
    assert not any("format" in r.get("output_config", {}) for r in client.requests)  # no extra call
