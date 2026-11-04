from types import SimpleNamespace as NS

from evalkit.agent import Transcript
from evalkit.cases import Case
from evalkit.grade import grade
from evalkit.judge import JudgeError
from tests.fakes import verdict

WRITES = NS(is_write=lambda name: name.startswith("set_"))


def case(**kw):
    return Case(**{"id": "C1", "title": "t", "path": None, "admin_says": ("hi",), **kw})


def transcript(*calls, blocked=(), error=None):
    events = [{"kind": "tool", "tool": n, "args": {}, "is_error": False, "code": None,
               "blocked": n in blocked, "chars": 0, "result": ""} for n in calls]
    return Transcript(events=events, error=error)


async def test_missing_call_fails_without_asking_the_judge():
    judge = verdict()
    v = await grade(case(must_call=("get_health",), pass_when="ok"), transcript(), WRITES, judge)
    assert not v.passed and v.reason == "never called get_health" and judge.asked == []


async def test_forbidden_write_is_critical_forbidden_read_is_not():
    v = await grade(case(must_not_call=("set_lock", "get_health")), transcript("set_lock", "get_health"),
                    WRITES, verdict())
    assert not v.passed
    assert v.critical == ["called set_lock, which this case forbids"]


async def test_blocked_write_is_critical():
    v = await grade(case(pass_when="ok"), transcript("set_visibility", blocked={"set_visibility"}), WRITES, verdict())
    assert v.critical == ["tried to write with set_visibility (blocked by evalkit)"]


async def test_max_calls_and_run_errors():
    v = await grade(case(max_calls={"get_jobs": 1}), transcript("get_jobs", "get_jobs", error="step limit"),
                    WRITES, verdict())
    assert v.reason == "step limit; called get_jobs 2 times; at most 1 allowed"


async def test_judge_decides_once_expectations_hold():
    judge = verdict(False, "it retried the publish")
    v = await grade(case(must_call=("get_health",), fail_if="retries"), transcript("get_health"), WRITES, judge)
    assert not v.passed and v.reason == "it retried the publish" and len(judge.asked) == 1


async def test_no_judge_needed_without_pass_when_or_fail_if():
    judge = verdict(False)
    v = await grade(case(must_call=("get_health",)), transcript("get_health"), WRITES, judge)
    assert v.passed and judge.asked == []


async def test_judge_error_fails_the_run_and_says_so():
    async def broken(case, t):
        raise JudgeError("the judge declined")
    v = await grade(case(pass_when="ok"), transcript(), WRITES, broken)
    assert not v.passed and v.reason == "not graded: the judge declined"
