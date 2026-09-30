"""Local GPU reranker service for Memory Gateway."""

from __future__ import annotations

import json
import os
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# Reranker inference is local-only. Require a pre-cached model and suppress Hub telemetry.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import torch
from sentence_transformers import CrossEncoder

if __package__:
    from .network_policy import assert_loopback_bind_host, safe_internal_http_log
else:
    try:
        from network_policy import assert_loopback_bind_host, safe_internal_http_log
    except ModuleNotFoundError:
        from gateway.network_policy import assert_loopback_bind_host, safe_internal_http_log


HOST = os.getenv("RERANKER_HOST", "127.0.0.1")
PORT = int(os.getenv("RERANKER_PORT", "18001"))
MODEL_NAME = os.getenv("RERANKER_MODEL", "YOUR_LOCAL_RERANKER_MODEL")
MAX_LENGTH = int(os.getenv("RERANKER_MAX_LENGTH", "512"))
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
MODEL = CrossEncoder(MODEL_NAME, max_length=MAX_LENGTH, device=DEVICE, local_files_only=True, trust_remote_code=False)
MODEL_LOCK = threading.Lock()


def send_json(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        print(safe_internal_http_log("Reranker", args), flush=True)

    def do_GET(self) -> None:
        if self.path in {"/health", "/v1/status"}:
            send_json(self, {
                "ok": True,
                "service": "memory-reranker",
                "model": MODEL_NAME,
                "device": DEVICE,
                "cuda": torch.cuda.is_available(),
                "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            })
            return
        send_json(self, {"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/v1/rerank":
            send_json(self, {"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1_000_000:
                raise ValueError("request is too large")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            query = str(payload.get("query", "")).strip()
            documents = payload.get("documents", [])
            if not query or not isinstance(documents, list):
                raise ValueError("query and documents are required")
            documents = [str(item) for item in documents[:64]]
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            send_json(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        # CrossEncoder inference is GPU-bound and its model object is not
        # safe to drive from multiple HTTP worker threads concurrently.
        # Serialize only the forward pass; the HTTP server remains responsive
        # and callers receive deterministic ranking instead of a GPU deadlock.
        try:
            with MODEL_LOCK:
                ranked = MODEL.rank(query, documents, top_k=len(documents), return_documents=False)
            response_payload = {"query": query, "device": DEVICE, "ranking": ranked}
            json.dumps(response_payload, ensure_ascii=False, allow_nan=False)
        except Exception as exc:
            error_id = str(uuid.uuid4())
            print(f"Reranker error {error_id}: {type(exc).__name__}", flush=True)
            send_json(self, {"error": "reranker failed", "error_id": error_id}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        send_json(self, response_payload)


def main() -> None:
    assert_loopback_bind_host(HOST)
    print(f"Memory Reranker listening on http://{HOST}:{PORT} using {MODEL_NAME} on {DEVICE}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
