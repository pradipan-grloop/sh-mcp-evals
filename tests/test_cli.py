"""The command line, end to end where it matters: errors exit 2 with a fix, a run exits 0 or 1."""
import json

import anthropic
import pytest

from evalkit import cli, runner
from tests.fakes import FakeClaude, health_reply


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setattr(cli.config, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("SH_EVAL_TOKEN_QA_READ", raising=False)


def test_cases_lists_the_repo_cases(capsys):
    assert cli.main(["cases"]) == 0
    out = capsys.readouterr().out
    assert "| A05 |" in out and "write" in out and "cases, all valid." in out


def test_unknown_environment_names_the_fix(capsys):
    assert cli.main(["run", "--env", "nope"]) == 2
    assert "unknown environment 'nope'" in capsys.readouterr().err


def test_missing_token_names_the_variable(capsys):
    assert cli.main(["run", "--env", "qa"]) == 2
    assert "SH_EVAL_TOKEN_QA_READ" in capsys.readouterr().err


def test_bad_fail_on_is_refused(capsys, monkeypatch):
    monkeypatch.setenv("SH_EVAL_TOKEN_QA_READ", "sh_agent_x")
    assert cli.main(["run", "--env", "qa", "--fail-on", "SEVERE"]) == 2
    assert "--fail-on takes CRITICAL, HIGH, MEDIUM, LOW" in capsys.readouterr().err


def _claude(verdict_json):
    def reply(kw):
        if "format" in kw.get("output_config", {}):  # the judge
            return [("text", verdict_json)]
        return health_reply(kw)
    return FakeClaude([reply])


# The stub lists set_visibility and no case covers it: always one HIGH (untested write tool).
@pytest.mark.parametrize("verdict_json, fail_on, code", [
    ('{"passed": true, "reason": "fine"}', "CRITICAL", 0),
    ('{"passed": true, "reason": "fine"}', "HIGH", 1),
    ('{"passed": false, "reason": "invented a figure"}', "HIGH,CRITICAL", 1),
    ('{"passed": false, "reason": "invented a figure"}', "", 0),
])
def test_run_against_a_url_and_exit_code(stub_url, tmp_path, monkeypatch, capsys, verdict_json, fail_on, code):
    monkeypatch.setenv("SH_EVAL_TOKEN_QA_READ", "sh_agent_x")
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda: _claude(verdict_json))
    monkeypatch.setattr(runner, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(runner, "COVERAGE", tmp_path / "coverage")
    args = ["run", "--env", "qa", "--url", stub_url, "--case", "R01", "--k", "1"]
    assert cli.main(args + (["--fail-on", fail_on] if fail_on else [])) == code
    out = capsys.readouterr().out
    assert "| Cases | 1 ·" in out and "Full report:" in out
    data = json.loads(next((tmp_path / "results").glob("*/report.json")).read_text(encoding="utf-8"))
    assert data["url"] == stub_url and data["full"] is False
    assert not (tmp_path / "coverage").exists()  # a --case run never replaces coverage/qa.md
