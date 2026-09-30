"""Public error responses must not expose provider or parser exception text."""

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


def run_isolated(root: Path, code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code), str(PROJECT_ROOT)],
        cwd=PROJECT_ROOT,
        env=isolated_env(root),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


class PublicErrorRedactionTests(unittest.TestCase):
    def test_remote_content_paths_do_not_open_transport_without_egress_opt_in(self):
        with tempfile.TemporaryDirectory(prefix="remote-content-egress-denied-") as directory:
            result = run_isolated(Path(directory), r'''
                import os
                import sys
                from pathlib import Path
                from unittest.mock import patch

                root = Path(sys.argv[1])
                sys.path.insert(0, str(root / "gateway"))
                # An allowlist alone is not permission to send content.
                os.environ.pop("MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED", None)
                os.environ["MEMORY_GATEWAY_EGRESS_ALLOWLIST"] = ",".join((
                    "https://openmemory.example.invalid",
                    "https://graphiti.example.invalid",
                    "https://mempalace.example.invalid",
                    "https://ollama.example.invalid",
                    "https://reranker.example.invalid",
                ))
                import server

                server.OPENMEMORY_URL = "https://openmemory.example.invalid"
                server.OPENMEMORY_ENABLED = True
                server.GRAPHITI_URL = "https://graphiti.example.invalid"
                server.GRAPHITI_ENABLED = True
                server.MEMPALACE_URL = "https://mempalace.example.invalid"
                server.MEMPALACE_ENABLED = True
                server.PROVIDER_RECALL_ENABLED = True
                server.OLLAMA_URL = "https://ollama.example.invalid"
                server.OLLAMA_ENABLED = True
                server.EMBEDDING_ENABLED = True
                server.RERANKER_URL = "https://reranker.example.invalid"
                server.RERANKER_ENABLED = True
                server.analysis_is_paused = lambda: False

                outbound_attempts = []
                original_outbound = server.urlopen_no_proxy_redirects
                def capture_guarded_outbound(request, timeout=None):
                    outbound_attempts.append(request.full_url)
                    return original_outbound(request, timeout=timeout)

                with patch("urllib.request.build_opener") as opener_factory, patch.object(
                    server, "urlopen_no_proxy_redirects", side_effect=capture_guarded_outbound,
                ):
                    item = server.save_memory(
                        {"text": "synthetic outbound privacy canary"},
                        "synthetic-egress-test", "synthetic-egress-session", None,
                    )
                    fanout = server.fanout_memory(item, "synthetic-egress-test", "synthetic-egress-session", None)
                    recalled, trace = server.provider_recall("synthetic outbound query")
                    embedding = server.embed_text("synthetic embedding canary")
                    searched = server.search_memories("synthetic outbound privacy canary", limit=5, rerank=True)

                assert opener_factory.call_count == 0, opener_factory.call_args_list
                attempted_destinations = {(url.split("/", 3)[2], "/" + url.split("/", 3)[3]) for url in outbound_attempts}
                assert ("openmemory.example.invalid", "/v1/ingest") in attempted_destinations, attempted_destinations
                assert ("graphiti.example.invalid", "/v1/ingest") in attempted_destinations, attempted_destinations
                assert ("mempalace.example.invalid", "/v1/ingest") in attempted_destinations, attempted_destinations
                assert ("openmemory.example.invalid", "/v1/recall") in attempted_destinations, attempted_destinations
                assert ("graphiti.example.invalid", "/v1/search") in attempted_destinations, attempted_destinations
                assert ("mempalace.example.invalid", "/v1/search") in attempted_destinations, attempted_destinations
                assert any(host == "ollama.example.invalid" and path.startswith("/api/embed") for host, path in attempted_destinations), attempted_destinations
                assert ("reranker.example.invalid", "/v1/rerank") in attempted_destinations, attempted_destinations
                assert fanout.get("openmemory_error") == "provider_request_failed", fanout
                assert fanout.get("graphiti_error") == "provider_request_failed", fanout
                assert fanout.get("mempalace_error") == "provider_request_failed", fanout
                assert all(value == "provider_request_failed" for value in trace["errors"].values()), trace
                assert recalled == [], recalled
                assert embedding == [], embedding
                assert any(memory["id"] == item["id"] for memory in searched), searched
            ''')
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_invalid_confidence_value_is_not_echoed_to_the_http_validation_error(self):
        with tempfile.TemporaryDirectory(prefix="confidence-error-redaction-") as directory:
            result = run_isolated(Path(directory), r'''
                import sys
                from pathlib import Path

                root = Path(sys.argv[1])
                sys.path.insert(0, str(root / "gateway"))
                import server

                sentinel = "sensitive-confidence-value"
                try:
                    server.save_memory({"text": "synthetic", "confidence": sentinel}, "manual", None, None)
                except ValueError as exc:
                    assert str(exc) == "confidence must be a number", str(exc)
                    assert sentinel not in str(exc)
                else:
                    raise AssertionError("invalid confidence should be rejected")
            ''')
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_invalid_content_length_is_not_echoed_in_http_error(self):
        with tempfile.TemporaryDirectory(prefix="content-length-error-redaction-") as directory:
            result = run_isolated(Path(directory), r'''
                import io
                import json
                import sys
                from pathlib import Path

                root = Path(sys.argv[1])
                sys.path.insert(0, str(root / "gateway"))
                import server
                import http_routes

                sentinel = "private-content-length-sentinel"
                class FakeRequest:
                    path = "/v1/remember"
                    client_address = ("127.0.0.1", 43210)
                    headers = {"Content-Length": sentinel}
                    rfile = io.BytesIO(b"")
                    def read_json(self): return server.Handler.read_json(self)
                    def send_json(self, body, status=200): self.body, self.status = body, status
                class FakeServices:
                    def auth_ok(self, _handler): return True
                request = FakeRequest()
                http_routes.handle_post(request, FakeServices())
                assert request.status == 400, request.status
                assert request.body == {"error": "invalid Content-Length"}, request.body
                assert sentinel not in json.dumps(request.body), request.body
            ''')
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_loopback_provider_receives_redacted_payload(self):
        with tempfile.TemporaryDirectory(prefix="provider-egress-redaction-") as directory:
            result = run_isolated(Path(directory), r'''
                import json
                import sys
                import threading
                from http.server import BaseHTTPRequestHandler, HTTPServer
                from pathlib import Path

                root = Path(sys.argv[1])
                sys.path.insert(0, str(root / "gateway"))
                import server

                received = []
                class CaptureHandler(BaseHTTPRequestHandler):
                    def do_POST(self):
                        length = int(self.headers.get("Content-Length", "0"))
                        received.append((self.path, json.loads(self.rfile.read(length).decode("utf-8"))))
                        body = b'{"status":"stored"}'
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    def log_message(self, *_args):
                        pass

                receiver = HTTPServer(("127.0.0.1", 0), CaptureHandler)
                thread = threading.Thread(target=receiver.serve_forever, daemon=True)
                thread.start()
                server.analysis_is_paused = lambda: False
                server.OPENMEMORY_URL = f"http://127.0.0.1:{receiver.server_port}"
                server.OPENMEMORY_ENABLED = True
                server.GRAPHITI_URL = server.MEMPALACE_URL = ""
                server.GRAPHITI_ENABLED = server.MEMPALACE_ENABLED = False
                secret = "sk-" + "S" * 28
                email = "test-user@example.invalid"
                item = server.save_memory(
                    {"text": f"A synthetic memory containing {secret} and {email}"},
                    "synthetic-source", "synthetic-conversation", None,
                )
                outcome = server.fanout_memory(item, "synthetic-source", "synthetic-conversation", None)
                receiver.shutdown()
                receiver.server_close()
                thread.join(timeout=2)

                assert outcome.get("openmemory") == {"status": "stored"}, outcome
                assert received and received[0][0] == "/v1/ingest", received
                body = json.dumps(received[0][1], ensure_ascii=False)
                assert secret not in body, body
                assert "[REDACTED:openai_key]" in body, body
                assert email not in body, body
                assert "[REDACTED:email]" in body, body
            ''')
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_openrouter_rate_limit_keeps_bounded_diagnostic_code(self):
        with tempfile.TemporaryDirectory(prefix="openrouter-error-code-") as directory:
            result = run_isolated(Path(directory), r'''
                import io
                import sys
                import urllib.error
                from pathlib import Path

                root = Path(sys.argv[1])
                sys.path.insert(0, str(root / "gateway"))
                import server

                server.OPENROUTER_URL = "https://provider.example"
                server.openrouter_model_is_free = lambda _model: True
                server.urlopen_no_proxy_redirects = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    urllib.error.HTTPError("https://provider.example/chat", 429, "quota-secret", {}, io.BytesIO(b"body-secret"))
                )
                try:
                    server._openrouter_request("chat/completions", method="POST", payload={"model": "free"})
                except ValueError as exc:
                    assert server.safe_error_code(exc) == "openrouter_rate_limited", server.safe_error_code(exc)
                    assert getattr(exc, "status_code", None) == 429
                    assert "quota-secret" not in str(exc) and "body-secret" not in str(exc)
                else:
                    raise AssertionError("synthetic rate limit should be surfaced")
            ''')
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_analysis_backend_exception_text_is_not_returned_or_persisted(self):
        with tempfile.TemporaryDirectory(prefix="analysis-error-redaction-") as directory:
            result = run_isolated(Path(directory), r'''
                import json
                import sys
                from pathlib import Path

                root = Path(sys.argv[1])
                sys.path.insert(0, str(root / "gateway"))
                import server

                sentinel = "sentinel-private-provider-detail"
                def fail_analysis(*_args, **_kwargs):
                    raise server.AnalysisBackendError(sentinel)
                server.analyze_with_ollama = fail_analysis
                outcome = server.process_document({
                    "source": "synthetic-source",
                    "conversation_id": "synthetic-conversation",
                    "text": "Synthetic document content for the error path.",
                })
                assert outcome["status"] == "queued", outcome
                assert sentinel not in json.dumps(outcome), outcome
                with server.DB_LOCK:
                    persisted = {
                        "analysis_jobs": [dict(row) for row in server.DB.execute("SELECT * FROM analysis_jobs")],
                        "raw_documents": [dict(row) for row in server.DB.execute("SELECT * FROM raw_documents")],
                        "capture_events": [dict(row) for row in server.DB.execute("SELECT * FROM capture_events")],
                    }
                assert sentinel not in json.dumps(persisted), persisted
                assert "analysis_backend_error" in json.dumps(persisted), persisted

                preview = server.preview_document({"source": "synthetic-source", "text": "Synthetic preview content."})
                assert preview["fallback_reason"] == "analysis_backend_error", preview
                assert sentinel not in json.dumps(preview), preview

                def fail_probe(*_args, **_kwargs):
                    raise RuntimeError(sentinel)
                server.OPENMEMORY_URL = "http://127.0.0.1:1"
                server.PROVIDER_RECALL_ENABLED = True
                server.OPENMEMORY_ENABLED = True
                server.request_json = fail_probe
                _items, trace = server.provider_recall("synthetic query")
                assert trace["errors"].get("openmemory") == "processing_error", trace
                assert sentinel not in json.dumps(trace), trace

                server.get_json = fail_probe
                report = server.performance_report()
                assert all(sentinel not in json.dumps(service) for service in report["services"]), report
                assert next(service for service in report["services"] if service["service"] == "OpenMemory")["error"] == "processing_error", report
            ''')
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_background_retry_logs_do_not_include_raw_exception_text(self):
        with tempfile.TemporaryDirectory(prefix="worker-error-redaction-") as directory:
            result = run_isolated(Path(directory), r'''
                import contextlib
                import io
                import sys
                from pathlib import Path

                root = Path(sys.argv[1])
                sys.path.insert(0, str(root / "gateway"))
                import server

                sentinel = "sentinel-private-provider-detail"
                def fail():
                    raise RuntimeError(sentinel)
                def stop_worker(*_args):
                    raise StopIteration()

                server.retry_stale_queued_links_once = fail
                server.time.sleep = stop_worker
                retry_log = io.StringIO()
                with contextlib.redirect_stdout(retry_log):
                    try:
                        server.retry_worker()
                    except StopIteration:
                        pass
                assert sentinel not in retry_log.getvalue(), retry_log.getvalue()
                assert "RuntimeError" in retry_log.getvalue(), retry_log.getvalue()
                assert "retry worker error" in retry_log.getvalue(), retry_log.getvalue()

                server.retry_pending_portable_archive_once = lambda: False
                server.dispatch_queued_analysis_jobs = fail
                analysis_log = io.StringIO()
                with contextlib.redirect_stdout(analysis_log):
                    try:
                        server.analysis_retry_worker()
                    except StopIteration:
                        pass
                assert sentinel not in analysis_log.getvalue(), analysis_log.getvalue()
                assert "RuntimeError" in analysis_log.getvalue(), analysis_log.getvalue()
                assert "analysis retry worker error" in analysis_log.getvalue(), analysis_log.getvalue()
            ''')
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_reranker_model_exception_is_not_returned_to_http_caller(self):
        with tempfile.TemporaryDirectory(prefix="reranker-error-redaction-") as directory:
            result = run_isolated(Path(directory), r'''
                import importlib.util
                import io
                import json
                import sys
                import types
                from pathlib import Path
                from contextlib import redirect_stdout

                root = Path(sys.argv[1])
                torch = types.ModuleType("torch")
                torch.cuda = types.SimpleNamespace(is_available=lambda: False)
                class CrossEncoder:
                    def __init__(self, *args, **kwargs): pass
                    def rank(self, *args, **kwargs): raise RuntimeError("sentinel-private-provider-detail")
                sentence_transformers = types.ModuleType("sentence_transformers")
                sentence_transformers.CrossEncoder = CrossEncoder
                sys.modules["torch"] = torch
                sys.modules["sentence_transformers"] = sentence_transformers
                spec = importlib.util.spec_from_file_location("reranker_under_test", root / "gateway" / "reranker_server.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                class FakeHandler:
                    def __init__(self):
                        self.path = "/v1/rerank"
                        self.headers = {"Content-Length": "38"}
                        self.rfile = io.BytesIO(b'{"query":"q","documents":["d"]}')
                        self.wfile = io.BytesIO()
                        self.status = None
                    def send_response(self, status): self.status = status
                    def send_header(self, *_args): pass
                    def end_headers(self): pass

                handler = FakeHandler()
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    module.Handler.do_POST(handler)
                body = json.loads(handler.wfile.getvalue().decode("utf-8"))
                assert handler.status == 500, handler.status
                assert body.get("error") == "reranker failed", body
                assert body.get("error_id"), body
                assert "sentinel-private-provider-detail" not in json.dumps(body)
                assert "sentinel-private-provider-detail" not in stdout.getvalue()

                module.MODEL.rank = lambda *_args, **_kwargs: [{"corpus_id": 0, "score": 0.9}]
                success = FakeHandler()
                module.Handler.do_POST(success)
                success_body = json.loads(success.wfile.getvalue().decode("utf-8"))
                assert success.status == 200, success.status
                assert success_body == {"query": "q", "device": "cpu", "ranking": [{"corpus_id": 0, "score": 0.9}]}, success_body

                module.MODEL.rank = lambda *_args, **_kwargs: [object()]
                malformed = FakeHandler()
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    module.Handler.do_POST(malformed)
                malformed_body = json.loads(malformed.wfile.getvalue().decode("utf-8"))
                assert malformed.status == 500, malformed.status
                assert malformed_body.get("error") == "reranker failed", malformed_body
                assert malformed_body.get("error_id"), malformed_body
                assert "object at 0x" not in json.dumps(malformed_body)
            ''')
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_pdf_and_docx_parser_exceptions_are_not_returned_by_import(self):
        with tempfile.TemporaryDirectory(prefix="import-error-redaction-") as directory:
            result = run_isolated(Path(directory), r'''
                import base64
                import json
                import sys
                import types
                from pathlib import Path

                root = Path(sys.argv[1])
                sys.path.insert(0, str(root / "gateway"))
                fitz = types.ModuleType("fitz")
                def fail_open(*args, **kwargs): raise RuntimeError("sentinel-private-parser-detail")
                fitz.open = fail_open
                sys.modules["fitz"] = fitz
                import server
                import http_routes

                encoded = base64.b64encode(b"synthetic invalid document").decode("ascii")
                files = [
                    {"name": r"C:\Users\PublicTester\\\fixture.pdf", "type": "application/pdf", "data": encoded},
                    {"name": r"C:\Users\PublicTester\\\fixture.docx", "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "data": encoded},
                ]
                for item, expected in zip(files, (
                    "could not extract PDF text from fixture.pdf",
                    "could not extract Word text from fixture.docx",
                )):
                    try:
                        server.extract_uploaded_file(item)
                    except ValueError as exc:
                        assert str(exc) == expected, str(exc)
                    else:
                        raise AssertionError(f"{item['name']} unexpectedly parsed")

                class FakeHandler:
                    path = "/v1/import"
                    client_address = ("127.0.0.1", 43210)
                    def read_json(self): return {"files": files}
                    def send_json(self, body, status=200):
                        self.body, self.status = body, status
                class FakeServices:
                    def auth_ok(self, _handler): return True
                    def import_batch(self, payload): return server.import_batch(payload)

                handler = FakeHandler()
                http_routes.handle_post(handler, FakeServices())
                assert handler.status == 400, handler.status
                assert handler.body == {"error": "could not extract PDF text from fixture.pdf"}, handler.body
                assert "sentinel-private-parser-detail" not in json.dumps(handler.body)
                assert "sentinel-private-local-path" not in json.dumps(handler.body)

                _text, metadata = server.extract_uploaded_file({
                    "name": r"C:\Users\PublicTester\\\fixture.txt",
                    "data": base64.b64encode(b"synthetic text").decode("ascii"),
                })
                assert metadata["filename"] == "fixture.txt", metadata
            ''')
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
