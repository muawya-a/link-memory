"""Focused, side-effect-free contracts for the HTTP route dispatcher."""

from __future__ import annotations

import importlib
import os
from contextlib import redirect_stderr
from io import StringIO
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_PATH = PROJECT_ROOT / "gateway"
sys.path.insert(0, str(GATEWAY_PATH))
http_routes = importlib.import_module("http_routes")


class FakeHandler:
    def __init__(self, *, path="/", payload=None, authenticated=True):
        self.path = path
        self.payload = {} if payload is None else payload
        self.authenticated = authenticated
        self.client_address = ("127.0.0.1", 43210)
        self.events = []
        self.responses = []

    def read_json(self):
        self.events.append(("read_json",))
        return self.payload

    def send_json(self, body, status=200):
        self.events.append(("send_json", body, status))
        self.responses.append((body, status))


class FakeServices:
    """Dynamic service fake that records calls and returns stable sentinels."""

    def __init__(self, *, auth_ok=True, returns=None, errors=None):
        self.authenticated = auth_ok
        self.returns = returns or {}
        self.errors = errors or {}
        self.events = []

    def auth_ok(self, handler):
        self.events.append(("auth_ok", handler))
        return self.authenticated

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.events.append((name, *args) if not kwargs else (name, args, kwargs))
            if name in self.errors:
                raise self.errors[name]
            return self.returns.get(name, {"from": name})

        return call


def call_events(services):
    return [event[0] for event in services.events]


