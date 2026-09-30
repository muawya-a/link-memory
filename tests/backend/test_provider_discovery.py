"""No-inference OpenAI-compatible provider discovery contract."""

from __future__ import annotations

import io
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "gateway"))

import provider_discovery


class ProviderDiscoveryTests(unittest.TestCase):
    def test_classifies_empty_single_and_multi_model_catalogs(self):
        self.assertEqual(provider_discovery.classify_catalog({"data": []})["kind"], "empty_catalog")
        one = provider_discovery.classify_catalog({"data": [{"id": "local-model", "secret": "drop"}]})
        self.assertEqual(one["kind"], "single_model_catalog")
        self.assertEqual(one["models"], [{"id": "local-model"}])
        self.assertEqual(provider_discovery.classify_catalog({"data": [{"id": "a"}, {"id": "b"}]})["kind"], "model_catalog")

    def test_rejects_unknown_or_incompatible_payloads(self):
        self.assertEqual(provider_discovery.classify_catalog({"models": [{"name": "x"}]})["kind"], "unknown")
        with patch.object(provider_discovery, "urlopen_no_proxy_redirects", return_value=io.BytesIO(b'{"models":[]}')):
            with self.assertRaisesRegex(ValueError, "provider_catalog_not_openai_compatible"):
                provider_discovery.discover_openai_compatible_models("http://127.0.0.1:1234/v1")

    def test_discovery_only_sends_get_models_and_request_scoped_bearer_key(self):
        response = io.BytesIO(json.dumps({"data": [{"id": "synthetic-model"}]}).encode())
        with patch.object(provider_discovery, "urlopen_no_proxy_redirects", return_value=response) as opener:
            result = provider_discovery.discover_openai_compatible_models("http://127.0.0.1:1234/v1/", "synthetic-key")
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:1234/v1/models")
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-key")
        self.assertEqual(opener.call_args.kwargs["timeout"], 8)
        self.assertEqual(result["endpoint_kind"], "openai_compatible_models")
        self.assertNotIn("api_key", result)

    def test_never_posts_inference_content_during_discovery(self):
        with patch.object(provider_discovery, "urlopen_no_proxy_redirects", return_value=io.BytesIO(b'{"data":[]}')) as opener:
            provider_discovery.discover_openai_compatible_models("http://localhost:1234")
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:1234/v1/models")
        self.assertEqual(request.method, "GET")
        self.assertIsNone(request.data)

    def test_rejects_base_urls_with_credentials_query_or_model_path(self):
        for value in (
            "https://user:pass@provider.example/v1",
            "https://provider.example/v1?key=secret",
            "https://provider.example/v1/models",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                provider_discovery.discover_openai_compatible_models(value)

    def test_catalog_response_size_is_bounded(self):
        with patch.object(provider_discovery, "urlopen_no_proxy_redirects", return_value=io.BytesIO(b"x" * (provider_discovery.MAX_CATALOG_BYTES + 1))):
            with self.assertRaisesRegex(ValueError, "provider_catalog_too_large"):
                provider_discovery.discover_openai_compatible_models("http://localhost:1234/v1")

    def test_loopback_discovery_performs_only_models_get(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.command, self.path, self.headers.get("Authorization")))
                body = b'{"data":[{"id":"local-synthetic"}]}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                requests.append((self.command, self.path, None))
                self.send_error(405)

            def log_message(self, _format, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = provider_discovery.discover_openai_compatible_models(
                f"http://127.0.0.1:{server.server_port}/v1",
                "synthetic-key",
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
        self.assertEqual(result["models"], [{"id": "local-synthetic"}])
        self.assertEqual(requests, [("GET", "/v1/models", "Bearer synthetic-key")])


if __name__ == "__main__":
    unittest.main()
