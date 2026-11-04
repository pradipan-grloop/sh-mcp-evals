"""MCP client with three modes: live, record (live + save a cassette) and replay (cassette only)."""
import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL = "2025-06-18"
RETRIES_429 = 4
RETRY_BASE_SECONDS = 5.0  # first wait after a 429 with no Retry-After; doubles each time, capped at 60
CODE_IN_TEXT = re.compile(r"Code: ([A-Z][A-Z0-9_]*)\.")


class CassetteMiss(LookupError):
    """A replayed call that was never recorded."""


class AuthError(RuntimeError):
    """The server refused the token."""


@dataclass
class Result:
    text: str
    is_error: bool
    data: object = None  # structuredContent, or else the text parsed as JSON
    off_recording: bool = False
    blocked: bool = False  # stopped by evalkit's write guard; never sent to the server

    @property
    def ok(self):
        return not self.is_error

    @property
    def code(self):
        """A refusal's code (NOT_READY, STALE_VERSION, ...), or None."""
        if not self.is_error:
            return None
        if isinstance(self.data, dict) and self.data.get("code"):
            return self.data["code"]
        m = CODE_IN_TEXT.search(self.text)
        return m.group(1) if m else None


def _key(name, args):
    return f"{name} {json.dumps(args, sort_keys=True)}"


def _to_result(raw):
    text = "\n".join(c.get("text", "") for c in raw.get("content", []) if c.get("type") == "text")
    data = raw.get("structuredContent")
    if data is None:
        try:
            data = json.loads(text)
        except ValueError:
            data = None
    return Result(text=text, is_error=bool(raw.get("isError")), data=data)


def _retry_after(resp, attempt):
    try:
        return max(0.0, float(resp.headers["retry-after"]))
    except (KeyError, ValueError):
        return min(RETRY_BASE_SECONDS * 2 ** attempt, 60.0)


def _message(resp):
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300]
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict) and err.get("message"):  # SH answers a 401 as a JSON-RPC error
        return err["message"]
    if isinstance(body, dict) and (body.get("message") or body.get("error_description")):
        return body.get("message") or body.get("error_description")
    return json.dumps(body)[:300]


@dataclass
class Session:
    server: str
    mode: str
    cassette_path: Path | None
    url: str | None = None
    token: str | None = None
    calls: list = field(default_factory=list)
    server_info: dict = field(default_factory=dict)
    instructions: str | None = None
    _tools: list | None = None
    _http: httpx.AsyncClient | None = None
    _sid: str | None = None
    _next_id: int = 0
    _cassette: dict = field(default_factory=lambda: {"server": None, "tools": None, "calls": []})

    # --- transport (live and record) ---
    async def _post(self, msg):
        for attempt in range(RETRIES_429 + 1):
            resp = await self._http.post(self.url, json=msg, headers=self._headers())
            if resp.status_code != 429 or attempt == RETRIES_429:
                break
            await asyncio.sleep(_retry_after(resp, attempt))
        if resp.status_code == 401:
            raise AuthError(f"{self.url} refused the token (401): {_message(resp)}")
        resp.raise_for_status()
        return resp

    async def _rpc(self, method, params=None):
        self._next_id += 1
        msg = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            msg["params"] = params
        resp = await self._post(msg)
        self._sid = resp.headers.get("mcp-session-id", self._sid)
        body = _parse_body(resp, self._next_id)
        if "error" in body:
            raise RuntimeError(f"{method} failed: {body['error']}")
        return body["result"]

    def _headers(self):
        h = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": PROTOCOL}
        if self._sid:
            h["mcp-session-id"] = self._sid
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _open(self):
        self._http = httpx.AsyncClient(timeout=120)
        init = await self._rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                              "clientInfo": {"name": "evalkit", "version": "0.2"}})
        self.server_info = init.get("serverInfo") or {}
        self.instructions = init.get("instructions")
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        if self.mode == "record":
            self._cassette["server"] = {"serverInfo": self.server_info, "instructions": self.instructions}
            self._save()

    # --- public API ---
    async def list_tools(self):
        if self._tools is not None:
            return self._tools
        if self.mode == "replay":
            self._tools = self._cassette["tools"] or []
            return self._tools
        self._tools = (await self._rpc("tools/list"))["tools"]
        if self.mode == "record":
            self._cassette["tools"] = self._tools
            self._save()
        return self._tools

    def is_write(self, name):
        """True if the listed tool changes data. MCP's readOnlyHint defaults to false, so a
        listed tool that does not say it is read-only counts as a write. A name the server
        did not list is not a write here: the server refuses it."""
        for t in self._tools or []:
            if t.get("name") == name:
                return not (t.get("annotations") or {}).get("readOnlyHint", False)
        return False

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
        self.cassette_path.write_text(json.dumps(self._cassette, indent=2) + "\n", encoding="utf-8")


def _parse_body(resp, want_id):
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                msg = json.loads(line[5:].strip())
                if msg.get("id") == want_id:
                    return msg
        raise RuntimeError(f"no response with id {want_id} in event stream")
    return resp.json()


async def connect(server, mode="live", case=None, url=None, token=None, fixtures_dir=None):
    """Open a session to `url`. mode: live | record | replay. The token is passed in by the
    caller (the runner reads it from .env); without one, MCP_TOKEN_<SERVER> is tried."""
    if mode not in ("live", "record", "replay"):
        raise ValueError(f"mode must be live, record or replay, not {mode!r}")
    fixtures_dir = Path(fixtures_dir or ROOT / "fixtures")
    cassette = fixtures_dir / server / f"{case}.json" if case else None
    if mode in ("record", "replay") and cassette is None:
        raise ValueError(f"mode {mode!r} needs a case id")
    s = Session(server=server, mode=mode, cassette_path=cassette)
    if mode == "replay":
        if not cassette.exists():
            raise FileNotFoundError(f"no recording at {cassette}; run once with mode='record'")
        s._cassette = json.loads(cassette.read_text(encoding="utf-8"))
        recorded = s._cassette.get("server") or {}
        s.server_info = recorded.get("serverInfo") or {}
        s.instructions = recorded.get("instructions")
        return s
    if not url:
        raise ValueError("live and record need the server's url")
    s.url = url
    s.token = token or os.environ.get(f"MCP_TOKEN_{server.upper().replace('-', '_')}")
    await s._open()
    return s
