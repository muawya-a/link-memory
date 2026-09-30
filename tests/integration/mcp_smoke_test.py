"""Smoke-test the stdio MCP contract without writing a memory."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "gateway" / "mcp_server.py"


def main() -> int:
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "acceptance", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "memory_status", "arguments": {}}},
    ]
    process = subprocess.Popen([sys.executable, str(SERVER)], cwd=str(ROOT / "gateway"), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    payload = "\n".join(json.dumps(message) for message in messages) + "\n"
    stdout, stderr = process.communicate(payload, timeout=30)
    responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    initialize = next(item for item in responses if item.get("id") == 1)
    tools = next(item for item in responses if item.get("id") == 2)
    status = next(item for item in responses if item.get("id") == 3)
    names = {item.get("name") for item in tools.get("result", {}).get("tools", [])}
    status_data = status.get("result", {}).get("structuredContent", {})
    providers = status_data.get("providers", {})
    optional_providers = ("openmemory", "graphiti", "mempalace")
    gateway_available = status_data.get("available") is True
    expected_tools = {
        "memory_recall", "memory_context", "memory_interactive_context", "memory_remember",
        "memory_status", "memory_ingest", "memory_capture", "memory_import",
        "memory_conflicts", "memory_layers",
    }
    ok = (
        initialize.get("result", {}).get("serverInfo", {}).get("name") == "link-memory"
        and expected_tools <= names
        and gateway_available
    )
    if not ok or process.returncode != 0:
        raise SystemExit(json.dumps({"ok": False, "exit_code": process.returncode, "responses": responses, "stderr": stderr[-500:]}, ensure_ascii=False))
    print(json.dumps({
        "ok": True,
        "mcp_transport": "available",
        "gateway": "available",
        "tool_count": len(names),
        "optional_providers": {
            name: "available" if providers.get(name, {}).get("available") else "disabled or unavailable"
            for name in optional_providers
        },
        "end_to_end_capture_recall_verified": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