def clean_remember_route_import():
    """Probe route import in a fresh process that cannot import Gateway server."""
    code = textwrap.dedent(
        """
        import importlib.abc
        import sys

        class RejectGatewayServer(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in {"server", "gateway.server"}:
                    raise AssertionError("route import attempted to load Gateway server")
                return None

        sys.meta_path.insert(0, RejectGatewayServer())
        sys.path.insert(0, sys.argv[1])
        from routes import remember
        assert callable(remember.handle_remember)
        assert "server" not in sys.modules
        assert "gateway.server" not in sys.modules
        """
    )
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if key in os.environ
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="remember-route-import-") as temp:
        env["MEMORY_GATEWAY_DATA"] = str(Path(temp) / "data")
        env["MEMORY_GATEWAY_DB"] = str(Path(temp) / "data" / "gateway.sqlite3")
        env["MEMORY_GATEWAY_BACKUP_DIR"] = str(Path(temp) / "backups")
        return subprocess.run(
            [sys.executable, "-c", code, str(GATEWAY_PATH)],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


def clean_ingest_route_import():
    """Probe ingest import without server composition or database setup."""
    code = textwrap.dedent(
        """
        import importlib.abc
        import sqlite3
        import sys

        class RejectGatewayServer(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in {"server", "gateway.server"}:
                    raise AssertionError("route import attempted to load Gateway server")
                return None

        def reject_database_connect(*args, **kwargs):
            raise AssertionError("route import attempted to initialize a database")

        sqlite3.connect = reject_database_connect
        sys.meta_path.insert(0, RejectGatewayServer())
        sys.path.insert(0, sys.argv[1])
        from routes import ingest
        assert callable(ingest.handle_ingest)
        assert "server" not in sys.modules
        assert "gateway.server" not in sys.modules
        """
    )
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if key in os.environ
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="ingest-route-import-") as temp:
        env["MEMORY_GATEWAY_DATA"] = str(Path(temp) / "data")
        env["MEMORY_GATEWAY_DB"] = str(Path(temp) / "data" / "gateway.sqlite3")
        env["MEMORY_GATEWAY_BACKUP_DIR"] = str(Path(temp) / "backups")
        return subprocess.run(
            [sys.executable, "-c", code, str(GATEWAY_PATH)],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


class HttpRouteContractTests(unittest.TestCase):
    def test_ingest_route_module_is_directly_importable_without_server_or_database_setup(self):
        result = clean_ingest_route_import()
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_remember_route_module_is_directly_importable_without_loading_server(self):
        result = clean_remember_route_import()
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_clean_route_import_is_independent_of_parent_server_module(self):
        missing = object()
        previous_server = sys.modules.get("server", missing)
        sys.modules["server"] = types.ModuleType("server")
        try:
            result = clean_remember_route_import()
        finally:
            if previous_server is missing:
                sys.modules.pop("server", None)
            else:
                sys.modules["server"] = previous_server

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_extracted_remember_handler_preserves_domain_call_order_and_response(self):
        remember_route = importlib.import_module("routes.remember")
        handler = FakeHandler(payload={"text": "synthetic note", "conversation_id": "c-1"})
        services = FakeServices(returns={
            "hook_capture_allowed": True,
            "save_memory": {"id": "m-1"},
            "write_portable_archive": {"status": "written"},
        })

        remember_route.handle_remember(handler, services, handler.payload)

        self.assertEqual(call_events(services), [
            "hook_capture_allowed", "save_memory", "enqueue_memory_fanout", "write_portable_archive",
        ])
        self.assertEqual(services.events[0], ("hook_capture_allowed", "manual"))
        self.assertEqual(services.events[1], ("save_memory", handler.payload, "manual", "c-1", None))
        self.assertEqual(services.events[2], ("enqueue_memory_fanout", {"id": "m-1"}, "manual", "c-1", None))
        self.assertEqual(handler.responses, [({
            "status": "saved",
            "memory": {"id": "m-1"},
            "fanout": "queued",
            "archive": {"status": "written"},
        }, 201)])

    def test_extracted_remember_handler_keeps_capture_rejection_as_value_error(self):
        remember_route = importlib.import_module("routes.remember")
        handler = FakeHandler(payload={"source": "test"})
        services = FakeServices(returns={"hook_capture_allowed": False})

        with self.assertRaisesRegex(ValueError, "capture is disabled for this source"):
            remember_route.handle_remember(handler, services, handler.payload)

        self.assertEqual(call_events(services), ["hook_capture_allowed"])
        self.assertEqual(handler.responses, [])

    def test_unauthorized_get_is_rejected_before_any_service_dispatch(self):
        handler = FakeHandler(authenticated=False)
        services = FakeServices(auth_ok=False)

        http_routes.handle_get(handler, services, urlsplit("/v1/recall?q=secret"))

        self.assertEqual(call_events(services), ["auth_ok"])
        self.assertEqual(handler.responses, [({"error": "unauthorized"}, 401)])

    def test_health_unauthorized_is_rejected_before_database_or_provider_calls(self):
        handler = FakeHandler(authenticated=False)
        services = FakeServices(auth_ok=False)

        http_routes.handle_get(handler, services, urlsplit("/health"))

        self.assertEqual(call_events(services), ["auth_ok"])
        self.assertEqual(handler.responses, [({"error": "unauthorized"}, 401)])

    def test_get_recall_decodes_query_and_preserves_dispatch_and_response(self):
        handler = FakeHandler()
        services = FakeServices(returns={
            "unified_recall": ([{"id": "m-1"}], {"source": "fake"}),
            "provider_status": {"local": "ready"},
        })

        http_routes.handle_get(handler, services, urlsplit("/v1/recall?q=hello+world&type=event"))

        self.assertEqual(call_events(services), ["auth_ok", "unified_recall", "provider_status"])
        self.assertEqual(services.events[1], ("unified_recall", ("hello world",), {"kind": "event"}))
        self.assertEqual(handler.responses, [({
            "query": "hello world",
            "memories": [{"id": "m-1"}],
            "recall": {"source": "fake"},
            "providers": {"local": "ready"},
        }, 200)])

    def test_get_jobs_requires_id_without_dispatching_a_job_lookup(self):
        handler = FakeHandler()
        services = FakeServices()

        http_routes.handle_get(handler, services, urlsplit("/v1/jobs"))

        self.assertEqual(call_events(services), ["auth_ok"])
        self.assertEqual(handler.responses, [({"error": "id is required"}, 400)])

    def test_get_invalid_numeric_parameter_returns_safe_bad_request(self):
        sentinel = "private-query-sentinel"
        handler = FakeHandler(path=f"/v1/captures?limit={sentinel}")
        services = FakeServices()

        http_routes.handle_get_safely(handler, services, urlsplit(handler.path))

        self.assertEqual(handler.responses, [({"error": "invalid request"}, 400)])
        self.assertNotIn(sentinel, str(handler.responses))
        self.assertEqual(call_events(services), ["auth_ok"])

    def test_get_memory_list_and_advanced_search_validate_limit_at_route_boundary(self):
        sentinel = "private-filter-limit-sentinel"
        for path in (f"/v1/memories?limit={sentinel}", f"/v1/search/advanced?limit={sentinel}"):
            with self.subTest(path=path):
                handler = FakeHandler()
                services = FakeServices()
                http_routes.handle_get_safely(handler, services, urlsplit(path))
                self.assertEqual(handler.responses, [({"error": "invalid request"}, 400)])
                self.assertNotIn(sentinel, str(handler.responses))
                self.assertEqual(call_events(services), ["auth_ok"])

    def test_get_missing_job_preserves_not_found_semantics(self):
        handler = FakeHandler()
        services = FakeServices(errors={"analysis_job": ValueError("analysis job not found")})

        http_routes.handle_get_safely(handler, services, urlsplit("/v1/jobs?id=missing"))

        self.assertEqual(handler.responses, [({"error": "analysis job not found"}, 404)])

    def test_get_openrouter_catalog_maps_service_failure_to_503(self):
        handler = FakeHandler()
        services = FakeServices(errors={"openrouter_catalog": RuntimeError("upstream detail")})

        http_routes.handle_get(handler, services, urlsplit("/v1/openrouter/models?refresh=true"))

        self.assertEqual(call_events(services), ["auth_ok", "openrouter_catalog"])
        self.assertEqual(services.events[1], ("openrouter_catalog", True))
        self.assertEqual(handler.responses, [({"error": "model catalog unavailable"}, 503)])

    def test_provider_discovery_requires_auth_before_reading_secret_body(self):
        handler = FakeHandler(
            path="/v1/provider/discover",
            payload={"base_url": "https://provider.example/v1", "api_key": "synthetic-secret"},
            authenticated=False,
        )
        services = FakeServices(auth_ok=False)

        http_routes.handle_post(handler, services)

        self.assertEqual(call_events(services), ["auth_ok"])
        self.assertNotIn(("read_json",), handler.events)
        self.assertEqual(handler.responses, [({"error": "unauthorized"}, 401)])

    def test_provider_discovery_route_forwards_only_explicit_catalog_inputs(self):
        handler = FakeHandler(
            path="/v1/provider/discover",
            payload={"base_url": "http://127.0.0.1:11434/v1", "api_key": "synthetic-key"},
        )
        services = FakeServices(returns={"discover_openai_compatible_models": {"compatible": True, "kind": "single_model_catalog"}})

        http_routes.handle_post(handler, services)

        self.assertEqual(call_events(services), ["auth_ok", "discover_openai_compatible_models"])
        self.assertEqual(handler.events[0], ("read_json",))
        self.assertEqual(
            services.events[-1],
            ("discover_openai_compatible_models", "http://127.0.0.1:11434/v1", "synthetic-key"),
        )
        self.assertEqual(handler.responses, [({"compatible": True, "kind": "single_model_catalog"}, 200)])

    def test_unknown_get_route_authenticates_then_returns_not_found(self):
        handler = FakeHandler()
        services = FakeServices()

        http_routes.handle_get(handler, services, urlsplit("/v1/not-a-route"))

        self.assertEqual(call_events(services), ["auth_ok"])
        self.assertEqual(handler.responses, [({"error": "not found"}, 404)])

    def test_unauthorized_post_does_not_read_body_or_call_domain_service(self):
        handler = FakeHandler(path="/v1/remember", payload={"text": "private"})
        services = FakeServices(auth_ok=False)

        http_routes.handle_post(handler, services)

        self.assertEqual(call_events(services), ["auth_ok"])
        self.assertEqual(handler.events, [("send_json", {"error": "unauthorized"}, 401)])

    def test_remember_dispatches_in_order_and_returns_created_response(self):
        handler = FakeHandler(path="/v1/remember", payload={"text": "synthetic note", "conversation_id": "c-1"})
        services = FakeServices(returns={
            "hook_capture_allowed": True,
            "save_memory": {"id": "m-1"},
            "write_portable_archive": {"status": "written"},
        })

        http_routes.handle_post(handler, services)

        self.assertEqual(call_events(services), [
            "auth_ok", "hook_capture_allowed", "save_memory", "enqueue_memory_fanout", "write_portable_archive",
        ])
        self.assertEqual(handler.events[0], ("read_json",))
        self.assertEqual(services.events[1], ("hook_capture_allowed", "manual"))
        self.assertEqual(services.events[2], ("save_memory", handler.payload, "manual", "c-1", None))
        self.assertEqual(services.events[3], ("enqueue_memory_fanout", {"id": "m-1"}, "manual", "c-1", None))
        self.assertEqual(handler.responses, [({
            "status": "saved",
            "memory": {"id": "m-1"},
            "fanout": "queued",
            "archive": {"status": "written"},
        }, 201)])

    def test_post_value_error_becomes_bad_request_with_message(self):
        handler = FakeHandler(path="/v1/remember", payload={"source": "test"})
        services = FakeServices(returns={"hook_capture_allowed": False})

        http_routes.handle_post(handler, services)

        self.assertEqual(call_events(services), ["auth_ok", "hook_capture_allowed"])
        self.assertEqual(handler.responses, [({"error": "capture is disabled for this source"}, 400)])

    def test_capture_disabled_error_does_not_echo_source_value(self):
        sentinel = "private-source-sentinel"
        handler = FakeHandler(path="/v1/remember", payload={"source": sentinel})
        services = FakeServices(returns={"hook_capture_allowed": False})

        http_routes.handle_post(handler, services)

        self.assertEqual(handler.responses, [({"error": "capture is disabled for this source"}, 400)])
        self.assertNotIn(sentinel, str(handler.responses))

    def test_post_invalid_numeric_limit_does_not_echo_request_value(self):
        sentinel = "private-limit-sentinel"
        handler = FakeHandler(path="/v1/recall", payload={"query": "synthetic", "limit": sentinel})
        services = FakeServices()

        http_routes.handle_post(handler, services)

        self.assertEqual(handler.responses, [({"error": "limit must be an integer"}, 400)])
        self.assertNotIn(sentinel, str(handler.responses))
        self.assertEqual(call_events(services), ["auth_ok"])

    def test_permission_error_uses_internal_error_response_without_path(self):
        sentinel = r"C:\private\operator-home\secrets.sqlite3"
        handler = FakeHandler(path="/v1/backup", payload={})
        services = FakeServices(errors={"create_backup": PermissionError(f"access denied: {sentinel}")})
        stderr = StringIO()

        with redirect_stderr(stderr):
            http_routes.handle_post(handler, services)

        body, status = handler.responses[0]
        self.assertEqual(status, 500)
        self.assertEqual(body["error"], "internal error")
        self.assertRegex(body["error_id"], r"^[0-9a-f-]{36}$")
        self.assertNotIn(sentinel, str(body))
        self.assertNotIn(sentinel, stderr.getvalue())
        self.assertIn("PermissionError", stderr.getvalue())

    def test_ingest_authenticates_reads_payload_dispatches_and_returns_accepted(self):
        timeline = []
        payload = {"source": "fixture", "items": [{"text": "synthetic ingest item"}]}
        result = {"job_id": "job-1", "status": "queued"}

        class OrderedHandler(FakeHandler):
            def read_json(self):
                timeline.append("read_json")
                return super().read_json()

            def send_json(self, body, status=200):
                timeline.append("send_json")
                super().send_json(body, status)

        class IngestServices(FakeServices):
            def auth_ok(self, handler):
                timeline.append("auth_ok")
                return super().auth_ok(handler)

            def ingest(self, received_payload):
                timeline.append("ingest")
                self.events.append(("ingest", received_payload))
                return result

        handler = OrderedHandler(path="/v1/ingest?source=ignored", payload=payload)
        services = IngestServices()

        http_routes.handle_post(handler, services)

        self.assertEqual(timeline, ["auth_ok", "read_json", "ingest", "send_json"])
        self.assertEqual(call_events(services), ["auth_ok", "ingest"])
        self.assertIs(services.events[1][1], payload)
        self.assertEqual(handler.responses, [(result, 202)])

    def test_unauthorized_ingest_does_not_read_payload_or_dispatch(self):
        handler = FakeHandler(path="/v1/ingest", payload={"items": ["synthetic"]})
        services = FakeServices(auth_ok=False)

        http_routes.handle_post(handler, services)

        self.assertEqual(call_events(services), ["auth_ok"])
        self.assertEqual(handler.events, [("send_json", {"error": "unauthorized"}, 401)])
        self.assertEqual(handler.responses, [({"error": "unauthorized"}, 401)])

    def test_ingest_value_error_becomes_bad_request(self):
        handler = FakeHandler(path="/v1/ingest", payload={"source": "fixture"})
        services = FakeServices(errors={"ingest": ValueError("invalid ingest fixture")})

        http_routes.handle_post(handler, services)

        self.assertEqual(call_events(services), ["auth_ok", "ingest"])
        self.assertEqual(services.events[1], ("ingest", handler.payload))
        self.assertEqual(handler.responses, [({"error": "invalid ingest fixture"}, 400)])

    def test_ingest_unexpected_service_error_is_masked_as_internal_error(self):
        handler = FakeHandler(path="/v1/ingest", payload={"source": "fixture"})
        sentinel = "sentinel-private-provider-detail"
        services = FakeServices(errors={"ingest": RuntimeError(sentinel)})
        stderr = StringIO()

        with redirect_stderr(stderr):
            http_routes.handle_post(handler, services)

        self.assertEqual(call_events(services), ["auth_ok", "ingest"])
        body, status = handler.responses[0]
        self.assertEqual(status, 500)
        self.assertEqual(set(body), {"error", "error_id"})
        self.assertEqual(body["error"], "internal error")
        self.assertRegex(body["error_id"], r"^[0-9a-f-]{36}$")
        self.assertNotIn(sentinel, str(body))
        self.assertNotIn(sentinel, stderr.getvalue())
        self.assertIn(body["error_id"], stderr.getvalue())
        self.assertIn("RuntimeError", stderr.getvalue())

    def test_unknown_post_route_reads_payload_then_returns_not_found(self):
        handler = FakeHandler(path="/v1/not-a-route", payload={"ignored": True})
        services = FakeServices()

        http_routes.handle_post(handler, services)

        self.assertEqual(call_events(services), ["auth_ok"])
        self.assertEqual(handler.events, [
            ("read_json",),
            ("send_json", {"error": "not found"}, 404),
        ])

    def test_post_unexpected_service_error_is_masked_as_internal_error(self):
        handler = FakeHandler(path="/v1/backup", payload={})
        services = FakeServices(errors={"create_backup": RuntimeError("sensitive internal detail")})

        with redirect_stderr(StringIO()):
            http_routes.handle_post(handler, services)

        self.assertEqual(call_events(services), ["auth_ok", "create_backup"])
        body, status = handler.responses[0]
        self.assertEqual(status, 500)
        self.assertEqual(set(body), {"error", "error_id"})
        self.assertEqual(body["error"], "internal error")
        self.assertRegex(body["error_id"], r"^[0-9a-f-]{36}$")
        self.assertNotIn("sensitive internal detail", str(body))


if __name__ == "__main__":
    unittest.main()
