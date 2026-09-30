"""Graphiti adapter for the Memory Gateway.

The Gateway calls this process over loopback, but Graphiti's SDK sends episode
and query data to the configured LLM, embedding, and reranking endpoints. Those
endpoints may be remote; loopback to this adapter does not make their processing
local. Deployments must restrict destinations and content egress explicitly.
"""

from __future__ import annotations

import asyncio
import base64
import ctypes
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from graphiti_core import Graphiti
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.nodes import EpisodeType

if __package__:
    from .outbound_http import assert_outbound_url_allowed, create_restricted_async_openai_client
    from .network_policy import assert_loopback_bind_host, assert_neo4j_uri_allowed, safe_internal_http_log
else:
    from outbound_http import assert_outbound_url_allowed, create_restricted_async_openai_client
    from network_policy import assert_loopback_bind_host, assert_neo4j_uri_allowed, safe_internal_http_log


HOST = os.getenv("GRAPHITI_HOST", "127.0.0.1")
PORT = int(os.getenv("GRAPHITI_PORT", "18002"))
NEO4J_URI = os.getenv("GRAPHITI_NEO4J_URI", "bolt://127.0.0.1:17687")
NEO4J_USER = os.getenv("GRAPHITI_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("GRAPHITI_NEO4J_PASSWORD", "")
OLLAMA_BASE = os.getenv("GRAPHITI_OLLAMA_BASE", "http://127.0.0.1:11435/v1")
OPENROUTER_BASE = os.getenv("GRAPHITI_OPENROUTER_BASE", "http://127.0.0.1:18099/api/v1").rstrip("/")
ROOT = Path(__file__).resolve().parents[1]
OPENROUTER_KEY_PATH = ROOT / "data" / "openrouter.key.dpapi"
LLM_MODEL = os.getenv("GRAPHITI_LLM_MODEL", "").strip() or os.getenv("OPENROUTER_MODEL", "YOUR_API_MODEL").strip()
EMBED_MODEL = os.getenv("GRAPHITI_EMBED_MODEL", "YOUR_LOCAL_EMBEDDING_MODEL")


def read_openrouter_key() -> str:
    """Read the same Windows-DPAPI protected key used by the Gateway."""
    if os.name != "nt" or not OPENROUTER_KEY_PATH.exists():
        return ""
    try:
        encoded = OPENROUTER_KEY_PATH.read_bytes()
        protected = base64.b64decode(encoded)

        class Blob(ctypes.Structure):
            _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

        source = (ctypes.c_ubyte * len(protected)).from_buffer_copy(protected)
        input_blob = Blob(len(protected), source)
        output_blob = Blob()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)):
            return ""
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData).decode("utf-8")
        finally:
            ctypes.windll.kernel32.LocalFree(output_blob.pbData)
    except (OSError, ValueError, UnicodeError):
        return ""

loop = asyncio.new_event_loop()
graph: Graphiti | None = None
ready = False
init_error: str | None = None
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.RLock()
INGEST_LOCK = threading.Lock()
GRAPHITI_SDK_CLIENTS: list[Any] = []


