"""MCP client with three modes: live, record (live + save a cassette) and replay (cassette only)."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL = "2025-06-18"


class CassetteMiss(LookupError):
    """A replayed call that was never recorded."""


@dataclass
class Result:
    text: str
    is_error: bool
    data: object = None
    off_recording: bool = False

    @property
    def ok(self):
        return not self.is_error


def _key(name, args):
    return f"{name} {json.dumps(args, sort_keys=True)}"


def _to_result(raw):
    text = "".join(c.get("text", "") for c in raw.get("content", []) if c.get("type") == "text")
    data = raw.get("structuredContent")
    if data is None:
        try:
            data = json.loads(text)
        except ValueError:
            data = None
    return Result(text=text, is_error=bool(raw.get("isError")), data=data)


def _server_url(server, servers_file):
    servers = json.loads(Path(servers_file).read_text())
    if server not in servers:
        raise KeyError(f"{server!r} is not in {servers_file}; known: {sorted(servers)}")
    return servers[server]["url"]


@dataclass
class Session:
    server: str
    mode: str
    cassette_path: Path | None
    url: str | None = None
    calls: list = field(default_factory=list)
    _http: httpx.AsyncClient | None = None
    _sid: str | None = None
    _next_id: int = 0
    _cassette: dict = field(default_factory=lambda: {"tools": None, "calls": []})

    # --- transport (live and record) ---
    async def _rpc(self, method, params=None):
        self._next_id += 1
        msg = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            msg["params"] = params
        resp = await self._http.post(self.url, json=msg, headers=self._headers())
        resp.raise_for_status()
        self._sid = resp.headers.get("mcp-session-id", self._sid)
        body = _parse_body(resp, self._next_id)
        if "error" in body:
            raise RuntimeError(f"{method} failed: {body['error']}")
        return body["result"]

    def _headers(self):
        h = {"Accept": "application/json, text/event-stream"}
        if self._sid:
            h["mcp-session-id"] = self._sid
        token = os.environ.get(f"MCP_TOKEN_{self.server.upper().replace('-', '_')}")
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    async def _open(self):
        self._http = httpx.AsyncClient(timeout=30)
        await self._rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                       "clientInfo": {"name": "evalkit", "version": "0.1"}})
        await self._http.post(self.url, json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                              headers=self._headers())

    # --- public API ---
    async def list_tools(self):
        if self.mode == "replay":
            return self._cassette["tools"] or []
        tools = (await self._rpc("tools/list"))["tools"]
        if self.mode == "record":
            self._cassette["tools"] = tools
            self._save()
        return tools

    async def call(self, name, args=None, strict=True):
        """Call a tool. In replay, an unrecorded call raises CassetteMiss, or with strict=False
        comes back as an error result marked off_recording (what an agent run needs)."""
        args = args or {}
        self.calls.append((name, args))
        if self.mode == "replay":
            for c in self._cassette["calls"]:
                if _key(c["name"], c["args"]) == _key(name, args):
                    return _to_result(c["result"])
            if strict:
                raise CassetteMiss(f"not in {self.cassette_path}: {_key(name, args)}")
            return Result(text=f"call not in recording: {_key(name, args)}", is_error=True, off_recording=True)
        raw = await self._rpc("tools/call", {"name": name, "arguments": args})
        if self.mode == "record":
            self._cassette["calls"].append({"name": name, "args": args, "result": raw})
            self._save()
        return _to_result(raw)

    async def close(self):
        if self._http:
            await self._http.aclose()

    def _save(self):
        self.cassette_path.parent.mkdir(parents=True, exist_ok=True)
        self.cassette_path.write_text(json.dumps(self._cassette, indent=2) + "\n")


def _parse_body(resp, want_id):
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                msg = json.loads(line[5:].strip())
                if msg.get("id") == want_id:
                    return msg
        raise RuntimeError(f"no response with id {want_id} in event stream")
    return resp.json()


async def connect(server, mode="replay", case=None, url=None, fixtures_dir=None, servers_file=None):
    """Open a session. mode: live | record | replay. Credentials, if any, come from
    MCP_TOKEN_<SERVER> in the environment, never from the notebook."""
    if mode not in ("live", "record", "replay"):
        raise ValueError(f"mode must be live, record or replay, not {mode!r}")
    fixtures_dir = Path(fixtures_dir or ROOT / "fixtures")
    cassette = fixtures_dir / server / f"{case}.json" if case else None
    if mode in ("record", "replay") and cassette is None:
        raise ValueError(f"mode {mode!r} needs a case id")
    s = Session(server=server, mode=mode, cassette_path=cassette)
    if mode == "replay":
        if not cassette.exists():
            raise FileNotFoundError(f"no recording at {cassette}; run once with MODE='record'")
        s._cassette = json.loads(cassette.read_text())
        return s
    s.url = url or _server_url(server, servers_file or ROOT / "servers.json")
    await s._open()
    return s
