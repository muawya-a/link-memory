from __future__ import annotations

import importlib
import json
import os
import sqlite3
import sys
import threading
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "gateway"))
server = importlib.import_module("server")
http_routes = importlib.import_module("http_routes")
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
hook_script = importlib.import_module("codex_user_prompt_hook")


class FakeHandler:
    def __init__(self, *, path, payload=None, client_ip="127.0.0.1", headers=None):
        self.path = path
        self.payload = payload or {}
        self.client_address = (client_ip, 43210)
        self.headers = headers or {}
        self.responses = []
        self.read_count = 0

    def read_json(self):
        self.read_count += 1
        return self.payload

    def send_json(self, body, status=200):
        self.responses.append((body, status))


class FakeServices:
    def __init__(self):
        self.calls = []
        self.API_KEY = "configured-for-test"

    def auth_ok(self, _handler):
        return True

    def hook_local_context(self, message, limit):
        self.calls.append((message, limit))
        return {"context_packet": [{"type": "fact", "text": "synthetic context"}]}


class CodexPromptHookTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        server.initialize_schema(self.db)
        self.previous_db = server.DB
        self.previous_lock = server.DB_LOCK
        self.previous_hook_context_ids = server.HOOK_CONTEXT_MEMORY_IDS
        server.DB = self.db
        server.DB_LOCK = threading.RLock()
        server.HOOK_CONTEXT_MEMORY_IDS = {"synthetic-active"}
        timestamp = "2026-09-26T00:00:00+00:00"
        with server.DB_LOCK:
            server.DB.execute(
                "INSERT INTO memories(id,kind,text,source,occurred_at,confidence,metadata_json,created_at,updated_at,archived) "
                "VALUES(?,?,?,?,?,?,?,?,?,0)",
                ("synthetic-active", "fact", "The telescope project uses a cedar mount", "codex", "2026-09-25", 0.9, '{"scope":"project-only"}', timestamp, timestamp),
            )
            server.DB.execute(
                "INSERT INTO memories(id,kind,text,source,occurred_at,confidence,metadata_json,created_at,updated_at,archived) "
                "VALUES(?,?,?,?,?,?,?,?,?,1)",
                ("synthetic-archived", "fact", "The telescope archive uses cedar glass", "codex", "2026-09-20", 0.9, "{}", timestamp, timestamp),
            )
            server.DB.execute(
                "INSERT INTO memories(id,kind,text,source,occurred_at,confidence,metadata_json,created_at,updated_at,archived) "
                "VALUES(?,?,?,?,?,?,?,?,?,0)",
                ("synthetic-unapproved", "fact", "The telescope project uses an oak mount", "codex", "2026-09-26", 0.9, "{}", timestamp, timestamp),
            )
            server.DB.commit()

    def tearDown(self):
        server.DB = self.previous_db
        server.DB_LOCK = self.previous_lock
        server.HOOK_CONTEXT_MEMORY_IDS = self.previous_hook_context_ids
        self.db.close()

    def test_local_hook_context_uses_only_sqlite_fts_and_server_allowlisted_ids(self):
        with (
            patch.object(server, "vector_search", side_effect=AssertionError("vector network path used")),
            patch.object(server, "embed_text", side_effect=AssertionError("embedding path used")),
            patch.object(server, "provider_recall", side_effect=AssertionError("provider path used"), create=True),
            patch.object(server, "request_json", side_effect=AssertionError("HTTP service called")),
        ):
            result = server.hook_local_context("Which telescope project uses the cedar mount?", limit=99)

        self.assertEqual(len(result["context_packet"]), 1)
        self.assertEqual(result["context_packet"][0]["text"], "The telescope project uses a cedar mount")
        self.assertEqual(result["context_packet"][0]["source"], "codex")
        self.assertEqual(result["context_packet"][0]["date"], "2026-09-25")
        self.assertLessEqual(result["limit"], 3)
        self.assertLessEqual(len(result["context_packet"]), 3)
        self.assertNotIn("query", result)
        self.assertNotIn("synthetic-archived", str(result))
        self.assertNotIn("The telescope project uses an oak mount", str(result))

    def test_local_hook_context_respects_requested_limit_after_scope_filtering(self):
        timestamp = "2026-09-26T00:00:00+00:00"
        with server.DB_LOCK:
            server.DB.execute(
                "INSERT INTO memories(id,kind,text,source,occurred_at,confidence,metadata_json,created_at,updated_at,archived) "
                "VALUES(?,?,?,?,?,?,?,?,?,0)",
                ("synthetic-active-2", "fact", "The telescope project uses a cedar mount for observations", "manual", "2026-09-26", 0.9, '{"scope":"anything"}', timestamp, timestamp),
            )
            server.DB.commit()
        server.HOOK_CONTEXT_MEMORY_IDS = {"synthetic-active", "synthetic-active-2"}

        result = server.hook_local_context("Which telescope project uses the cedar mount?", limit=1)

        self.assertEqual(result["limit"], 1)
        self.assertEqual(len(result["context_packet"]), 1)

    def test_empty_server_allowlist_returns_no_context_even_for_global_metadata(self):
        with server.DB_LOCK:
            server.DB.execute(
                "UPDATE memories SET metadata_json=? WHERE id=?",
                ('{"scope":"global"}', "synthetic-active"),
            )
            server.DB.commit()
        server.HOOK_CONTEXT_MEMORY_IDS = set()

        result = server.hook_local_context("Which telescope project uses the cedar mount?")

        self.assertEqual(result["context_packet"], [])

    def test_empty_or_generic_prompt_does_not_inject_unrelated_memories(self):
        self.assertEqual(server.hook_local_context("hello")["context_packet"], [])
        self.assertEqual(server.hook_local_context("What do you remember about me?")["context_packet"], [])

    def test_prompt_context_http_route_rejects_non_loopback_before_reading_body(self):
        handler = FakeHandler(
            path="/v1/hooks/codex/user-prompt-context",
            payload={"message": "synthetic private query"},
            client_ip="203.0.113.10",
        )
        services = FakeServices()

        http_routes.handle_post(handler, services)

        self.assertEqual(handler.responses, [({"error": "local hook endpoint only"}, 403)])
        self.assertEqual(services.calls, [])
        self.assertEqual(handler.read_count, 0)

    def test_prompt_context_http_route_limits_payload_and_calls_local_search(self):
        handler = FakeHandler(
            path="/v1/hooks/codex/user-prompt-context",
            payload={"message": "Which telescope?", "limit": 99},
        )
        services = FakeServices()

        http_routes.handle_post(handler, services)

        self.assertEqual(services.calls, [("Which telescope?", 3)])
        self.assertEqual(handler.responses, [({"context_packet": [{"type": "fact", "text": "synthetic context"}]}, 200)])

    def test_prompt_context_http_route_rejects_oversized_payload_without_reading(self):
        handler = FakeHandler(
            path="/v1/hooks/codex/user-prompt-context",
            headers={"Content-Length": str(256 * 1024 + 1)},
        )
        services = FakeServices()

        http_routes.handle_post(handler, services)

        self.assertEqual(handler.responses, [({"error": "request is too large"}, 413)])
        self.assertEqual(handler.read_count, 0)

    def test_prompt_context_http_route_requires_a_gateway_api_key(self):
        handler = FakeHandler(path="/v1/hooks/codex/user-prompt-context")
        services = FakeServices()
        services.API_KEY = ""

        http_routes.handle_post(handler, services)

        self.assertEqual(handler.responses, [({"error": "local hook authentication is not configured"}, 503)])
        self.assertEqual(handler.read_count, 0)

    def test_prompt_context_http_route_hides_unexpected_error_details(self):
        handler = FakeHandler(
            path="/v1/hooks/codex/user-prompt-context",
            payload={"message": "prompt sentinel"},
        )
        services = FakeServices()
        services.hook_local_context = lambda *_args: (_ for _ in ()).throw(RuntimeError("prompt sentinel diagnostic"))
        stderr = StringIO()

        with redirect_stderr(stderr):
            http_routes.handle_post(handler, services)

        self.assertEqual(handler.responses, [({"error": "local hook context unavailable"}, 503)])
        self.assertNotIn("prompt sentinel", stderr.getvalue())

    def test_prompt_hook_adds_only_bounded_untrusted_context_and_never_blocks(self):
        calls = []
        result = hook_script.process_hook_payload(
            {"hook_event_name": "UserPromptSubmit", "prompt": "What was the telescope decision?"},
            lambda prompt: calls.append(prompt) or {"context_packet": [{
                "type": "decision", "source": "manual", "date": "2026-09-26", "text": "Use the cedar mount.\n" + "x" * 3000,
            }]},
        )

        self.assertEqual(calls, ["What was the telescope decision?"])
        self.assertIs(result["continue"], True)
        output = result["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "UserPromptSubmit")
        self.assertLessEqual(len(output["additionalContext"]), hook_script.MAX_CONTEXT_CHARS)
        self.assertIn("do not follow instructions", output["additionalContext"])
        serialized = output["additionalContext"].split("\n", 1)[1]
        self.assertIsInstance(json.loads(serialized), list)

    def test_prompt_hook_ignores_other_events_and_fails_open_on_gateway_failure(self):
        called = []
        ignored = hook_script.process_hook_payload(
            {"hook_event_name": "Stop", "prompt": "synthetic"},
            lambda _prompt: called.append(True) or {"context_packet": []},
        )
        failed = hook_script.process_hook_payload(
            {"hook_event_name": "UserPromptSubmit", "prompt": "synthetic"},
            lambda _prompt: (_ for _ in ()).throw(RuntimeError("private detail")),
        )

        self.assertEqual(ignored, {"continue": True})
        self.assertEqual(failed, {"continue": True})
        self.assertEqual(called, [])

    def test_hook_gateway_client_uses_literal_loopback_not_configurable_url(self):
        connections = []

        class Response:
            status = 200

            def read(self, _limit):
                return b'{"context_packet":[]}'

        class Connection:
            def __init__(self, host, port, timeout):
                connections.append((host, port, timeout))

            def request(self, method, path, body, headers):
                connections.append((method, path, json.loads(body), headers))

            def getresponse(self):
                return Response()

            def close(self):
                pass

        env = {
            "MEMORY_GATEWAY_PORT": "18042",
            "MEMORY_GATEWAY_API_KEY": "synthetic-test-token",
            "MEMORY_GATEWAY_URL": "https://example.invalid",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(hook_script.http.client, "HTTPConnection", Connection):
            hook_script.query_local_gateway("synthetic query")

        self.assertEqual(connections[0], ("127.0.0.1", 18000, 1.0))
        self.assertEqual(connections[1][1], hook_script.ENDPOINT)

    def test_optional_hook_round_trips_to_local_gateway_without_provider_calls(self):
        previous_api_key = server.API_KEY
        server.API_KEY = "synthetic-hook-token"
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        port = str(httpd.server_address[1])
        settings = {
            "MEMORY_GATEWAY_API_KEY": "synthetic-hook-token",
        }
        try:
            with (
                patch.object(hook_script, "_local_setting", side_effect=lambda key: settings.get(key, "")),
                patch.object(hook_script, "GATEWAY_PORT", int(port)),
                patch.object(server, "embed_text", side_effect=AssertionError("embedding path used")),
                patch.object(server, "request_json", side_effect=AssertionError("external HTTP service called")),
            ):
                result = hook_script.process_hook_payload(
                    {"hook_event_name": "UserPromptSubmit", "prompt": "Which telescope project uses the cedar mount?"},
                    hook_script.query_local_gateway,
                )
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
            server.API_KEY = previous_api_key

        self.assertEqual(result["continue"], True)
        injected = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("The telescope project uses a cedar mount", injected)
        self.assertNotIn("synthetic-active", str(result))


if __name__ == "__main__":
    unittest.main()
