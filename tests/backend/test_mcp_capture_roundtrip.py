"""A local MCP capture must be recallable without contacting providers."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def isolated_env(root: Path) -> dict[str, str]:
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if key in os.environ
    }
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "MEMORY_GATEWAY_DATA": str(root / "data"),
        "MEMORY_GATEWAY_DB": str(root / "data" / "gateway.sqlite3"),
        "MEMORY_GATEWAY_BACKUP_DIR": str(root / "backups"),
        "MEMORY_GATEWAY_API_KEY": "",
        "OPENMEMORY_URL": "",
        "OPENMEMORY_ENABLED": "false",
        "GRAPHITI_URL": "",
        "GRAPHITI_ENABLED": "false",
        "MEMPALACE_URL": "",
        "MEMPALACE_ENABLED": "false",
        "OLLAMA_URL": "",
        "OLLAMA_ENABLED": "false",
        "RERANKER_URL": "",
        "RERANKER_ENABLED": "false",
        "OPENROUTER_URL": "",
        "EMBEDDING_ENABLED": "false",
        "PROVIDER_RECALL_ENABLED": "false",
        "OLLAMA_WARMUP_ENABLED": "false",
    })
    return env


class McpCaptureRoundTripTests(unittest.TestCase):
    def test_capture_is_recallable_and_raw_document_is_retained_by_default(self):
        with tempfile.TemporaryDirectory(prefix="mcp-capture-roundtrip-") as directory:
            result = subprocess.run(
                [sys.executable, "-c", textwrap.dedent(r'''
                    import json
                    import os
                    import subprocess
                    import sys
                    import threading
                    import uuid
                    from http.server import ThreadingHTTPServer
                    from pathlib import Path

                    root = Path(sys.argv[1])
                    sys.path.insert(0, str(root / "gateway"))
                    import server

                    queued_provider_calls = []
                    class DisabledExecutor:
                        def submit(self, function, *args, **kwargs):
                            queued_provider_calls.append((function, args, kwargs))
                            return None

                    server.PROVIDER_EXECUTOR = DisabledExecutor()
                    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                    thread.start()
                    with server.DB_LOCK:
                        server.DB.execute(
                            "INSERT INTO raw_documents(id,source,conversation_id,body,metadata_json,received_at) VALUES(?,?,?,?,?,?)",
                            ("private-existing-doc-991", "mcp", "private-conversation-992", "Existing synthetic preference", json.dumps({"private_marker": "private-metadata-993"}), "2026-09-27T00:00:00Z"),
                        )
                        server.DB.execute(
                            "INSERT INTO raw_documents(id,source,conversation_id,body,metadata_json,received_at) VALUES(?,?,?,?,?,?)",
                            ("private-incoming-doc-994", "mcp", "private-conversation-992", "Incoming synthetic preference", json.dumps({"private_marker": "private-metadata-995"}), "2026-09-27T00:00:00Z"),
                        )
                        server.DB.execute(
                            "INSERT INTO conflicts(id,source,conversation_id,existing_document_id,incoming_document_id,reason,details_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                            ("private-conflict-996", "mcp", "private-conversation-992", "private-existing-doc-991", "private-incoming-doc-994", "private-reason-997", "{}", "2026-09-27T00:00:00Z"),
                        )
                        server.DB.commit()
                    child_env = dict(os.environ)
                    child_env["MEMORY_GATEWAY_URL"] = f"http://127.0.0.1:{httpd.server_address[1]}"
                    child_env["MEMORY_GATEWAY_API_KEY"] = ""
                    conversation_id = "synthetic-mcp-capture-" + uuid.uuid4().hex
                    marker = "I prefer answers that are concise and clear."
                    messages = [
                        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "synthetic-capture-test", "version": "1"}}},
                        {"jsonrpc": "2.0", "method": "notifications/initialized"},
                        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "memory_capture", "arguments": {"source": "mcp", "conversation_id": conversation_id, "messages": [{"role": "user", "content": marker}]}}},
                        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "memory_recall", "arguments": {"query": "concise clear", "limit": 5}}},
                        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "memory_conflicts", "arguments": {"status": "open"}}},
                    ]
                    mcp = subprocess.run(
                        [sys.executable, str(root / "gateway" / "mcp_server.py")],
                        cwd=root / "gateway",
                        input="\n".join(json.dumps(message) for message in messages) + "\n",
                        text=True,
                        capture_output=True,
                        env=child_env,
                        timeout=30,
                        check=False,
                    )
                    try:
                        assert mcp.returncode == 0, mcp.stderr[-1000:]
                        responses = [json.loads(line) for line in mcp.stdout.splitlines() if line.strip()]
                        initialized = next(item["result"] for item in responses if item.get("id") == 1)
                        assert initialized["serverInfo"]["name"] == "link-memory", initialized
                        capture = next(item["result"]["structuredContent"] for item in responses if item.get("id") == 2)
                        recall = next(item["result"]["structuredContent"] for item in responses if item.get("id") == 3)
                        conflicts = next(item["result"]["structuredContent"] for item in responses if item.get("id") == 4)
                        assert capture["status"] == "processed", capture
                        assert capture["saved_count"] == 1, capture
                        assert capture["deleted_after_success"] is False, capture
                        assert "saved" not in capture and "raw_document_id" not in capture, capture
                        assert any(memory.get("source") == "mcp" and memory.get("text") == marker.rstrip(".") for memory in recall["memories"]), recall
                        assert len(conflicts["conflicts"]) == 1, conflicts
                        public_conflict = conflicts["conflicts"][0]
                        assert public_conflict["existing"]["text"] == "Existing synthetic preference", public_conflict
                        assert public_conflict["incoming"]["text"] == "Incoming synthetic preference", public_conflict
                        serialized_conflicts = json.dumps(conflicts, ensure_ascii=False)
                        for sentinel in ("private-existing-doc-991", "private-incoming-doc-994", "private-conversation-992", "private-metadata-993", "private-metadata-995", "private-reason-997"):
                            assert sentinel not in serialized_conflicts, serialized_conflicts
                        with server.DB_LOCK:
                            raw_document = server.DB.execute("SELECT id FROM raw_documents WHERE conversation_id=?", (conversation_id,)).fetchone()
                        assert raw_document is not None, "memory_capture retains the raw document unless deletion is explicitly requested"
                        assert len(queued_provider_calls) == 1, queued_provider_calls
                        fanout_function, _fanout_args, _fanout_kwargs = queued_provider_calls[0]
                        assert fanout_function is server.fanout_batch
                        print(json.dumps({"capture": capture["status"], "saved_count": capture["saved_count"], "recall_text_source_match": True, "conflict_projection_safe": True, "raw_document_retained": True, "provider_network_calls": 0}))
                    finally:
                        httpd.shutdown()
                        httpd.server_close()
                        thread.join(timeout=5)
                        server.DB.close()
                '''), str(PROJECT_ROOT)],
                cwd=PROJECT_ROOT,
                env=isolated_env(Path(directory)),
                capture_output=True,
                text=True,
                check=False,
                timeout=40,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertIn('"recall_text_source_match": true', result.stdout)
            self.assertIn('"conflict_projection_safe": true', result.stdout)
            self.assertIn('"raw_document_retained": true', result.stdout)
            self.assertIn('"provider_network_calls": 0', result.stdout)


if __name__ == "__main__":
    unittest.main()
