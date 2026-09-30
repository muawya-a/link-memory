"""End-to-end acceptance checks for the local Memory Gateway.

The script uses only the local HTTP surface, creates uniquely-marked QA memories,
and archives them before exiting. It never prints memory contents, tokens, or
absolute backup paths.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from http.client import HTTPConnection
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE = os.getenv("MEMORY_GATEWAY_TEST_URL", "http://127.0.0.1:18000").rstrip("/")
ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = float(os.getenv("MEMORY_GATEWAY_TEST_TIMEOUT", "180"))
MARKER = f"qa-acceptance-{uuid.uuid4().hex[:12]}"
results: list[dict[str, object]] = []


def request(path: str, method: str = "GET", payload: dict | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Accept": "application/json"}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)
    try:
        with urlopen(Request(f"{BASE}{path}", data=body, headers=request_headers, method=method), timeout=TIMEOUT) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"HTTP {exc.code} at {path}: {detail[:200]}") from exc
    except URLError as exc:
        raise AssertionError(f"Gateway unavailable: {exc.reason}") from exc


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append({"name": name, "passed": bool(passed), "detail": detail})
    if not passed:
        raise AssertionError(f"{name}: {detail}")


def main() -> int:
    created_ids: list[str] = []
    try:
        status, body = request("/health")
        check("gateway health", status == 200 and body.get("ok") is True)
        providers = body.get("providers", {})
        check("three memory providers", all(providers.get(name, {}).get("available") for name in ("openmemory", "graphiti", "mempalace")))
        check("GPU reranker", providers.get("reranker", {}).get("device") == "cuda", str(providers.get("reranker", {}).get("device")))

        _, metrics_response = request("/v1/metrics")
        metrics = metrics_response.get("metrics", {})
        check("monitor metrics", isinstance(metrics.get("captures"), dict) and "review_open" in metrics)
        for path, name in (("/v1/captures?limit=5", "capture log"), ("/v1/review", "smart review"), ("/v1/memories?limit=5", "memory administration"), ("/v1/backups", "backup inventory"), ("/v1/retry", "retry queue")):
            _, value = request(path)
            check(name, isinstance(value, dict))

        _, preview = request("/v1/preview", "POST", {"source": "qa-preview", "text": "I prefer concise answers. api_key=not-a-real-api-token"})
        check("privacy preview", preview.get("persisted") is False and preview.get("redaction_count", 0) > 0)
        check("preview candidates", isinstance(preview.get("candidates"), list))

        _, health = request("/v1/health/check", "POST", {})
        services = health.get("services", [])
        health_ok = bool(services) and all(item.get("ok") is True for item in services)
        check("automated health", health_ok, "one or more services failed" if not health_ok else "")

        _, backups = request("/v1/backups")
        backup_items = backups.get("backups", [])
        if backup_items:
            _, verified = request("/v1/backup/verify", "POST", {"path": backup_items[0]["path"]})
            check("backup integrity", verified.get("valid") is True and verified.get("integrity") == "ok")
        else:
            check("backup inventory", False, "no backup exists")

        _, saved = request("/v1/remember", "POST", {"text": f"{MARKER} prefers concise acceptance-test answers", "type": "preference", "source": "qa-acceptance", "confidence": 0.91})
        memory_id = saved.get("memory", {}).get("id")
        check("manual save", bool(memory_id))
        if memory_id:
            created_ids.append(memory_id)
            _, updated = request("/v1/memory/update", "POST", {"id": memory_id, "text": f"{MARKER} prefers concise and structured acceptance-test answers", "type": "preference", "confidence": 0.94})
            check("memory editing", updated.get("memory", {}).get("id") == memory_id)
            _, explained = request(f"/v1/memory/explain?id={memory_id}")
            check("provenance and versioning", len(explained.get("versions", [])) >= 2 and isinstance(explained.get("audit"), list))
            _, searched = request(f"/v1/search/advanced?{urlencode({'q': MARKER, 'kind': 'preference', 'source': 'qa-acceptance'})}")
            check("advanced filtered search", any(item.get("id") == memory_id for item in searched.get("memories", [])))

        _, contextual = request("/v1/ingest", "POST", {
                "source": "qa-acceptance-context",
                "conversation_id": f"{MARKER}-context",
                "messages": [{"role": "user", "content": f"The user repeated this preference: {MARKER} prefers concise and structured acceptance-test answers."}],
                "delete_after_success": True,
        })
        contextual_items = contextual.get("saved", [])
        contextual_metadata = [item.get("metadata", {}) for item in contextual_items if isinstance(item, dict)]
        _, analysis_state = request("/v1/analysis/status")
        if analysis_state.get("paused"):
            check(
                "analysis pause queue",
                contextual.get("status") == "queued" and contextual.get("paused") is True and bool(contextual.get("job_id")),
                "paused analysis must remain durable and queued",
            )
        elif contextual.get("status") == "queued":
            # A remote provider quota/rate-limit is a supported transient
            # state: the gateway must retain the raw document and expose a
            # durable job instead of reporting a false success or deleting it.
            queued_job_id = contextual.get("job_id")
            _, queued_job = request(f"/v1/jobs?id={queued_job_id}")
            job = queued_job.get("job", {})
            check(
                "analysis provider queue",
                bool(queued_job_id) and job.get("status") == "queued" and contextual.get("submitted") is False,
                "transient provider failure must remain queued for retry",
            )
        else:
            check(
                "analysis recalls prior memories",
                contextual.get("status") == "processed" and any(int(meta.get("related_memory_count", 0)) > 0 for meta in contextual_metadata),
            )
        for item in contextual_items:
            if item.get("id") and item.get("id") not in created_ids:
                created_ids.append(item["id"])

        _, low_saved = request("/v1/remember", "POST", {"text": f"{MARKER} low confidence review candidate", "type": "fact", "source": "qa-acceptance", "confidence": 0.1})
        low_id = low_saved.get("memory", {}).get("id")
        if low_id:
            created_ids.append(low_id)
        _, review = request("/v1/review")
        review_id = next((item.get("id") for item in review.get("review", []) if item.get("memory_id") == low_id), None)
        check("automatic review admission", bool(review_id))
        if review_id:
            request("/v1/review/resolve", "POST", {"id": review_id, "status": "resolved"})

        request("/v1/memory/archive", "POST", {"id": memory_id})
        if low_id:
            request("/v1/memory/archive", "POST", {"id": low_id})
        check("archive lifecycle", True)

        _, retry = request("/v1/retry", "POST", {})
        check("retry execution", retry.get("status") == "queued")

        cors_status, _ = request("/v1/metrics", headers={"Origin": "http://127.0.0.1:18765"})
        check("dashboard CORS", cors_status == 200)
        check("Codex bridge", all((ROOT / "scripts" / name).is_file() for name in ("codex_notify_bridge.py", "codex_hook_report.py")))
        connection = HTTPConnection("127.0.0.1", 18000, timeout=10)
        connection.request("OPTIONS", "/v1/metrics", headers={"Origin": "http://127.0.0.1:18765", "Access-Control-Request-Method": "GET"})
        options = connection.getresponse()
        check("CORS preflight", options.status == 204 and options.getheader("Access-Control-Allow-Origin") == "http://127.0.0.1:18765")
        connection.close()
    finally:
        for memory_id in created_ids:
            try:
                request("/v1/memory/archive", "POST", {"id": memory_id})
            except Exception:
                pass
    by_name = {str(item["name"]): bool(item["passed"]) for item in results}
    features = {
        "01 monitoring center": by_name.get("monitor metrics", False), "02 capture log": by_name.get("capture log", False),
        "03 retry queue": by_name.get("retry queue", False) and by_name.get("retry execution", False), "04 privacy filter": by_name.get("privacy preview", False),
        "05 explainability": by_name.get("provenance and versioning", False), "06 smart review": by_name.get("automatic review admission", False),
        "07 versioning": by_name.get("provenance and versioning", False), "08 advanced search": by_name.get("advanced filtered search", False),
        "09 preview": by_name.get("preview candidates", False), "10 health test": by_name.get("automated health", False),
        "11 Codex/providers": by_name.get("three memory providers", False) and by_name.get("Codex bridge", False),
        "12 smart backup": by_name.get("backup integrity", False), "13 manual management": by_name.get("memory administration", False) and by_name.get("memory editing", False),
        "14 performance/GPU": by_name.get("GPU reranker", False) and by_name.get("monitor metrics", False),
    }
    print(json.dumps({"ok": True, "marker": MARKER, "features": features, "checks": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "checks": results}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
