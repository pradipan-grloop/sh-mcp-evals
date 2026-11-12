"""One eval run against one environment: spec lint, every case K times, then the report."""
import json
import time
from datetime import datetime
from pathlib import Path

import anthropic

from evalkit import config, console, sources, timing, usage
from evalkit.agent import api_tools, converse, system_prompt
from evalkit.client import AuthError, connect
from evalkit.grade import Verdict, grade
from evalkit.lint import lint_tools
from evalkit.progress import QUIET
from evalkit.report import CaseResult, Report, as_json, markdown, previous_report

RESULTS = config.ROOT / "results"  # every run's report, JSON and transcripts; kept out of git
COVERAGE = config.ROOT / "coverage"  # the latest full run's report per environment; committed
WRITE_SKIP = ("needs write access (start_state {state}); write cases run once `evalkit login` "
              "and the eval programs are in place")
# Failures that would fail every run the same way: stop the run instead of recording each one.
FATAL = (AuthError, anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError)


async def run(env, token, settings, cases, *, client, judge_fn, full=True, skills=(),
              results_root=None, coverage_dir=None, log=print, progress=None, paint=None,
              detail=False, with_sources=True):
    """Returns (report, path to report.md). `judge_fn(case, transcript)` -> (passed, reason)."""
    started = datetime.now().astimezone()
    results_root = Path(results_root or RESULTS)
    base = f"{started:%Y-%m-%d_%H%M%S}"
    run_id, n = f"{base}_{env.name}", 1
    while (results_root / run_id).exists():  # two runs in the same second; the suffix keeps ids in order
        n += 1
        run_id = f"{base}_{env.name}_{n}"
    out = results_root / run_id
    (out / "transcripts").mkdir(parents=True)

    session = await connect(env.name, "live", url=env.url, token=token)
    try:
        listed = await session.list_tools()
        tools = api_tools(listed)
        system = system_prompt(session.instructions, skills)
        info = session.server_info
        log(f"{env.name}: {info.get('name', 'server')} {info.get('version', '')} · {len(listed)} tools · "
            f"{len(cases)} cases · K={settings.k}")
        results = [await _run_case(c, session, client, judge_fn, settings, system, tools, out, log,
                                   progress or QUIET, paint, detail, with_sources)
                   for c in cases]
    finally:
        await session.close()

    rep = Report(env=env.name, url=env.url, run_id=run_id, started=f"{started:%Y-%m-%d %H:%M}",
                 finished=f"{datetime.now().astimezone():%Y-%m-%d %H:%M}", evalkit=config.evalkit_version(),
                 server=dict(info), settings=settings, tools=listed, lint=lint_tools(listed),
                 cases=results, full=full,
                 write_tools=frozenset(t["name"] for t in listed if session.is_write(t["name"])))
    rep.previous = previous_report(results_root, env.name, run_id)
    md = markdown(rep)
    (out / "report.md").write_text(md, encoding="utf-8")
    _write_json(out / "report.json", as_json(rep))
    if full:
        coverage_dir = Path(coverage_dir or COVERAGE)
        coverage_dir.mkdir(parents=True, exist_ok=True)
        (coverage_dir / f"{env.name}.md").write_text(md, encoding="utf-8")
    return rep, out / "report.md"


async def _run_case(case, session, client, judge_fn, settings, system, tools, out, log, progress=QUIET,
                    paint=None, detail=False, with_sources=True):
    if case.needs_writes:
        result = CaseResult(case, skipped=WRITE_SKIP.format(state=case.start_state))
        _log_case(result, log, paint, detail)
        return result
    result = CaseResult(case)
    for i in range(1, settings.k + 1):
        transcript, judged = None, None
        progress.start(f"{case.id} run {i}/{settings.k}", settings.max_steps)
        started = time.perf_counter()
        try:
            transcript = await converse(session, client, settings, system, tools, case.admin_says,
                                        progress=progress)
            progress.judging()
            judged = time.perf_counter()
            verdict = await grade(case, transcript, session, judge_fn)
        except FATAL:
            raise
        except Exception as e:  # an API or network failure in one run: record it and go on
            verdict = Verdict(False, f"run error: {type(e).__name__}: {e}")
        finally:
            progress.stop()
        ended = time.perf_counter()
        took = timing.of_run(transcript, (ended - started) * 1000, (ended - judged) * 1000 if judged else 0)
        found = None
        if with_sources and transcript is not None:  # after the clock stops: not part of the test's time
            progress.start(f"{case.id} run {i}/{settings.k}", settings.max_steps)
            progress.extracting()
            try:
                found = await sources.collect(client if settings.sources_model else None, settings, transcript)
            finally:
                progress.stop()
        name = f"{case.id}_run{i}.json"
        result.runs.append(_run_record(transcript, verdict, f"transcripts/{name}", took, found))
        _write_json(out / "transcripts" / name,
                    {"case": case.id, "title": case.title, "run": i, "pass": verdict.passed,
                     "reason": verdict.reason, **(transcript.to_json() if transcript else {}),
                     "mcpUsage": usage.of_transcript(transcript), "timing": took, "sources": found})
        if detail:
            status = "PASS" if verdict.passed else f"FAIL · {verdict.reason}"
            log(f"  {case.id} run {i}/{settings.k}: {status} · {timing.fmt(took['totalMs'])}")
    _log_case(result, log, paint, detail)
    return result


def _log_case(result, log, paint, detail):
    """The case's result, MCP tool rating and time. Rating and time are informational only."""
    for line in console.case_block(result, paint, detail):
        log(line)


def _run_record(t, v, transcript_path, took=None, found=None):
    """One run, in the shape mcp-evals.md ("Recording a run") uses, plus what the report needs."""
    return {"pass": v.passed, "notes": v.reason, "critical": v.critical,
            "toolCalls": [name for name, _ in t.calls] if t else [],
            "codes": t.codes if t else [], "responseChars": t.response_chars if t else 0,
            "tokens": t.tokens if t else 0, "fallbacks": sorted(t.fallbacks) if t else [],
            "transcript": transcript_path, "mcpUsage": usage.of_transcript(t), "timing": took,
            "sources": found}


def _write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
