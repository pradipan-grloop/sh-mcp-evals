"""Runs the real case notebook end to end: record against the stub, then replay with the stub stopped."""
import json
from pathlib import Path

import papermill as pm

from tests import stub_server

NB = Path(__file__).parent.parent / "cases" / "prometheus" / "PROM-0001_targets_down.ipynb"


def test_case_records_then_replays(tmp_path):
    url, stop = stub_server.start()
    params = {"MODE": "record", "SERVER_URL": url, "FIXTURES_DIR": str(tmp_path), "RUN_AGENT": False}
    pm.execute_notebook(str(NB), str(tmp_path / "rec.ipynb"), parameters=params, kernel_name="python3")
    stop()
    assert (tmp_path / "prometheus-main" / "PROM-0001.json").exists()

    params = {"MODE": "replay", "FIXTURES_DIR": str(tmp_path), "RUN_AGENT": False}
    pm.execute_notebook(str(NB), str(tmp_path / "rep.ipynb"), parameters=params, kernel_name="python3")
    out = json.loads((tmp_path / "rep.ipynb").read_text())
    text = "".join("".join(o.get("text", "")) for c in out["cells"] for o in c.get("outputs", []))
    assert "Final assertion passed" in text
