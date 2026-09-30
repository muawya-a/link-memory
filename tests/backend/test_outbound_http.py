"""Outbound stdlib HTTP must not silently proxy or follow redirects."""

from __future__ import annotations

import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "gateway"))


class OutboundHTTPPolicyTests(unittest.TestCase):
    def test_allows_loopback_http_and_exact_allowlisted_https_origin(self):
        from outbound_http import assert_outbound_url_allowed

        with patch.dict(os.environ, {
            "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED": "true",
            "MEMORY_GATEWAY_EGRESS_ALLOWLIST": "https://api.example.test",
        }, clear=False):
            assert_outbound_url_allowed("http://127.0.0.1:18000/v1/recall?q=synthetic")
            assert_outbound_url_allowed("https://api.example.test/v1/embeddings")

    def test_blocks_remote_egress_without_explicit_process_opt_in(self):
        from outbound_http import assert_outbound_url_allowed

        with patch.dict(os.environ, {
            "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED": "false",
            "MEMORY_GATEWAY_EGRESS_ALLOWLIST": "https://api.example.test",
        }, clear=False):
            assert_outbound_url_allowed("http://127.0.0.1:18000/v1/recall?q=synthetic")
            with self.assertRaisesRegex(ValueError, "outbound_destination_denied"):
                assert_outbound_url_allowed("https://api.example.test/v1/capture")

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "outbound_destination_denied"):
                assert_outbound_url_allowed("https://api.example.test/v1/capture")

        with patch.dict(os.environ, {
            "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED": "true",
            "MEMORY_GATEWAY_EGRESS_ALLOWLIST": "https://api.example.test",
        }, clear=False):
            assert_outbound_url_allowed("https://api.example.test/v1/capture")

    def test_http_transport_refuses_remote_payload_before_opening_network(self):
        from outbound_http import urlopen_no_proxy_redirects

        request = urllib.request.Request(
            "https://api.example.test/v1/capture",
            data=b"synthetic-memory-canary",
            method="POST",
        )
        with patch.dict(os.environ, {
            "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED": "false",
            "MEMORY_GATEWAY_EGRESS_ALLOWLIST": "https://api.example.test",
        }, clear=False), patch("urllib.request.build_opener") as opener_factory:
            with self.assertRaisesRegex(ValueError, "outbound_destination_denied"):
                urlopen_no_proxy_redirects(request, timeout=1)
            opener_factory.assert_not_called()

    def test_remote_openai_client_refuses_before_sdk_or_transport_creation(self):
        from outbound_http import create_restricted_async_openai_client

        with patch.dict(os.environ, {
            "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED": "false",
            "MEMORY_GATEWAY_EGRESS_ALLOWLIST": "https://api.example.test",
        }, clear=False):
            with self.assertRaisesRegex(ValueError, "outbound_destination_denied"):
                create_restricted_async_openai_client(
                    api_key="synthetic-key",
                    base_url="https://api.example.test/v1",
                    transport=object(),
                )

    def test_blocks_non_tls_remote_and_unlisted_https_before_network(self):
        from outbound_http import assert_outbound_url_allowed

        with patch.dict(os.environ, {"MEMORY_GATEWAY_EGRESS_ALLOWLIST": ""}, clear=False):
            with self.assertRaisesRegex(ValueError, "outbound_destination_denied"):
                assert_outbound_url_allowed("http://api.example.test/v1/capture")
            with self.assertRaisesRegex(ValueError, "outbound_destination_denied"):
                assert_outbound_url_allowed("https://api.example.test/v1/capture")

    def test_rejects_url_credentials_and_malformed_allowlist(self):
        from outbound_http import assert_outbound_url_allowed

        with patch.dict(os.environ, {"MEMORY_GATEWAY_EGRESS_ALLOWLIST": "https://api.example.test"}, clear=False):
            with self.assertRaisesRegex(ValueError, "outbound_destination_denied"):
                assert_outbound_url_allowed("https://test-user@example.invalid/v1/capture")
        with patch.dict(os.environ, {
            "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED": "true",
            "MEMORY_GATEWAY_EGRESS_ALLOWLIST": "api.example.test",
        }, clear=False):
            with self.assertRaisesRegex(ValueError, "outbound_allowlist_invalid"):
                assert_outbound_url_allowed("https://api.example.test/v1/capture")

    def test_ignores_ambient_proxy_environment(self):
        target_hits: list[bytes] = []
        proxy_hits: list[str] = []

        class TargetHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                target_hits.append(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *_args):
                pass

        class ProxyHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                proxy_hits.append(self.path)
                self.send_response(502)
                self.end_headers()

            def log_message(self, *_args):
                pass

        target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
        proxy = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
        threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (target, proxy)]
        for thread in threads:
            thread.start()
        try:
            with patch.dict(os.environ, {
                "HTTP_PROXY": f"http://127.0.0.1:{proxy.server_port}",
                "http_proxy": f"http://127.0.0.1:{proxy.server_port}",
                "ALL_PROXY": f"http://127.0.0.1:{proxy.server_port}",
                "all_proxy": f"http://127.0.0.1:{proxy.server_port}",
                "NO_PROXY": "",
                "no_proxy": "",
            }):
                from outbound_http import urlopen_no_proxy_redirects

                request = urllib.request.Request(
                    f"http://127.0.0.1:{target.server_port}/capture",
                    data=b"synthetic-payload",
                    method="POST",
                )
                with urlopen_no_proxy_redirects(request, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                    response.read()
            self.assertEqual(target_hits, [b"synthetic-payload"])
            self.assertEqual(proxy_hits, [])
        finally:
            for server in (target, proxy):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=3)

    def test_does_not_forward_payload_after_redirect(self):
        redirect_hits: list[bytes] = []

        class ReceiverHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                redirect_hits.append(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_args):
                pass

        receiver = ThreadingHTTPServer(("127.0.0.1", 0), ReceiverHandler)

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(307)
                self.send_header("Location", f"http://127.0.0.1:{receiver.server_port}/collect")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_args):
                pass

        redirector = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (receiver, redirector)]
        for thread in threads:
            thread.start()
        try:
            from outbound_http import urlopen_no_proxy_redirects

            request = urllib.request.Request(
                f"http://127.0.0.1:{redirector.server_port}/capture",
                data=b"synthetic-sensitive-payload",
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as error:
                urlopen_no_proxy_redirects(request, timeout=3)
            self.assertEqual(error.exception.code, 307)
            self.assertEqual(redirect_hits, [])
        finally:
            for server in (receiver, redirector):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
