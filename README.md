# mcp-evals

Notebook-based evaluation for our MCP servers. One notebook = one test case, in the format we
used for the google-agents-colabs task notebooks: header → setup → initial assertion → action
(gold tool calls) → golden answer → final assertion → agent run. Design: the "MCP Tool Evaluation
Notebooks" doc.

## Setup

```bash
uv venv --python 3.12 .venv && uv pip install -e '.[dev,agent]'
```

## Run a case

| Mode | What it does | Needs |
|---|---|---|
| `replay` (default) | Answers every call from `fixtures/<server>/<case>.json` | Nothing: no VPN, no server |
| `record` | Calls the real server and saves the answers as the fixture | VPN; read-only cases only, with a nod first |
| `live` | Calls the real server, saves nothing | VPN |

- **By hand:** open `cases/prometheus/PROM-0001_targets_down.ipynb` in Jupyter, VS Code or Colab
  Enterprise, edit the `parameters` cell, Run All.
- **Headless / CI:**
  `papermill cases/prometheus/PROM-0001_targets_down.ipynb out.ipynb -p MODE replay`
- **Agent run:** set `ANTHROPIC_API_KEY`; the last cell runs the query `K` times with `MODEL`
  and grades each run with the case's own `check()`. Without a key it is skipped.

Server URLs live in `servers.json`. A server that needs auth reads `MCP_TOKEN_<SERVER>` from the
environment (e.g. `MCP_TOKEN_PROMETHEUS_MAIN`). Never put credentials in a notebook.

## Layout

```
evalkit/client.py   connect(server, mode, case) -> session.call(), list_tools(); record/replay
evalkit/lint.py     layer 1 spec lint over tools/list
evalkit/asserts.py  mentions, called, scalar, compare_strings
evalkit/agent.py    layer 3: model + MCP session, k runs, pass^k
cases/<server>/     one notebook per case
fixtures/<server>/  recordings (scrub before commit)
tests/              evalkit tests + the notebook run against a local stand-in server
```

## Tests

`.venv/bin/python -m pytest -q`. The stand-in server in `tests/stub_server.py` is a test double,
not Prometheus: its numbers are made up and never used as fixtures.
