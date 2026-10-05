"""Minimal MCP stdio server exposing one gateway instead of three stores."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

if __package__:
    from .outbound_http import urlopen_no_proxy_redirects
else:
    from outbound_http import urlopen_no_proxy_redirects

# MCP responses can contain Arabic memory text. Windows may start this stdio
# process with a legacy code page; force UTF-8 so a valid recall never fails
# while serializing the response.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


def load_local_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_local_env()

GATEWAY_URL = os.getenv("MEMORY_GATEWAY_URL", "http://127.0.0.1:18000").rstrip("/")
GATEWAY_API_KEY = os.getenv("MEMORY_GATEWAY_API_KEY", "").strip()
GATEWAY_FAILURE_MESSAGE = "Link Memory could not complete the request. Check the connection and try again."


def gateway_request(path: str, payload: dict[str, Any] | None = None, *, method: str | None = None) -> dict[str, Any]:
    """Call the live Gateway so long-lived MCP processes never pin stale code."""
    data = None
    request_method = method or ("POST" if payload is not None else "GET")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if GATEWAY_API_KEY:
        headers["Authorization"] = f"Bearer {GATEWAY_API_KEY}"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        request = urllib.request.Request(f"{GATEWAY_URL}{path}", data=data, headers=headers, method=request_method)
        with urlopen_no_proxy_redirects(request, timeout=120) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        try:
            exc.close()
        except Exception:
            pass
        raise RuntimeError(GATEWAY_FAILURE_MESSAGE) from None
    except Exception as exc:
        print(f"Gateway request failed ({type(exc).__name__})", file=sys.stderr)
        raise RuntimeError(GATEWAY_FAILURE_MESSAGE) from None


def bounded_context(data: dict[str, Any]) -> dict[str, Any]:
    memories = data.get("memories") if isinstance(data.get("memories"), list) else []
    lines = [f"- [{item.get('type', 'fact')}] {item.get('text', '')}" for item in memories]
    return {"query": data.get("query", ""), "context": "\n".join(lines), "memories": memories, "recall": data.get("recall", {})}


def send(message: dict[str, Any]) -> None:
    # Keep the JSON-RPC transport ASCII-safe even when the parent process uses
    # a legacy Windows code page. The client still decodes the escaped Unicode.
    sys.stdout.write(json.dumps(message, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def result(request_id: Any, payload: Any) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "result": payload})


def error(request_id: Any, code: int, message: str) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


TOOLS = [
    {"name": "memory_recall", "description": "Search Link Memory and return relevant memories with their available source and date evidence.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}, "type": {"type": "string"}}, "required": ["query"]}},
    {"name": "memory_context", "description": "Build a bounded, response-ready context from relevant Link Memory evidence without returning full transcripts.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["query"]}},
    {"name": "memory_interactive_context", "description": "Retrieve a bounded context packet for a new message, including relevant facts, preferences, decisions, relationships, and dates.", "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 12}}, "required": ["message"]}},
    {"name": "memory_remember", "description": "Save one durable memory through the gateway.", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, "type": {"type": "string"}, "source": {"type": "string"}, "confidence": {"type": "number"}}, "required": ["text"]}},
    {"name": "memory_status", "description": "Show whether Link Memory is responding.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "memory_ingest", "description": "Submit a complete conversation for one-pass local analysis.", "inputSchema": {"type": "object", "properties": {"source": {"type": "string"}, "conversation_id": {"type": "string"}, "messages": {"type": "array"}, "text": {"type": "string"}}, "required": ["source"]}},
    {"name": "memory_capture", "description": "Capture a user-selected conversation. The temporary raw copy is retained unless delete_after_success is explicitly true.", "inputSchema": {"type": "object", "properties": {"source": {"type": "string"}, "conversation_id": {"type": "string"}, "messages": {"type": "array"}, "text": {"type": "string"}, "delete_after_success": {"type": "boolean"}}, "required": ["source"]}},
    {"name": "memory_import", "description": "Import a bounded batch of conversations with idempotency and conflict records.", "inputSchema": {"type": "object", "properties": {"source": {"type": "string"}, "documents": {"type": "array"}, "conversations": {"type": "array"}, "delete_after_success": {"type": "boolean"}}, "required": ["source"]}},
    {"name": "memory_conflicts", "description": "List or resolve conversation import conflicts.", "inputSchema": {"type": "object", "properties": {"status": {"type": "string"}, "conflict_id": {"type": "string"}, "resolution": {"type": "string"}}}},
    {"name": "memory_layers", "description": "Show availability of facts, relationships and events, and original-source evidence.", "inputSchema": {"type": "object", "properties": {}}},
]


_PUBLIC_MEMORY_SOURCES = {
    "codex", "chatgpt", "claude", "claude_code", "gemini", "grok", "hermes",
    "pc-file", "manual", "mcp",
}
_INTERNAL_MEMORY_TAGS = {"openmemory", "graphiti", "mempalace", "reranker", "embedding", "ollama", "openrouter", "neo4j"}


def _project_public_memory(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    text = value.get("display_text") or value.get("text")
    if not isinstance(text, str):
        return None
    result: dict[str, Any] = {"text": text}
    kind = value.get("type", value.get("kind"))
    if isinstance(kind, str) and kind in {"fact", "preference", "decision", "skill", "relationship", "date", "episode"}:
        result["type"] = kind
    source = value.get("source")
    if isinstance(source, str) and source.strip().lower() in _PUBLIC_MEMORY_SOURCES:
        result["source"] = source.strip().lower()
    date = value.get("date") or value.get("occurred_at")
    if isinstance(date, str) and date.strip():
        result["date"] = date.strip()[:80]
    tags = value.get("tags")
    if isinstance(tags, list):
        result["tags"] = [
            tag.strip()[:80] for tag in tags[:12]
            if isinstance(tag, str) and tag.strip() and tag.strip().lower() not in _INTERNAL_MEMORY_TAGS
        ]
    return result


def _project_public_memories(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [projected for item in value if (projected := _project_public_memory(item)) is not None]


def _project_public_conflict(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    identifier = value.get("conflict_id") or value.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        return None
    status = value.get("status")
    if status not in {"open", "resolved", "ignored"}:
        status = "needs_review"
    conflict: dict[str, Any] = {"conflict_id": identifier, "status": status}
    source = value.get("source")
    if isinstance(source, str) and source.strip().lower() in _PUBLIC_MEMORY_SOURCES:
        conflict["source"] = source.strip().lower()
    details = value.get("details")
    if isinstance(details, dict):
        for name in ("existing", "incoming"):
            item = details.get(name)
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                conflict[name] = {"text": item["text"][:2000]}
    return conflict


def project_mcp_output(name: str, data: Any) -> Any:
    """Return a customer-safe MCP DTO, never forwarding Gateway diagnostics."""
    payload = data if isinstance(data, dict) else {}
    if name == "memory_status":
        return {"available": payload.get("ok") is True}
    if name == "memory_layers":
        statuses = payload.get("status") if isinstance(payload.get("status"), dict) else {}
        layer_sources = (
            ("facts_and_decisions", "openmemory"),
            ("events_and_relationships", "graphiti"),
            ("original_sources", "mempalace"),
        )
        return {
            "available": payload.get("ok") is True,
            "layers": [
                {
                    "kind": kind,
                    "available": isinstance(statuses.get(provider), dict) and statuses[provider].get("available") is True,
                }
                for kind, provider in layer_sources
            ],
        }
    if name == "memory_recall":
        return {
            "query": payload.get("query", "") if isinstance(payload.get("query"), str) else "",
            "memories": _project_public_memories(payload.get("memories")),
        }
    if name in {"memory_context", "memory_interactive_context"}:
        context_packet = payload.get("context_packet")
        projected_packet = _project_public_memories(context_packet)
        result = {
            "query": payload.get("query", "") if isinstance(payload.get("query"), str) else "",
            "context": payload.get("context", "") if isinstance(payload.get("context"), str) else "",
            "context_packet": projected_packet,
        }
        if name == "memory_context":
            result["memories"] = projected_packet
            result.pop("context_packet")
        return result
    if name == "memory_remember":
        status = payload.get("status")
        return {"status": status} if isinstance(status, str) else {"status": "unknown"}
    if name in {"memory_ingest", "memory_capture"}:
        result: dict[str, Any] = {
            "status": payload.get("status") if isinstance(payload.get("status"), str) else "unknown",
        }
        for key in ("saved_count", "deleted_after_success", "submitted", "retryable"):
            value = payload.get(key)
            if isinstance(value, (int, bool)):
                result[key] = value
        return result
    if name == "memory_import":
        result = {"status": payload.get("status") if isinstance(payload.get("status"), str) else "unknown"}
        for key in ("total", "processed", "duplicates", "conflicts", "failed"):
            value = payload.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                result[key] = value
        return result
    if name == "memory_conflicts":
        if isinstance(data, list):
            projected = [item for value in data if (item := _project_public_conflict(value)) is not None]
            return {"conflicts": projected}
        if isinstance(payload.get("conflicts"), list):
            projected = [item for value in payload["conflicts"] if (item := _project_public_conflict(value)) is not None]
            return {"conflicts": projected}
        conflict = _project_public_conflict(payload.get("conflict"))
        if conflict is not None:
            return {"conflict": conflict}
        return {"conflicts": []}
    return data


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    if name == "memory_recall":
        data = gateway_request("/v1/recall", {
            "query": str(arguments.get("query", "")),
            "limit": int(arguments.get("limit", 8)),
            "type": arguments.get("type"),
        })
    elif name == "memory_context":
        data = gateway_request("/v1/interactive/context", {
            "message": str(arguments.get("query", "")),
            "limit": int(arguments.get("limit", 8)),
        })
    elif name == "memory_interactive_context":
        data = gateway_request("/v1/interactive/context", {
            "message": str(arguments.get("message", "")),
            "limit": int(arguments.get("limit", 8)),
        })
    elif name == "memory_remember":
        data = gateway_request("/v1/remember", {**arguments, "source": str(arguments.get("source", "mcp"))})
    elif name == "memory_status":
        data = gateway_request("/health")
    elif name == "memory_ingest":
        data = gateway_request("/v1/ingest", arguments)
    elif name == "memory_capture":
        capture = dict(arguments)
        capture.setdefault("delete_after_success", False)
        data = gateway_request("/v1/ingest", capture)
    elif name == "memory_import":
        data = gateway_request("/v1/import", arguments)
    elif name == "memory_conflicts":
        if arguments.get("conflict_id"):
            data = gateway_request("/v1/conflicts/resolve", {"conflict_id": arguments["conflict_id"], "status": arguments.get("resolution", "resolved")})
        else:
            status = arguments.get("status")
            path = "/v1/conflicts" + (f"?status={status}" if status else "")
            data = gateway_request(path)
    elif name == "memory_layers":
        data = gateway_request("/v1/memory-layers")
    else:
        raise ValueError(f"unknown tool: {name}")
    data = project_mcp_output(name, data)
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}], "structuredContent": data}


def main() -> None:
    for line in sys.stdin:
        request: dict[str, Any] = {}
        try:
            request = json.loads(line)
            request_id = request.get("id")
            method = request.get("method")
            if method == "initialize":
                result(request_id, {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "link-memory", "version": "0.1.1"}})
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                result(request_id, {"tools": TOOLS})
            elif method == "tools/call":
                params = request.get("params", {})
                result(request_id, call_tool(str(params.get("name")), params.get("arguments", {})))
            else:
                error(request_id, -32601, f"method not found: {method}")
        except Exception as exc:
            print(f"MCP request failed ({type(exc).__name__})", file=sys.stderr)
            safe_message = GATEWAY_FAILURE_MESSAGE if isinstance(exc, RuntimeError) and exc.args == (GATEWAY_FAILURE_MESSAGE,) else "The MCP request could not be completed."
            error(request.get("id") if isinstance(request, dict) else None, -32603, safe_message)


if __name__ == "__main__":
    main()
