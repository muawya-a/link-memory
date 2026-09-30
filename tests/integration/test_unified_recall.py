"""End-to-end checks for the bounded multi-store recall contract."""

from __future__ import annotations

import json
import subprocess
import time
import uuid
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def get(path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:18000{path}", timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def post(path: str, payload: dict, timeout: int = 30) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:18000{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    health = get("/health")
    assert health["ok"] is True
    for name in ("openmemory", "graphiti", "mempalace"):
        assert health["providers"][name]["available"] is True, health["providers"][name]

    query = urllib.parse.quote("owner")
    recall = get(f"/v1/recall?q={query}&limit=8")
    assert len(recall["memories"]) <= 8
    assert recall["recall"]["providers"]["openmemory"]["ok"] is True
    assert recall["recall"]["providers"]["graphiti"]["ok"] is True
    assert recall["recall"]["providers"]["mempalace"]["ok"] is True
    assert all("vector" not in item for item in recall["memories"])

    # The gateway must accept a complete long document while analysis is
    # internally chunked; use a unique id so this check never mutates a prior
    # document or creates an import conflict.
    long_text = "user: I prefer concise answers.\nassistant: noted.\n" * 160
    result = post("/v1/ingest", {"source": "unified-test", "conversation_id": f"unified-long-{uuid.uuid4().hex}", "text": long_text, "delete_after_success": True}, timeout=30)
    assert result["status"] in {"processed", "duplicate", "queued"}, result
    long_document_status = result["status"]
    if result["status"] == "queued":
        analysis_state = get("/v1/analysis/status")
        if analysis_state.get("paused"):
            assert result.get("paused") is True and result.get("job_id"), result
            long_document_status = "queued-paused"
        else:
            # Local generation is intentionally serialized on the shared GPU. A
            # long document may wait briefly behind a live capture, so allow up to
            # six minutes for the durable job instead of failing at three minutes.
            for _ in range(72):
                job = get(f"/v1/jobs?id={urllib.parse.quote(result['job_id'])}")["job"]
                if job["status"] == "queued":
                    # A provider quota/temporary outage is a supported state:
                    # the raw document must remain retryable and expose a
                    # scheduled retry instead of being reported as success.
                    assert job.get("next_retry_at") or job.get("error"), job
                    long_document_status = "queued-provider"
                    break
                if job["status"] in {"completed", "failed"}:
                    assert job["status"] == "completed", job
                    break
                time.sleep(5)
            else:
                raise AssertionError("long analysis job did not finish")

    mcp = subprocess.run(
        ["python", str(ROOT / "gateway" / "mcp_server.py")],
        input='{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n',
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=30,
        check=True,
    )
    tools = json.loads(mcp.stdout)["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert {"memory_context", "memory_capture", "memory_recall"} <= names, names
    print(json.dumps({"health": True, "providers": ["openmemory", "graphiti", "mempalace"], "bounded_recall": len(recall["memories"]), "long_document": long_document_status, "mcp": sorted(names)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
