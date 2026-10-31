"""A stand-in Prometheus MCP server (streamable HTTP) for tests. Not a real Prometheus."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = [
    {"name": "health_check", "description": "Check that the Prometheus MCP server and Prometheus are reachable.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "execute_query", "description": "Run an instant PromQL query and return the result vector.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "PromQL expression"},
         "time": {"type": "string", "description": "Evaluation time, RFC3339 or unix seconds"}},
         "required": ["query"]}},
    {"name": "list_metrics", "description": "List every metric name Prometheus knows about.",
     "inputSchema": {"type": "object", "properties": {}}},
]

QUERIES = {
    "count(up)": [{"metric": {}, "value": [1761800000, "12"]}],
    "count(up == 0) or vector(0)": [{"metric": {}, "value": [1761800000, "2"]}],
}


def _call(name, args):
    if name == "health_check":
        return {"status": "healthy"}, False
    if name == "list_metrics":
        return ["up", "kafka_consumergroup_lag", "kafka_topic_partitions"], False
    if name == "execute_query":
        q = args.get("query", "")
        if q not in QUERIES:
            return f"query not supported by stub: {q}", True
        return {"resultType": "vector", "result": QUERIES[q]}, False
    return f"unknown tool {name}", True


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "id" not in msg:  # notification
            self.send_response(202)
            self.end_headers()
            return
        method, params = msg["method"], msg.get("params", {})
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "stub-prometheus", "version": "0"}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            data, err = _call(params["name"], params.get("arguments", {}))
            text = data if isinstance(data, str) else json.dumps(data)
            result = {"content": [{"type": "text", "text": text}], "isError": err}
        else:
            result = None
        body = json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result})
        self.send_response(200)
        self.send_header("mcp-session-id", "stub-session")
        if method == "tools/call":  # exercise the SSE path too
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(f"event: message\ndata: {body}\n\n".encode())
        else:
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())


def start():
    """Start on a free port; returns (url, stop)."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_port}/mcp", srv.shutdown
