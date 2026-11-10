"""Command line: `evalkit cases`, `evalkit lint --env qa`, `evalkit run --env qa`."""
import argparse
import asyncio
import sys

from evalkit import config, runner, usage
from evalkit.cases import CaseError, load_cases
from evalkit.client import AuthError, connect
from evalkit.judge import judge
from evalkit.lint import lint_tools
from evalkit.progress import Progress
from evalkit.report import SEVERITIES, answers, fails_threshold, table, terminal


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = _parser().parse_args(argv)
    config.load_dotenv()
    try:
        return args.func(args)
    except (config.ConfigError, CaseError, AuthError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


def _parser():
    p = argparse.ArgumentParser(prog="evalkit", description="Evaluate Stitched Health's MCP server.")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("cases", help="check every case file and list the cases (no network)"
                   ).set_defaults(func=cmd_cases)

    lint = sub.add_parser("lint", help="spec lint over the tools an environment lists")
    run = sub.add_parser("run", help="run the cases against an environment and write the report")
    for s in (lint, run):
        s.add_argument("--env", required=True, help="environment from environments.json: qa, staging, ...")
        s.add_argument("--url", help="use this /mcp address instead of the one in environments.json")
    lint.set_defaults(func=cmd_lint)
    run.add_argument("--case", action="append", default=[], metavar="ID", help="only this case (repeatable)")
    run.add_argument("--tag", action="append", default=[], help="only cases with this tag (repeatable)")
    run.add_argument("-k", "--k", type=int, help="runs per case (default: settings.json)")
    run.add_argument("--model", help="model under test (default: settings.json)")
    run.add_argument("--fail-on", default="", metavar="SEVERITIES",
                     help="exit with code 1 if any finding has one of these severities, e.g. HIGH,CRITICAL")
    run.add_argument("--answers", action=argparse.BooleanOptionalAction, default=None,
                     help="print each run's verdict, tools and Claude's answer at the end "
                          "(default: on with --case or --tag, off for a full run)")
    run.set_defaults(func=cmd_run)
    return p


def cmd_cases(args):
    cases = load_cases()
    print(table(["Case", "Title", "Needs", "Tools"], [
        [c.id, c.title, "write" if c.needs_writes else "read", ", ".join(sorted(c.tools)) or "–"]
        for c in cases]))
    print(f"\n{len(cases)} cases, all valid.")
    return 0


def cmd_lint(args):
    env = config.environment(args.env, args.url)
    return asyncio.run(_lint(env))


async def _lint(env):
    session = await connect(env.name, "live", url=env.url, token=env.read_token())
    try:
        tools = await session.list_tools()
    finally:
        await session.close()
    found = lint_tools(tools)
    clean = len(tools) - len({f.tool for f in found if f.severity == "error"})
    print(f"{env.name}: {len(tools)} tools · {clean} clean · "
          f"{sum(f.severity == 'error' for f in found)} errors, {sum(f.severity == 'warning' for f in found)} warnings\n")
    if found:
        print(table(["Tool", "Rule", "Severity", "Detail"],
                    [[f.tool, f.rule, f.severity.upper(), f.message] for f in found]))
    return 0


def cmd_run(args):
    env = config.environment(args.env, args.url)
    s = config.settings(k=args.k, model=args.model)
    if s.k < 1:
        raise config.ConfigError("--k must be at least 1")
    fail_on = [x.strip().upper() for x in args.fail_on.split(",") if x.strip()]
    bad = [x for x in fail_on if x not in SEVERITIES]
    if bad:
        raise config.ConfigError(f"--fail-on takes {', '.join(SEVERITIES)}, not {', '.join(bad)}")
    cases = load_cases(ids=args.case, tags=args.tag)
    token = env.read_token()
    paint = usage.painter(sys.stdout)
    client = None
    if any(not c.needs_writes for c in cases):
        import anthropic
        client = anthropic.AsyncAnthropic()
    rep, path = asyncio.run(runner.run(
        env, token, s, cases, client=client, judge_fn=lambda case, t: judge(client, s, case, t),
        full=not (args.case or args.tag), skills=config.skills(), progress=Progress(), paint=paint))
    print(terminal(rep, path))
    print()
    print("\n".join(usage.summary_lines(rep.cases, paint)))
    show = args.answers if args.answers is not None else bool(args.case or args.tag)
    if show:
        print(answers(path.parent))
        print(f"\nTranscripts: {path.parent / 'transcripts'}")
    return 1 if fail_on and fails_threshold(rep, fail_on) else 0