class _GraphitiProviderErrorFilter(logging.Filter):
    """Drop provider exception text that Graphiti logs before re-raising."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.ERROR:
            record.msg = "Graphiti provider request failed"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


def _install_graphiti_provider_error_filters() -> None:
    error_filter = _GraphitiProviderErrorFilter()
    for logger_name in (
        "graphiti_core.llm_client.openai_generic_client",
        "graphiti_core.cross_encoder.openai_reranker_client",
    ):
        logging.getLogger(logger_name).addFilter(error_filter)


def run_async(awaitable: Any, timeout: float = 180) -> Any:
    future = asyncio.run_coroutine_threadsafe(awaitable, loop)
    return future.result(timeout=timeout)


async def initialize() -> None:
    global graph, ready, init_error
    try:
        _install_graphiti_provider_error_filters()
        # Validate every configured provider/database target before constructing clients.
        assert_outbound_url_allowed(OPENROUTER_BASE)
        assert_outbound_url_allowed(OLLAMA_BASE)
        assert_neo4j_uri_allowed(NEO4J_URI)
        openrouter_key = os.getenv("GRAPHITI_OPENROUTER_API_KEY", "").strip() or read_openrouter_key()
        if not openrouter_key:
            raise RuntimeError("Graphiti OpenRouter key is unavailable; configure the key in Link Memory first")
        cfg = LLMConfig(api_key=openrouter_key, model=LLM_MODEL, small_model=LLM_MODEL, base_url=OPENROUTER_BASE, temperature=0)
        llm_sdk_client = create_restricted_async_openai_client(api_key=openrouter_key, base_url=OPENROUTER_BASE)
        GRAPHITI_SDK_CLIENTS.append(llm_sdk_client)
        embedder_sdk_client = create_restricted_async_openai_client(api_key="ollama", base_url=OLLAMA_BASE)
        GRAPHITI_SDK_CLIENTS.append(embedder_sdk_client)
        graph = Graphiti(
            NEO4J_URI,
            NEO4J_USER,
            NEO4J_PASSWORD,
            llm_client=OpenAIGenericClient(config=cfg, client=llm_sdk_client, structured_output_mode="json_object"),
            embedder=OpenAIEmbedder(config=OpenAIEmbedderConfig(api_key="ollama", embedding_model=EMBED_MODEL, embedding_dim=1024, base_url=OLLAMA_BASE), client=embedder_sdk_client),
            cross_encoder=OpenAIRerankerClient(config=cfg, client=llm_sdk_client),
            # Keep Graphiti's remote LLM calls bounded; embeddings remain local.
            max_coroutines=1,
        )
        await graph.build_indices_and_constraints()
        ready = True
    except Exception:  # expose readiness without leaking provider diagnostics
        await close_sdk_clients()
        init_error = "graphiti_initialization_failed"
        ready = False


async def close_sdk_clients() -> None:
    clients = list(GRAPHITI_SDK_CLIENTS)
    GRAPHITI_SDK_CLIENTS.clear()
    for client in clients:
        try:
            await client.close()
        except Exception:
            pass


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")


def serialize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): serialize(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return serialize(value.model_dump(mode="json"))
    if hasattr(value, "__dict__"):
        return serialize({key: item for key, item in vars(value).items() if not key.startswith("_")})
    return str(value)


def _ingest_episode(job_id: str, payload: dict[str, Any]) -> None:
    with JOBS_LOCK:
        JOBS[job_id]["status"] = "running"
    try:
        with INGEST_LOCK:
            text = str(payload.get("text", "")).strip()
            occurred = payload.get("occurred_at")
            reference_time = datetime.fromisoformat(str(occurred).replace("Z", "+00:00")) if occurred else datetime.now(timezone.utc)
            memory_id = str(payload.get("memory_id", ""))[:160]
            source_name = str(payload.get("source", "memory-gateway"))
            tags = payload.get("tags", [])
            tag_text = ",".join(str(tag).strip() for tag in tags[:8] if str(tag).strip()) if isinstance(tags, list) else ""
            episode_name = f"{payload.get('conversation_id') or source_name}:{memory_id or 'event'}"
            result = run_async(graph.add_episode(
                name=episode_name,
                episode_body=text,
                source_description=f"{source_name}; kind={payload.get('kind', 'fact')}; tags={tag_text}; gateway_memory_id={memory_id}",
                reference_time=reference_time,
                source=EpisodeType.text,
                group_id="personal",
                update_communities=False,
            ), timeout=240)
        with JOBS_LOCK:
            JOBS[job_id].update({"status": "completed", "result": serialize(result), "finished_at": datetime.now(timezone.utc).isoformat()})
    except Exception:
        with JOBS_LOCK:
            JOBS[job_id].update({"status": "failed", "error": "graphiti_ingest_failed", "finished_at": datetime.now(timezone.utc).isoformat()})


class Handler(BaseHTTPRequestHandler):
    server_version = "MemoryGateway-Graphiti/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(safe_internal_http_log("Graphiti", args), flush=True)

    def send_json(self, value: Any, status: int = 200) -> None:
        body = json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON object is required")
        return payload

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json({"ok": ready, "service": "graphiti-adapter", "store": "neo4j", "ready": ready, "error": init_error, "llm_model": LLM_MODEL, "embedding_model": EMBED_MODEL}, 200 if ready else 503)
            return
        if self.path.startswith("/v1/jobs"):
            job_id = self.path.split("?id=", 1)[1] if "?id=" in self.path else ""
            with JOBS_LOCK:
                job = dict(JOBS.get(job_id, {"id": job_id, "status": "not_found"}))
            self.send_json({"job": job}, 200 if job.get("status") != "not_found" else HTTPStatus.NOT_FOUND)
            return
        self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            payload = self.body()
            if not ready or graph is None:
                self.send_json({"error": "graphiti is not ready", "code": "graphiti_unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            if self.path == "/v1/ingest":
                text = str(payload.get("text", "")).strip()
                if not text:
                    raise ValueError("text is required")
                job_id = str(uuid.uuid4())
                with JOBS_LOCK:
                    JOBS[job_id] = {"id": job_id, "status": "queued", "created_at": datetime.now(timezone.utc).isoformat(), "memory_id": payload.get("memory_id")}
                threading.Thread(target=_ingest_episode, args=(job_id, payload), name=f"graphiti-job-{job_id[:8]}", daemon=True).start()
                self.send_json({"status": "queued", "job_id": job_id}, HTTPStatus.ACCEPTED)
                return
            if self.path == "/v1/search":
                query = str(payload.get("query", payload.get("text", ""))).strip()
                results = run_async(graph.search(query=query, num_results=max(1, min(int(payload.get("limit", 8)), 30))))
                # Graphiti's primary search returns EntityEdge objects. A graph
                # containing only episodic nodes has no edges yet, so expose
                # matching episodes as bounded evidence instead of reporting a
                # false empty result.
                if not results and query:
                    terms = [part.lower() for part in query.split() if len(part) > 2]
                    episodes = run_async(graph.retrieve_episodes(datetime.now(timezone.utc), last_n=50))
                    results = [episode for episode in episodes if any(term in str(getattr(episode, "content", "")).lower() for term in terms)]
                self.send_json({"query": query, "results": serialize(results)})
                return
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except ValueError:
            self.send_json({"error": "invalid_request", "code": "invalid_request"}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self.send_json({"error": "graphiti request failed", "code": "graphiti_request_failed"}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main() -> None:
    assert_loopback_bind_host(HOST)
    threading.Thread(target=lambda: (asyncio.set_event_loop(loop), loop.run_forever()), daemon=True).start()
    run_async(initialize(), timeout=240)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Graphiti adapter listening on http://{HOST}:{PORT} ready={ready}", flush=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        run_async(close_sdk_clients(), timeout=15)
        loop.call_soon_threadsafe(loop.stop)


if __name__ == "__main__":
    main()
