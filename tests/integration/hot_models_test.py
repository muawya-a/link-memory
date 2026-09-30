"""Verify the remaining local embedding and GPU reranker services."""
from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen


OLLAMA = os.getenv("OLLAMA_URL", "http://127.0.0.1:11435").rstrip("/")
RERANKER = os.getenv("RERANKER_URL", "http://127.0.0.1:18001").rstrip("/")
KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "24h")


def post(url: str, payload: dict) -> dict:
    request = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode())


def main() -> int:
    jobs = {
        "embedding": (f"{OLLAMA}/api/embed", {"model": os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:0.6b"), "input": "hot model concurrency test", "keep_alive": KEEP_ALIVE}),
        "reranker": (f"{RERANKER}/v1/rerank", {"query": "concise answers", "documents": ["The user prefers concise answers.", "A random unrelated sentence."]}),
    }
    # The models remain resident together, but GPU inference is intentionally
    # serialized on this 8 GB card. This avoids llama-server/CrossEncoder
    # contention while keeping every subsequent request hot and bounded.
    outputs: dict[str, dict] = {name: post(url, payload) for name, (url, payload) in jobs.items()}
    checks = {
        "embedding": bool(outputs["embedding"].get("embeddings") or outputs["embedding"].get("embedding")),
        "reranker": outputs["reranker"].get("device") == "cuda" and bool(outputs["reranker"].get("ranking")),
    }
    if not all(checks.values()):
        raise SystemExit(json.dumps({"ok": False, "checks": checks}, ensure_ascii=False))
    print(json.dumps({"ok": True, "checks": checks, "mode": "serialized-gpu-queue", "keep_alive": KEEP_ALIVE, "reranker_device": outputs["reranker"].get("device")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
