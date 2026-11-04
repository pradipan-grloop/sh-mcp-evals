from pathlib import Path

import pytest

from evalkit.cases import CaseError, load_case, load_cases

ROOT = Path(__file__).resolve().parent.parent


def write(folder, name, text):
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def test_the_repo_cases_and_template_are_valid():
    cases = load_cases()
    assert {"R01", "A08", "A05"} <= {c.id for c in cases}
    assert load_case(ROOT / "cases" / "_template.yaml").id == "X01"  # the template stays a working case


def test_a_single_message_becomes_a_list(tmp_path):
    c = load_case(write(tmp_path, "c.yaml", "id: R9\ntitle: t\nadmin_says: hi\npass_when: ok\n"))
    assert c.admin_says == ("hi",) and not c.needs_writes and c.judged


def test_tools_for_coverage(tmp_path):
    c = load_case(write(tmp_path, "c.yaml", "id: R9\ntitle: t\nadmin_says: hi\ncovers: [c]\n"
                        "expect: {must_call: [a], must_not_call: [x], max_calls: {b: 1}}\n"))
    assert c.tools == {"a", "b", "c"}


@pytest.mark.parametrize("body, problem", [
    ("id: R9\ntitle: t\nadmin_says: hi\npass_if: ok\n", "unknown key 'pass_if' (did you mean pass_when?)"),
    ("title: t\nadmin_says: hi\npass_when: ok\n", "id is required"),
    ("id: R9\ntitle: t\npass_when: ok\n", "admin_says is required"),
    ("id: R9\ntitle: t\nadmin_says: hi\n", "nothing to grade"),
    ("id: R9\ntitle: t\nadmin_says: hi\npass_when: ok\nstart_state: half\n", "start_state must be one of"),
    ("id: R9\ntitle: t\nadmin_says: Publish {program}\npass_when: ok\n", "{program} in admin_says needs a start_state"),
    ("id: R9\ntitle: t\nadmin_says: hi\nexpect: {must_call: [a], must_not_call: [a]}\n", "a is in both"),
    ("id: R9\ntitle: t\nadmin_says: hi\nexpect: {max_calls: {a: many}}\n", "expect.max_calls maps"),
    ("id: R9\ntitle: t\nadmin_says: hi\nexpect: {must_cal: [a]}\n", "did you mean must_call?"),
    ("id: R9\ntitle: [\n", "not valid YAML"),
])
def test_problems_are_named(tmp_path, body, problem):
    with pytest.raises(CaseError) as e:
        load_case(write(tmp_path, "bad.yaml", body))
    assert problem in str(e.value)


def test_every_problem_in_a_file_is_listed(tmp_path):
    with pytest.raises(CaseError) as e:
        load_case(write(tmp_path, "bad.yaml", "id: R9\nadmin_says: hi\npas_when: ok\n"))
    assert "title is required" in str(e.value) and "pas_when" in str(e.value)


def test_duplicate_ids_and_filters(tmp_path):
    write(tmp_path, "a.yaml", "id: A1\ntitle: t\nadmin_says: hi\npass_when: ok\ntags: [pii]\n")
    write(tmp_path, "b.yml", "id: B1\ntitle: t\nadmin_says: hi\npass_when: ok\n")
    write(tmp_path, "_draft.yaml", "not: a case\n")
    assert [c.id for c in load_cases(tmp_path)] == ["A1", "B1"]
    assert [c.id for c in load_cases(tmp_path, ids=["B1"])] == ["B1"]
    assert [c.id for c in load_cases(tmp_path, tags=["pii"])] == ["A1"]
    with pytest.raises(CaseError, match="no case with id Z9"):
        load_cases(tmp_path, ids=["Z9"])
    write(tmp_path, "c.yaml", "id: A1\ntitle: t\nadmin_says: hi\npass_when: ok\n")
    with pytest.raises(CaseError, match="id A1 is also used by a.yaml"):
        load_cases(tmp_path)
