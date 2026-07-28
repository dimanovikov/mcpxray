"""Minimal stdlib MCP server for testing ``--runtime`` capture.

Speaks the MCP JSON-RPC 2.0 stdio handshake (newline-delimited JSON): answers
``initialize``, acknowledges ``notifications/initialized`` (no reply), and serves
a fixed ``tools/list``. No third-party deps — just the stdlib — so the test
suite can spawn it with ``python <this file>`` on any platform.
"""

import json
import sys

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "test-runtime-server", "version": "0.1.0"}

TOOLS = [
    {
        "name": "add",
        "description": "Add two numbers.",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    },
    {
        "name": "ping",
        "description": "Health check.",
        "inputSchema": {"type": "object"},
    },
]


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            msg = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        method = msg.get("method")
        req_id = msg.get("id")
        if method == "initialize":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "serverInfo": SERVER_INFO,
                        "capabilities": {"tools": {}},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue  # notification — no response expected
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
        elif req_id is not None:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"method not found: {method}"},
                }
            )


if __name__ == "__main__":
    main()
