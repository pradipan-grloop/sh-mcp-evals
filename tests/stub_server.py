"""A stand-in for Stitched Health's MCP server (streamable HTTP) for tests. Its data is made
up; it copies only the shapes: instructions at initialize, readOnlyHint annotations, and the
refusal format (message, then "Code: X. Fix: Y", with structuredContent)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

INSTRUCTIONS = "Stub instructions: every call acts as the signed-in admin."
READ = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
WRITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
PROGRAM = {"type": "string", "description": "The program's id (a uuid), from list_programs"}

TOOLS = [
    {"name": "get_health", "description": "Platform health: API, database, queues and video processing.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}, "annotations": READ},
    {"name": "list_programs", "description": "List the programs this account can see, with their status.",
     "inputSchema": {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object",
                     "properties": {"search": {"type": "string", "description": "Matches the program name"}},
                     "additionalProperties": False}, "annotations": READ},
    {"name": "get_program_readiness", "description": "The publish checklist for one program, row by row.",
     "inputSchema": {"type": "object", "properties": {"programId": PROGRAM}, "required": ["programId"],
                     "additionalProperties": False}, "annotations": READ},
    {"name": "search_learners", "description": "Search learners; personal fields only with a reason.",
     "inputSchema": {"type": "object", "properties": {
         "pii_fields": {"type": "array", "items": {"type": "string"}, "description": "name, email or npi"},
         "reason": {"type": "string", "description": "Why the personal data is needed"}},
         "additionalProperties": False}, "annotations": READ},
    {"name": "set_visibility", "description": "Set a program's status: PRIVATE, UNLISTED or PUBLIC.",
     "inputSchema": {"type": "object", "properties": {
         "programId": PROGRAM,
         "status": {"type": "string", "enum": ["PRIVATE", "UNLISTED", "PUBLIC"], "description": "New status"}},
         "required": ["programId", "status"], "additionalProperties": False}, "annotations": WRITE},
]


def _refusal(code, message, fix, **detail):
    data = {"code": code, "field": None, "message": message, "fixHint": fix, **detail}
    return {"content": [{"type": "text", "text": message}, {"type": "text", "text": f"Code: {code}. Fix: {fix}"}],
            "structuredContent": data, "isError": True}


def _ok(data):
    return {"content": [{"type": "text", "text": json.dumps(data)}], "isError": False}


def _call(name, args):
    if name == "get_health":
        return _ok({"status": "ok", "video": {"processing": 0, "failedLastDay": 0}})
    if name == "list_programs":
        return _ok({"programs": [{"id": "p-1", "name": "Stub AFib", "status": "PRIVATE"}], "total": 1})
    if name == "get_program_readiness":
        return _ok({"ready": False, "failing": [{"item": "Videos", "reason": "no full-length video"}]})
    if name == "search_learners":
        if args.get("pii_fields") and not args.get("reason"):
            return _refusal("REASON_REQUIRED", "A reason is required to release personal data.",
                            "Ask the admin why they need it and send it as reason.")
        return _ok({"learners": [{"id": "l-1", "hasNpi": True}], "total": 1})
    if name == "set_visibility":
        return _refusal("NOT_READY", "Stub AFib is not ready to publish.", "Fix the failing checklist rows.",
                        failing=[{"item": "Videos"}])
    return {"content": [{"type": "text", "text": f"Tool {name} not found"}], "isError": True}


class Stub:
    """Start with Stub(token=...); .url, .throttle_next (answer the next N requests with 429),
    .seen (every JSON-RPC message received), .stop()."""

    def __init__(self, token=None):
        self.token = token
        self.throttle_next = 0
        self.seen = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body=None, ctype="application/json", headers=()):
                self.send_response(status)
                for k, v in headers:
                    self.send_header(k, v)
                if body is None:
                    self.end_headers()
                    return
                self.send_header("Content-Type", ctype)
                self.end_headers()
                self.wfile.write(body.encode())

            def do_POST(self):
                msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if stub.throttle_next > 0:
                    stub.throttle_next -= 1
                    return self._send(429, json.dumps({"message": "Too many requests"}),
                                      headers=[("Retry-After", "0")])
                if stub.token and self.headers.get("Authorization") != f"Bearer {stub.token}":
                    return self._send(401, json.dumps({"jsonrpc": "2.0", "id": None, "error": {
                        "code": -32001, "message": "Agent token revoked"}}))  # SH's own 401 shape
                stub.seen.append(msg)
                if "id" not in msg:  # notification
                    return self._send(202)
                method, params = msg["method"], msg.get("params", {})
                if method == "initialize":
                    result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                              "serverInfo": {"name": "stitched-health", "version": "9.9.9-stub"},
                              "instructions": INSTRUCTIONS}
                elif method == "tools/list":
                    result = {"tools": TOOLS}
                elif method == "tools/call":
                    result = _call(params["name"], params.get("arguments", {}))
                else:
                    result = None
                body = json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result})
                if method == "tools/call":  # exercise the SSE path too
                    return self._send(200, f"event: message\ndata: {body}\n\n", "text/event-stream")
                return self._send(200, body)

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self._srv.server_port}/mcp"

    def stop(self):
        self._srv.shutdown()
        self._srv.server_close()
