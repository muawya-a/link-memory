"""Synthetic deny-by-default tests for database targets and internal listeners."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "gateway"))


class Neo4jTargetPolicyTests(unittest.TestCase):
    def test_allows_default_local_bolt_target(self):
        from network_policy import assert_neo4j_uri_allowed

        with patch.dict(os.environ, {"MEMORY_GATEWAY_NEO4J_ALLOWLIST": ""}, clear=False):
            self.assertEqual(
                assert_neo4j_uri_allowed("bolt://127.0.0.1:17687"),
                "bolt://127.0.0.1:17687",
            )

    def test_allows_only_exact_tls_remote_database_origin(self):
        from network_policy import assert_neo4j_uri_allowed

        uri = "bolt+s://graph.example.test:7687"
        with patch.dict(
            os.environ,
            {
                "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED": "true",
                "MEMORY_GATEWAY_NEO4J_ALLOWLIST": "bolt+s://graph.example.test:7687",
            },
            clear=False,
        ):
            self.assertEqual(assert_neo4j_uri_allowed(uri), uri)

    def test_denies_unencrypted_or_unlisted_remote_targets(self):
        from network_policy import assert_neo4j_uri_allowed

        with patch.dict(os.environ, {"MEMORY_GATEWAY_NEO4J_ALLOWLIST": ""}, clear=False):
            for uri in (
                "bolt://graph.example.test:7687",
                "bolt+s://graph.example.test:7687",
                "neo4j+s://graph.example.test:7687",
                "neo4j+s://localhost:7687",
                "neo4j://localhost:7687",
            ):
                with self.subTest(uri=uri), self.assertRaisesRegex(ValueError, "neo4j_destination_denied"):
                    assert_neo4j_uri_allowed(uri)

    def test_denies_remote_neo4j_even_when_allowlisted_without_remote_egress_opt_in(self):
        from network_policy import assert_neo4j_uri_allowed

        with patch.dict(os.environ, {
            "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED": "false",
            "MEMORY_GATEWAY_NEO4J_ALLOWLIST": "bolt+s://graph.example.test:7687",
        }, clear=False):
            with self.assertRaisesRegex(ValueError, "neo4j_destination_denied"):
                assert_neo4j_uri_allowed("bolt+s://graph.example.test:7687")

    def test_rejects_userinfo_fragments_and_malformed_allowlist_entries(self):
        from network_policy import assert_neo4j_uri_allowed

        with patch.dict(os.environ, {"MEMORY_GATEWAY_NEO4J_ALLOWLIST": "bolt+s://graph.example.test"}, clear=False):
            for uri in (
                "neo4j+s://user:test-user@example.invalid:7687",
                "neo4j+s://graph.example.test:7687#fragment",
                "bolt://localhost:7687?encrypted=false",
                "bolt+s://graph.example.test:0",
            ):
                with self.subTest(uri=uri), self.assertRaisesRegex(ValueError, "neo4j_destination_denied"):
                    assert_neo4j_uri_allowed(uri)
        with patch.dict(os.environ, {
            "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED": "true",
            "MEMORY_GATEWAY_NEO4J_ALLOWLIST": "bolt+s://bad.example.test/path",
        }, clear=False):
            with self.assertRaisesRegex(ValueError, "neo4j_allowlist_invalid"):
                assert_neo4j_uri_allowed("bolt+s://graph.example.test:7687")


class InternalListenerPolicyTests(unittest.TestCase):
    def test_allows_loopback_bind_addresses(self):
        from network_policy import assert_loopback_bind_host

        for host in ("127.0.0.1", "::1", "localhost"):
            with self.subTest(host=host):
                self.assertEqual(assert_loopback_bind_host(host), host)

    def test_denies_wildcard_and_remote_bind_addresses(self):
        from network_policy import assert_loopback_bind_host

        for host in ("0.0.0.0", "::", "192.0.2.10", "service.internal"):
            with self.subTest(host=host), self.assertRaisesRegex(ValueError, "internal_listener_must_be_loopback"):
                assert_loopback_bind_host(host)

    def test_gateway_bind_requires_an_ipv4_loopback_literal(self):
        from network_policy import assert_gateway_bind_host

        self.assertEqual(assert_gateway_bind_host("127.0.0.1"), "127.0.0.1")
        for host in ("::1", "localhost", "0.0.0.0", "192.0.2.10", "service.internal"):
            with self.subTest(host=host), self.assertRaisesRegex(ValueError, "gateway_listener_must_be_ipv4_loopback"):
                assert_gateway_bind_host(host)

    def test_safe_http_log_omits_request_target_and_query(self):
        from network_policy import safe_internal_http_log

        message = safe_internal_http_log(
            "Graphiti",
            ('"GET /v1/jobs?id=synthetic-sensitive-id HTTP/1.1"', 200, "-"),
        )
        self.assertEqual(message, "Graphiti HTTP status=200")
        self.assertNotIn("/v1/jobs", message)
        self.assertNotIn("synthetic-sensitive-id", message)


class GatewayBindEnforcementTests(unittest.TestCase):
    def test_gateway_bind_failure_prevents_queued_job_dispatch(self):
        project_root = Path(__file__).resolve().parents[2]
        script = textwrap.dedent(r"""
            import sys
            from pathlib import Path

            root = Path(sys.argv[1])
            sys.path.insert(0, str(root / "gateway"))
            import server

            server.HOST = "127.0.0.1"
            server.dispatch_queued_analysis_jobs = lambda: print("DISPATCHED")

            class BindFailure:
                def __init__(self, *args, **kwargs):
                    print("BIND_FAILED")
                    raise OSError("synthetic address in use")

            server.ThreadingHTTPServer = BindFailure
            try:
                server.main()
            except OSError as exc:
                print(f"bind_error:{exc}")
            else:
                print("NOT_BLOCKED")
        """)
        with tempfile.TemporaryDirectory(prefix="gateway-bind-failure-") as temporary:
            env = {
                key: os.environ[key]
                for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
                if key in os.environ
            }
            data_dir = Path(temporary) / "data"
            env.update({
                "PYTHONDONTWRITEBYTECODE": "1",
                "MEMORY_GATEWAY_DATA": str(data_dir),
                "MEMORY_GATEWAY_DB": str(data_dir / "gateway.sqlite3"),
                "MEMORY_GATEWAY_BACKUP_DIR": str(Path(temporary) / "backups"),
                "OPENMEMORY_ENABLED": "false",
                "GRAPHITI_ENABLED": "false",
                "MEMPALACE_ENABLED": "false",
                "OLLAMA_ENABLED": "false",
                "RERANKER_ENABLED": "false",
                "EMBEDDING_ENABLED": "false",
                "PROVIDER_RECALL_ENABLED": "false",
            })
            result = subprocess.run(
                [sys.executable, "-c", script, str(project_root)],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertIn("bind_error:synthetic address in use", result.stdout)
            self.assertNotIn("DISPATCHED", result.stdout)

    def test_gateway_refuses_unsupported_bind_hosts_before_startup_side_effects(self):
        project_root = Path(__file__).resolve().parents[2]
        script = textwrap.dedent(r"""
            import sys
            from pathlib import Path

            root = Path(sys.argv[1])
            sys.path.insert(0, str(root / "gateway"))
            import server

            server.HOST = sys.argv[2]
            server.dispatch_queued_analysis_jobs = lambda: print("DISPATCHED")

            class FakeThread:
                def __init__(self, *args, **kwargs): pass
                def start(self): pass

            class FakeServer:
                def __init__(self, *args, **kwargs): print("CONSTRUCTED")
                def serve_forever(self): print("SERVED")

            server.threading.Thread = FakeThread
            server.ThreadingHTTPServer = FakeServer
            try:
                server.main()
            except ValueError as exc:
                print(f"blocked:{exc}")
            else:
                print("NOT_BLOCKED")
        """)
        for host in ("0.0.0.0", "::1", "localhost", "192.0.2.10"):
            with self.subTest(host=host), tempfile.TemporaryDirectory(prefix="gateway-bind-policy-") as temporary:
                env = {
                    key: os.environ[key]
                    for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
                    if key in os.environ
                }
                data_dir = Path(temporary) / "data"
                env.update({
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "MEMORY_GATEWAY_DATA": str(data_dir),
                    "MEMORY_GATEWAY_DB": str(data_dir / "gateway.sqlite3"),
                    "MEMORY_GATEWAY_BACKUP_DIR": str(Path(temporary) / "backups"),
                    "MEMORY_GATEWAY_HOST": "127.0.0.1",
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
                result = subprocess.run(
                    [sys.executable, "-c", script, str(project_root), host],
                    cwd=project_root,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                self.assertIn("blocked:gateway_listener_must_be_ipv4_loopback", result.stdout)
                self.assertNotIn("DISPATCHED", result.stdout)
                self.assertNotIn("CONSTRUCTED", result.stdout)
                self.assertNotIn("SERVED", result.stdout)


if __name__ == "__main__":
    unittest.main()
