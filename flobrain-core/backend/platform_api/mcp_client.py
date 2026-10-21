"""MCP client for external agents (Phase 14e, Decision 48). Streamable HTTP, JSON-RPC 2.0.

Every request goes through ``net.fetch_full``: https only, DNS checked and pinned, private and
reserved addresses refused, no redirects, a hard deadline and a size cap. The built-in demo
server is called in-process instead, and only in demo mode (``demo_hosts.is_demo_url``).
Nothing a server returns is executed or treated as instructions; callers get plain data.
"""

import itertools
import json

from platform_api import demo_hosts, net

PROTOCOL = "2025-06-18"
MAX_BYTES = 256 * 1024
_ids = itertools.count(1)


class MCPError(Exception):
    def __init__(self, code, details=""):
        super().__init__(details or code)
        self.code = code


def _parse(content_type: str, data: bytes, rid):
    """A JSON body, or an SSE stream whose ``data:`` lines hold the response."""
    text = data.decode("utf-8", errors="replace")
    candidates = []
    if "text/event-stream" in (content_type or ""):
        for line in text.splitlines():
            if line.startswith("data:"):
                candidates.append(line[5:].strip())
    else:
        candidates.append(text)
    for raw in candidates:
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if isinstance(msg, dict) and msg.get("id") == rid:
            return msg
    raise MCPError("bad_response", "the server did not answer with JSON-RPC")


class Session:
    """One short conversation with a server: initialize, then requests."""

    def __init__(self, url: str, token: str = ""):
        self.url = url
        self.token = token
        self.session_id = ""
        self.server_info = {}
        self.demo = demo_hosts.is_demo_url(url, demo_hosts.DEMO_MCP_HOST)

    def _send(self, message: dict, expect_reply=True):
        if self.demo:
            from platform_api import demo_mcp

            return demo_mcp.handle(message)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        try:
            status, resp_headers, data = net.fetch_full(
                "POST", self.url, json.dumps(message).encode(), headers, timeout=10, max_bytes=MAX_BYTES
            )
        except net.UnsafeURL as exc:
            raise MCPError("unsafe_url", str(exc)) from exc
        except OSError as exc:
            raise MCPError("unreachable", type(exc).__name__) from exc
        if resp_headers.get("mcp-session-id") and not self.session_id:
            self.session_id = resp_headers["mcp-session-id"][:200]
        if not expect_reply:
            return None
        if status in (401, 403):
            raise MCPError("unauthorized", f"the server answered {status}")
        if not 200 <= status < 300:
            raise MCPError("http_error", f"the server answered {status}")
        return _parse(resp_headers.get("content-type", ""), data, message.get("id"))

    def request(self, method, params=None):
        rid = next(_ids)
        reply = self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        if not isinstance(reply, dict):
            raise MCPError("bad_response", "no answer")
        if "error" in reply:
            err = reply.get("error") or {}
            raise MCPError("rpc_error", str(err.get("message") if isinstance(err, dict) else err)[:200])
        result = reply.get("result")
        if not isinstance(result, dict):
            raise MCPError("bad_response", "the result is not an object")
        return result

    def initialize(self):
        result = self.request(
            "initialize",
            {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "flobrain", "version": "2"}},
        )
        info = result.get("serverInfo") if isinstance(result.get("serverInfo"), dict) else {}
        self.server_info = {"name": str(info.get("name") or "")[:80], "version": str(info.get("version") or "")[:40]}
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)
        return self


def clean_tools(raw) -> list[dict]:
    """Keep only what FloBrain shows and validates against: name, description, schema, read hint."""
    out = []
    for tool in (raw or [])[:50]:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            continue
        name = tool["name"][:128]
        if not name.strip():
            continue
        schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {"type": "object"}
        if len(json.dumps(schema)) > 8000:
            schema = {"type": "object"}
        annotations = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
        out.append(
            {
                "name": name,
                "description": str(tool.get("description") or "")[:500],
                "inputSchema": schema,
                "readOnly": annotations.get("readOnlyHint") is True,
            }
        )
    return out


def list_tools(url, token=""):
    session = Session(url, token).initialize()
    result = session.request("tools/list")
    return session.server_info, clean_tools(result.get("tools"))


def call_tool(url, token, name, arguments):
    """Returns (text, is_error). Only text content is kept; anything else is described, not run."""
    session = Session(url, token).initialize()
    result = session.request("tools/call", {"name": name, "arguments": arguments})
    parts = []
    for item in (result.get("content") or [])[:20]:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
        elif isinstance(item, dict):
            parts.append(f"[{str(item.get('type') or 'content')[:20]} content not shown]")
    if not parts and isinstance(result.get("structuredContent"), (dict, list)):
        parts.append(json.dumps(result["structuredContent"])[:8000])
    return "\n".join(parts), bool(result.get("isError"))
