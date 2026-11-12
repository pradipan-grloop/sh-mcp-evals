"""Which EPs and case studies a run's answer came from, with the numbers the answer gives for
them, so a reader can see at a glance what was counted and where.

Names always come from the MCP tool results in the transcript, never from Claude. Numbers come
from Claude's final answer: one small extraction call (settings.sources_model) reads the answer
and fills a fixed schema. Before anything is shown, every number is checked to appear in the
answer and every EP to appear in the tool results; anything else is dropped. When the
extraction fails, the names are still shown, without numbers. Informational only: never part
of the result.
"""
import json
import re
import shutil

from evalkit.judge import JudgeError

MAX_TOKENS = 4000
EP_ARG_KEYS = ("programId", "epId", "therapeuticProgramId")
PROGRAM_TOOLS = ("list_programs", "get_program", "get_program_readiness")
EP_CODE = re.compile(r"^EP-\d+$")

SYSTEM = """You read one answer that Claude gave a Stitched Health admin and pull out, into the \
schema, the numbers it reports per educational program (EP) and per case study.

Rules:
- Use only numbers written in the answer. Never add, subtract or work anything out.
- Name EPs by their code from the index (for example EP-646). Leave out EPs not in the index.
- Name case studies by their title exactly as the index lists it under that EP.
- When the answer gives no number for an EP or a case study, use null.
- measure says in a few plain words what the per-EP numbers count, for example "case studies \
completed" or "learners".
- headline is the answer's main result in one short sentence of at most 12 words, using only \
numbers from the answer. Empty string if there is none."""

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "measure": {"type": "string"},
        "eps": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "ep": {"type": "string"},
                "count": {"type": ["number", "null"]},
                "case_studies": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}, "count": {"type": ["number", "null"]}},
                    "required": ["title", "count"], "additionalProperties": False}},
            },
            "required": ["ep", "count", "case_studies"], "additionalProperties": False}},
    },
    "required": ["headline", "measure", "eps"],
    "additionalProperties": False,
}


# --- what the tool results say (no model) ---

def index(transcript):
    """{ep id: {"code", "name", "queried", "caseStudies": [titles]}} from the transcript's tool
    calls and results. "queried" means Claude called a tool for that EP."""
    eps = {}

    def ep(pid):
        return eps.setdefault(pid, {"code": "", "name": "", "queried": False, "caseStudies": []})

    for e in (transcript.events if transcript else []):
        if e.get("kind") != "tool":
            continue
        pid = next((e["args"][k] for k in EP_ARG_KEYS if isinstance(e["args"].get(k), str)), None)
        if pid:
            ep(pid)["queried"] = True
        try:
            result = json.loads(e.get("result") or "")
        except ValueError:
            continue
        for d in _dicts(result):
            if "id" in d and "name" in d and (EP_CODE.match(str(d.get("customId", "")))
                                              or e["tool"] in PROGRAM_TOOLS):
                _name(ep(d["id"]), d.get("customId"), d["name"])
            for id_key, name_key in (("epId", "epTitle"), ("epId", "epName")):
                if d.get(id_key) and d.get(name_key):
                    _name(ep(d[id_key]), None, d[name_key])
            title = d.get("title") or d.get("caseStudyName")
            owner = d.get("epId") or pid
            if d.get("caseStudyId") and title and owner:
                _add(ep(owner)["caseStudies"], title)
            elif e["tool"] == "get_case_studies" and d.get("id") and d.get("title") and pid:
                _add(ep(pid)["caseStudies"], d["title"])
    return {pid: v for pid, v in eps.items() if v["name"] or v["queried"]}


def _dicts(value):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from _dicts(v)
    elif isinstance(value, list):
        for v in value:
            yield from _dicts(v)


def _name(entry, code, name):
    if code and not entry["code"]:
        entry["code"] = str(code)
    if name and not entry["name"]:
        entry["name"] = " ".join(str(name).split())


def _add(titles, title):
    title = " ".join(str(title).split())
    if title not in titles:
        titles.append(title)


# --- the numbers in Claude's answer (one small model call) ---

async def extract(client, settings, answer, idx):
    """The schema filled from `answer`, or raises JudgeError when the model gives none."""
    listing = "\n".join(
        f"- {v['code'] or pid}: {v['name']}"
        + "".join(f"\n    - {t}" for t in v["caseStudies"])
        for pid, v in idx.items() if v["code"] or v["name"])
    resp = await client.beta.messages.create(
        model=settings.sources_model, max_tokens=MAX_TOKENS, system=SYSTEM,
        messages=[{"role": "user", "content": f"<index>\n{listing}\n</index>\n\n<answer>\n{answer}\n</answer>"}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}})
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise JudgeError(f"the extraction stopped: {resp.stop_reason}")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        data = json.loads(text)
        if not isinstance(data.get("eps"), list):
            raise ValueError
        return data
    except (ValueError, AttributeError):
        raise JudgeError(f"the extraction was not in the schema: {text[:120]!r}") from None


# --- checked and put together ---

def _numbers(text):
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")}


def _checked(count, said):
    """The count when the answer states it, else None."""
    if isinstance(count, bool) or not isinstance(count, (int, float)):
        return None
    if float(count).is_integer():
        count = int(count)
    return count if str(count) in said else None


def _match(title, titles):
    t = title.casefold().strip()
    for real in titles:
        r = real.casefold()
        if r == t or (len(t) >= 12 and (r.startswith(t) or t.startswith(r))):
            return real
    return None


