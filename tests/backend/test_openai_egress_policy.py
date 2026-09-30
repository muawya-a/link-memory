"""Synthetic checks for the optional OpenAI-compatible SDK egress boundary."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "gateway"))

try:
    import httpx
except ImportError:
    httpx = None


@unittest.skipUnless(
    importlib.util.find_spec("openai") and httpx and importlib.util.find_spec("graphiti_core"),
    "optional Graphiti/OpenAI SDK dependencies are not installed",
)
class OpenAIEgressPolicyTests(unittest.TestCase):
    def test_graphiti_provider_error_filter_removes_provider_exception_text(self):
        from graphiti_service import _GraphitiProviderErrorFilter

        record = logging.LogRecord(
            "graphiti_core.llm_client.openai_generic_client",
            logging.ERROR,
            __file__,
            1,
            "provider failed: %s",
            ("synthetic-sensitive-response",),
            (RuntimeError, RuntimeError("synthetic-sensitive-response"), None),
        )
        self.assertTrue(_GraphitiProviderErrorFilter().filter(record))
        self.assertEqual(record.getMessage(), "Graphiti provider request failed")
        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.exc_text)

    def test_graphiti_denies_unapproved_neo4j_before_client_or_driver_creation(self):
        import graphiti_service

        graphiti_service.ready = False
        graphiti_service.graph = None
        graphiti_service.init_error = None
        with (
            patch.dict(os.environ, {"MEMORY_GATEWAY_NEO4J_ALLOWLIST": ""}, clear=False),
            patch.object(graphiti_service, "OPENROUTER_BASE", "http://127.0.0.1:18099/v1"),
            patch.object(graphiti_service, "OLLAMA_BASE", "http://127.0.0.1:11435/v1"),
            patch.object(graphiti_service, "NEO4J_URI", "bolt://neo4j.example.test:7687"),
            patch.object(graphiti_service, "create_restricted_async_openai_client") as openai_factory,
            patch.object(graphiti_service, "Graphiti") as graphiti_factory,
        ):
            asyncio.run(graphiti_service.initialize())

        openai_factory.assert_not_called()
        graphiti_factory.assert_not_called()
        self.assertFalse(graphiti_service.ready)
        self.assertIsNone(graphiti_service.graph)
        self.assertEqual(graphiti_service.init_error, "graphiti_initialization_failed")

    def test_graphiti_listener_rejects_nonloopback_before_starting(self):
        import graphiti_service

        with (
            patch.object(graphiti_service, "HOST", "0.0.0.0"),
            patch.object(graphiti_service, "ThreadingHTTPServer") as server_factory,
            self.assertRaisesRegex(ValueError, "internal_listener_must_be_loopback"),
        ):
            graphiti_service.main()
        server_factory.assert_not_called()

    def test_graphiti_http_access_log_omits_caller_request_target(self):
        import graphiti_service

        handler = object.__new__(graphiti_service.Handler)
        with patch("builtins.print") as print_mock:
            handler.log_message(
                '"%s" %s %s',
                "GET /v1/jobs?id=synthetic-sensitive-id HTTP/1.1",
                "200",
                "-",
            )

        print_mock.assert_called_once_with("Graphiti HTTP status=200", flush=True)

    def test_graphiti_clients_share_only_restricted_sdk_clients(self):
        from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
        from outbound_http import create_restricted_async_openai_client

        with patch.dict(os.environ, {
            "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED": "true",
            "MEMORY_GATEWAY_EGRESS_ALLOWLIST": "https://llm.example.test,https://embed.example.test",
        }, clear=False):
            llm_sdk = create_restricted_async_openai_client(api_key="synthetic-key", base_url="https://llm.example.test/v1")
            embed_sdk = create_restricted_async_openai_client(api_key="synthetic-key", base_url="https://embed.example.test/v1")
            llm_config = LLMConfig(api_key="synthetic-key", model="synthetic", small_model="synthetic", base_url="https://llm.example.test/v1")
            generic_llm = OpenAIGenericClient(config=llm_config, client=llm_sdk, structured_output_mode="json_object")
            embedder = OpenAIEmbedder(
                config=OpenAIEmbedderConfig(api_key="synthetic-key", embedding_model="synthetic", embedding_dim=1, base_url="https://embed.example.test/v1"),
                client=embed_sdk,
            )
            reranker = OpenAIRerankerClient(config=llm_config, client=llm_sdk)
            try:
                self.assertIs(generic_llm.client, llm_sdk)
                self.assertIs(embedder.client, embed_sdk)
                self.assertIs(reranker.client, llm_sdk)
            finally:
                asyncio.run(llm_sdk.close())
                asyncio.run(embed_sdk.close())

    def test_graphiti_llm_embedder_and_reranker_calls_use_restricted_transport(self):
        from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
        from graphiti_core.prompts.models import Message
        from outbound_http import create_restricted_async_openai_client

        seen: list[tuple[str, str, dict]] = []

        async def handler(request):
            body = __import__("json").loads(request.content or b"{}")
            seen.append((request.url.host, request.url.path, body))
            if request.url.path.endswith("/embeddings"):
                payload = {
                    "object": "list",
                    "data": [{"object": "embedding", "index": 0, "embedding": [0.25, 0.75]}],
                    "model": "synthetic",
                }
            elif body.get("logprobs"):
                payload = {
                    "id": "synthetic-reranker",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "synthetic",
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": "True"},
                        "finish_reason": "stop",
                        "logprobs": {"content": [{
                            "token": "True",
                            "logprob": -0.1,
                            "bytes": [84, 114, 117, 101],
                            "top_logprobs": [{"token": "True", "logprob": -0.1, "bytes": [84, 114, 117, 101]}],
                        }]},
                    }],
                }
            else:
                payload = {
                    "id": "synthetic-llm",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "synthetic",
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": "{}"},
                        "finish_reason": "stop",
                    }],
                }
            return httpx.Response(200, json=payload)

        with patch.dict(os.environ, {
            "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED": "true",
            "MEMORY_GATEWAY_EGRESS_ALLOWLIST": "https://llm.example.test,https://embed.example.test",
        }, clear=False):
            transport = httpx.MockTransport(handler)
            llm_sdk = create_restricted_async_openai_client(
                api_key="synthetic-key", base_url="https://llm.example.test/v1", transport=transport,
            )
            embed_sdk = create_restricted_async_openai_client(
                api_key="synthetic-key", base_url="https://embed.example.test/v1", transport=transport,
            )
            config = LLMConfig(
                api_key="synthetic-key", model="synthetic", small_model="synthetic",
                base_url="https://llm.example.test/v1",
            )
            generic_llm = OpenAIGenericClient(config=config, client=llm_sdk, structured_output_mode="json_object")
            embedder = OpenAIEmbedder(
                config=OpenAIEmbedderConfig(
                    api_key="synthetic-key", embedding_model="synthetic", embedding_dim=2,
                    base_url="https://embed.example.test/v1",
                ),
                client=embed_sdk,
            )
            reranker = OpenAIRerankerClient(config=config, client=llm_sdk)

            async def exercise_wrappers():
                try:
                    llm_result = await generic_llm.generate_response([Message(role="user", content="synthetic query")])
                    embedding = await embedder.create("synthetic memory")
                    ranking = await reranker.rank("synthetic query", ["synthetic passage"])
                    return llm_result, embedding, ranking
                finally:
                    await llm_sdk.close()
                    await embed_sdk.close()

            llm_result, embedding, ranking = asyncio.run(exercise_wrappers())

        self.assertEqual(llm_result, {})
        self.assertEqual(embedding, [0.25, 0.75])
        self.assertEqual(len(ranking), 1)
        self.assertEqual({(host, path) for host, path, _body in seen}, {
            ("llm.example.test", "/v1/chat/completions"),
            ("embed.example.test", "/v1/embeddings"),
        })
        self.assertTrue(all(host in {"llm.example.test", "embed.example.test"} for host, _path, _body in seen))

    def test_unapproved_https_origin_is_rejected_before_transport(self):
        from outbound_http import create_restricted_async_openai_client

        sent: list[str] = []

        async def handler(request):
            sent.append(str(request.url))
            return httpx.Response(200, json={})

        with patch.dict(os.environ, {
            "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED": "true",
            "MEMORY_GATEWAY_EGRESS_ALLOWLIST": "https://approved.example.test",
        }, clear=False):
            with self.assertRaisesRegex(ValueError, "outbound_destination_denied"):
                create_restricted_async_openai_client(
                    api_key="synthetic-key",
                    base_url="https://unapproved.example.test/v1",
                    transport=httpx.MockTransport(handler),
                )
        self.assertEqual(sent, [])

    def test_redirect_receiver_is_never_contacted(self):
        from outbound_http import create_restricted_async_openai_client

        sent: list[str] = []

        async def handler(request):
            sent.append(str(request.url))
            return httpx.Response(307, headers={"Location": "https://redirect.example.test/collect"})

        with patch.dict(os.environ, {
            "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED": "true",
            "MEMORY_GATEWAY_EGRESS_ALLOWLIST": "https://approved.example.test",
        }, clear=False):
            client = create_restricted_async_openai_client(
                api_key="synthetic-key",
                base_url="https://approved.example.test/v1",
                transport=httpx.MockTransport(handler),
            )
            try:
                with self.assertRaises(Exception):
                    asyncio.run(client.embeddings.create(model="synthetic", input="synthetic"))
            finally:
                asyncio.run(client.close())
        self.assertEqual(sent, ["https://approved.example.test/v1/embeddings"])

    def test_ignores_ambient_proxy_for_loopback_sdk_requests(self):
        received: list[bytes] = []
        proxy_received: list[bytes] = []

        class TargetHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                body = b'{"object":"list","data":[{"object":"embedding","index":0,"embedding":[0.1]}],"model":"synthetic"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        class ProxyHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                proxy_received.append(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                self.send_response(502)
                self.end_headers()

            def log_message(self, *_args):
                pass

        target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
        proxy = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
        threads = [
            __import__("threading").Thread(target=server.serve_forever, daemon=True)
            for server in (target, proxy)
        ]
        for thread in threads:
            thread.start()
        try:
            from outbound_http import create_restricted_async_openai_client

            with patch.dict(os.environ, {
                "MEMORY_GATEWAY_EGRESS_ALLOWLIST": "",
                "HTTP_PROXY": f"http://127.0.0.1:{proxy.server_port}",
                "HTTPS_PROXY": f"http://127.0.0.1:{proxy.server_port}",
                "http_proxy": f"http://127.0.0.1:{proxy.server_port}",
                "https_proxy": f"http://127.0.0.1:{proxy.server_port}",
                "NO_PROXY": "",
                "no_proxy": "",
            }, clear=False):
                client = create_restricted_async_openai_client(
                    api_key="synthetic-key",
                    base_url=f"http://127.0.0.1:{target.server_port}/v1",
                )
                try:
                    asyncio.run(client.embeddings.create(model="synthetic", input="synthetic"))
                finally:
                    asyncio.run(client.close())
            self.assertEqual(len(received), 1)
            self.assertEqual(proxy_received, [])
        finally:
            for server in (target, proxy):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
