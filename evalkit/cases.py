"""Case files: one YAML file per case, written by QA. The format is in cases/_template.yaml."""
import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
KEYS = {"id", "title", "tags", "start_state", "admin_says", "expect", "pass_when", "fail_if",
        "covers", "notes"}
EXPECT_KEYS = {"must_call", "must_not_call", "max_calls"}
START_STATES = ("eval-empty", "eval-half-built", "eval-ready")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class CaseError(ValueError):
    """One or more case files are malformed. The message lists every problem."""


@dataclass(frozen=True)
class Case:
    id: str
    title: str
    path: Path
    admin_says: tuple
    pass_when: str | None = None
    fail_if: str | None = None
    must_call: tuple = ()
    must_not_call: tuple = ()
    max_calls: dict = field(default_factory=dict)
    covers: tuple = ()
    tags: tuple = ()
    start_state: str | None = None
    notes: str | None = None

    @property
    def needs_writes(self):
        return self.start_state is not None

    @property
    def tools(self):
        """The tools this case tests, for the coverage report."""
        return set(self.covers) | set(self.must_call) | set(self.max_calls)

    @property
    def judged(self):
        return bool(self.pass_when or self.fail_if)


def _suggest(key, known):
    close = difflib.get_close_matches(key, sorted(known), n=1)
    return f" (did you mean {close[0]}?)" if close else ""


def _names(value, where, problems):
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        problems.append(f"{where} must be a tool name or a list of tool names")
        return ()
    return tuple(v.strip() for v in value)


def load_case(path):
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise CaseError(f"{path.name}: not valid YAML: {e}") from None
    if not isinstance(raw, dict):
        raise CaseError(f"{path.name}: expected keys such as id, title and admin_says")
    p = []
    for key in sorted(set(raw) - KEYS):
        p.append(f"unknown key {key!r}{_suggest(key, KEYS)}")

    cid = raw.get("id")
    if not isinstance(cid, str) or not ID.match(cid):
        p.append("id is required: letters, digits, '-', '_' or '.', e.g. A05")
        cid = str(cid)
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        p.append("title is required")

    says = raw.get("admin_says")
    if isinstance(says, str):
        says = [says]
    if not isinstance(says, list) or not says or not all(isinstance(s, str) and s.strip() for s in says):
        p.append("admin_says is required: what the admin says, or a list of messages in order")
        says = []

    start = raw.get("start_state")
    if start is not None and start not in START_STATES:
        p.append(f"start_state must be one of {', '.join(START_STATES)}, not {start!r}")
    if start is None and any("{program}" in s for s in says):
        p.append("{program} in admin_says needs a start_state: it is that program's name")

    expect = raw.get("expect") or {}
    if not isinstance(expect, dict):
        p.append("expect must hold must_call, must_not_call and/or max_calls")
        expect = {}
    for key in sorted(set(expect) - EXPECT_KEYS):
        p.append(f"unknown key expect.{key}{_suggest(key, EXPECT_KEYS)}")
    must_call = _names(expect.get("must_call"), "expect.must_call", p)
    must_not_call = _names(expect.get("must_not_call"), "expect.must_not_call", p)
    max_calls = expect.get("max_calls") or {}
    if not isinstance(max_calls, dict) or not all(
            isinstance(k, str) and isinstance(v, int) and v >= 0 for k, v in max_calls.items()):
        p.append("expect.max_calls maps a tool name to the most times it may be called, e.g. set_videos: 1")
        max_calls = {}
    both = set(must_call) & set(must_not_call)
    if both:
        p.append(f"{', '.join(sorted(both))} is in both must_call and must_not_call")

    for key in ("pass_when", "fail_if", "notes"):
        if raw.get(key) is not None and not isinstance(raw[key], str):
            p.append(f"{key} must be text")
    if not (raw.get("pass_when") or raw.get("fail_if") or must_call or must_not_call or max_calls):
        p.append("nothing to grade: add pass_when / fail_if, or expect")

    covers = _names(raw.get("covers"), "covers", p)
    tags = _names(raw.get("tags"), "tags", p)
    if p:
        raise CaseError(f"{path.name}:\n  - " + "\n  - ".join(p))
    return Case(id=cid, title=title.strip(), path=path, admin_says=tuple(s.strip() for s in says),
                pass_when=raw.get("pass_when"), fail_if=raw.get("fail_if"),
                must_call=must_call, must_not_call=must_not_call, max_calls=dict(max_calls),
                covers=covers, tags=tags, start_state=start, notes=raw.get("notes"))


def load_cases(folder=None, ids=(), tags=()):
    """Every case under `folder` (files starting with _ are skipped), sorted by id.
    `ids` and `tags` narrow the set; an id that matches nothing is an error."""
    folder = Path(folder or ROOT / "cases")
    cases, errors = [], []
    for path in sorted(folder.rglob("*.y*ml")):
        if path.name.startswith("_") or path.suffix not in (".yaml", ".yml"):
            continue
        try:
            cases.append(load_case(path))
        except CaseError as e:
            errors.append(str(e))
    seen = {}
    for c in cases:
        if c.id in seen:
            errors.append(f"{c.path.name}: id {c.id} is also used by {seen[c.id].name}")
        seen.setdefault(c.id, c.path)
    if errors:
        raise CaseError("\n".join(errors))
    missing = [i for i in ids if i not in seen]
    if missing:
        raise CaseError(f"no case with id {', '.join(missing)}")
    if ids:
        cases = [c for c in cases if c.id in ids]
    if tags:
        cases = [c for c in cases if set(tags) & set(c.tags)]
    return sorted(cases, key=lambda c: c.id)