def build(idx, answer, extracted=None):
    """The sources record for one run. `extracted` is extract()'s result, or None."""
    said = _numbers(answer)
    by_code = {v["code"]: pid for pid, v in idx.items() if v["code"]}
    rows, seen = [], set()
    for item in (extracted or {}).get("eps") or []:
        pid = by_code.get(str(item.get("ep", "")).strip()) or (item.get("ep") if item.get("ep") in idx else None)
        if not pid or pid in seen:
            continue  # not an EP the tools returned: dropped
        seen.add(pid)
        v = idx[pid]
        studies = []
        for cs in item.get("case_studies") or []:
            real = _match(str(cs.get("title", "")), v["caseStudies"])
            if real and real not in [s["title"] for s in studies]:
                studies.append({"title": real, "count": _checked(cs.get("count"), said)})
        rows.append({"id": pid, "code": v["code"], "name": v["name"],
                     "count": _checked(item.get("count"), said), "caseStudies": studies})
    queried = [pid for pid, v in idx.items() if v["queried"]]
    if not rows:  # no extraction: every queried EP the results named case studies for, names only
        rows = [{"id": pid, "code": idx[pid]["code"], "name": idx[pid]["name"], "count": None,
                 "caseStudies": []} for pid in queried if idx[pid]["caseStudies"]]
    for r in rows:
        if not r["caseStudies"]:
            r["caseStudies"] = [{"title": t, "count": None} for t in idx[r["id"]]["caseStudies"]]
    rows = [r for r in rows if r["count"] != 0 or r["caseStudies"]]  # a bare 0 goes under "No results"
    rows.sort(key=lambda r: (-(r["count"] if r["count"] is not None else -1), r["code"] or r["name"]))
    listed = {r["id"] for r in rows}
    headline = str((extracted or {}).get("headline") or "").strip()
    if headline and not _numbers(headline) <= said:
        headline = ""  # a number the answer does not state
    return {"headline": headline or None,
            "measure": str((extracted or {}).get("measure") or "").strip() or None,
            "queried": len(queried), "eps": rows,
            "noResults": [idx[pid]["code"] or idx[pid]["name"] for pid in queried if pid not in listed],
            "numbers": extracted is not None}


async def collect(client, settings, transcript):
    """The sources record for one run, or None when the run touched no EP. Never raises for a
    model problem: without the extraction it falls back to names only."""
    idx = index(transcript)
    if not idx:
        return None
    answer = transcript.answer
    extracted = None
    if client is not None and settings.sources_model and answer:
        try:
            extracted = await extract(client, settings, answer, idx)
        except Exception:  # noqa: BLE001 - informational only: names without numbers
            extracted = None
    return build(idx, answer, extracted)


# --- shown ---

def _cut(text, width):
    return text if len(text) <= width else text[:width - 1].rstrip() + "…"


def lines(s, indent="  ", max_eps=15, max_studies=5):
    """The terminal section: headline, then EPs with their case studies and numbers."""
    if not s:
        return []
    out = []
    if s.get("headline"):
        out.append(f"{indent}Answer:     {s['headline']}")
    if not s["eps"] and not s["noResults"]:
        return out
    head = f"Data from {s['queried']} EP{'' if s['queried'] == 1 else 's'}" if s["queried"] else "Data from"
    if s.get("measure") and any(r["count"] is not None for r in s["eps"]):
        head += f" · numbers = {s['measure']}"
    out.append(f"{indent}{head}:")
    width = max(52, min(90, shutil.get_terminal_size((100, 20)).columns - 16))
    for r in s["eps"][:max_eps]:
        label = f"{r['code'] + '  ' if r['code'] else ''}{_cut(r['name'], width - len(r['code']) - 2)}"
        count = f" {r['count']:>4}" if r["count"] is not None else ""
        out.append(f"{indent}  {label} {'.' * max(2, width + 2 - len(label))}{count}" if count
                   else f"{indent}  {label}")
        studies = r["caseStudies"]
        for cs in studies[:max_studies]:
            name = _cut(cs["title"], width - 4)
            n = f" {cs['count']:>4}" if cs["count"] is not None else ""
            out.append(f"{indent}      · {name} {'.' * max(2, width - 2 - len(name))}{n}" if n
                       else f"{indent}      · {name}")
        if len(studies) > max_studies:
            out.append(f"{indent}      · +{len(studies) - max_studies} more case studies (report.md)")
    if len(s["eps"]) > max_eps:
        out.append(f"{indent}  +{len(s['eps']) - max_eps} more EPs (report.md)")
    if s["noResults"]:
        out.append(f"{indent}  No results ({len(s['noResults'])}): {', '.join(s['noResults'])}")
    return out


def markdown(results):
    """report.md: one section per case that touched an EP, with the full names."""
    out = []
    for c in results:
        s = c.sources
        if not s:
            continue
        out += ["", f"### {c.case.id} · {c.case.title}", ""]
        if s.get("headline"):
            out.append(f"**Answer:** {s['headline']}")
        note = f" Numbers: {s['measure']}." if s.get("measure") and s["numbers"] else ""
        out.append(f"Data from {s['queried']} EPs.{note}" + ("" if s["numbers"] else
                                                             " (Numbers not extracted: names only.)"))
        out.append("")
        for r in s["eps"]:
            count = f" — **{r['count']}**" if r["count"] is not None else ""
            out.append(f"- {r['code'] + ' ' if r['code'] else ''}{r['name']}{count}")
            for cs in r["caseStudies"]:
                out.append(f"  - {cs['title']}" + (f" — {cs['count']}" if cs["count"] is not None else ""))
        if s["noResults"]:
            out += ["", f"No results: {', '.join(s['noResults'])}"]
    return (["## Data from (EPs and case studies)", "",
             "EP and case-study names come from the MCP tool results; numbers come from Claude's answer "
             "and are shown only when the answer states them."] + out) if out else []
