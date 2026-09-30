"""Local MemPalace adapter for original transcripts and deep text search."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from mempalace.layers import MemoryStack

if __package__:
    from .network_policy import assert_loopback_bind_host, safe_internal_http_log
    from .subprocess_policy import build_mempalace_child_env
else:
    from network_policy import assert_loopback_bind_host, safe_internal_http_log
    from subprocess_policy import build_mempalace_child_env

try:
    from mempalace.searcher import search_memories as palace_search_memories
except ImportError:
    palace_search_memories = None

ROOT = Path(__file__).resolve().parents[1]
HOST = os.getenv("MEMPALACE_HOST", "127.0.0.1")
PORT = int(os.getenv("MEMPALACE_PORT", "18003"))
PALACE = Path(os.getenv("MEMPALACE_PALACE_PATH", str(ROOT / "data" / "mempalace"))).resolve()
SOURCES = Path(os.getenv("MEMPALACE_SOURCE_PATH", str(ROOT / "data" / "mempalace_sources"))).resolve()
MEMPALE_PYTHON = os.getenv("MEMPALACE_PYTHON", str(Path(os.sys.executable)))
LOCK = threading.RLock()


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")


def status() -> dict[str, Any]:
    PALACE.mkdir(parents=True, exist_ok=True)
    value = MemoryStack(palace_path=str(PALACE)).status()
    return {"ok": True, "service": "mempalace-adapter", "palace": str(PALACE), "status": value}


def ingest(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text", "")).strip()
    if not text:
        raise ValueError("text is required")
    SOURCES.mkdir(parents=True, exist_ok=True)
    path = SOURCES / f"{uuid.uuid4().hex}.md"
    tags = payload.get("tags", [])
    tag_line = ", ".join(str(tag).strip() for tag in tags[:8] if str(tag).strip()) if isinstance(tags, list) else ""
    heading = f"# {payload.get('source', 'memory-gateway')}\n\nMemory ID: {payload.get('memory_id', 'unknown')}\nKind: {payload.get('kind', 'fact')}\nOccurred at: {payload.get('occurred_at', '')}\nTags: {tag_line}\n\n"
    path.write_text(heading + text, encoding="utf-8")
    env = build_mempalace_child_env(os.environ, PALACE, SOURCES)
    command = [MEMPALE_PYTHON, "-m", "mempalace", "mine", str(path), "--mode", "convos", "--direct", "--extract", "general"]
    with LOCK:
        completed = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=180)
    if completed.returncode != 0:
        return {"status": "failed", "error": "mempalace_ingest_failed"}
    return {"status": "ingested"}


def source_file_search(query: str, limit: int) -> list[dict[str, Any]]:
    """Small exact/lexical fallback for source files not yet mined into drawers."""
    terms = [part.lower() for part in query.split() if len(part) > 2]
    if not terms:
        return []
    hits: list[tuple[int, Path, str]] = []
    for path in SOURCES.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        haystack = text.lower()
        score = sum(haystack.count(term) for term in terms)
        if score:
            hits.append((score, path, text))
    hits.sort(key=lambda item: item[0], reverse=True)
    results = []
    for score, path, text in hits[:limit]:
        results.append({"text": text[:12000], "source_file": path.name, "source_path": str(path), "score": score, "matched_via": "source-file-lexical"})
    return results


class Handler(BaseHTTPRequestHandler):
    server_version = "MemoryGateway-MemPalace/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(safe_internal_http_log("MemPalace", args), flush=True)

    def send_json(self, value: Any, status_code: int = 200) -> None:
        body = json_bytes(value)
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON object is required")
        return value

    def do_GET(self) -> None:
        if self.path == "/health":
            try:
                self.send_json(status())
            except Exception:
                self.send_json({"ok": False, "service": "mempalace-adapter", "error": "mempalace_status_failed"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if self.path == "/v1/status":
            try:
                self.send_json(status())
            except Exception:
                self.send_json({"ok": False, "service": "mempalace-adapter", "error": "mempalace_status_failed"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            payload = self.read_body()
            if self.path == "/v1/ingest":
                self.send_json(ingest(payload), HTTPStatus.ACCEPTED)
                return
            if self.path == "/v1/search":
                query = str(payload.get("query", payload.get("text", ""))).strip()
                limit = max(1, min(int(payload.get("limit", 8)), 30))
                if palace_search_memories is not None:
                    result = palace_search_memories(query, palace_path=str(PALACE), n_results=limit)
                else:
                    stack = MemoryStack(palace_path=str(PALACE))
                    result = stack.search(query, n_results=limit)
                if not isinstance(result, dict):
                    result = {"results": result}
                official = result.get("results") if isinstance(result.get("results"), list) else []
                official = [entry for entry in official if not (isinstance(entry, dict) and str(entry.get("text", "")).lstrip().lower().startswith("[registry]"))]
                fallback = source_file_search(query, limit)
                result["results"] = (fallback + official)[:limit]
                self.send_json({"query": query, "results": result})
                return
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except ValueError:
            self.send_json({"error": "invalid_request", "code": "invalid_request"}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self.send_json({"error": "mempalace request failed", "code": "mempalace_request_failed"}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main() -> None:
    assert_loopback_bind_host(HOST)
    PALACE.mkdir(parents=True, exist_ok=True)
    SOURCES.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"MemPalace adapter listening on http://{HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
