"""Isolated, synthetic HTTP recall benchmark for the local Gateway.

This is an observational benchmark, not a pass/fail SLA test. It uses a fresh
temporary SQLite database, loopback only, and disables every external provider.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
SIZES = (100, 1_000, 5_000)
SAMPLES = 60
QUERY = "syntheticneedle recallbenchmark"


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction + 0.5)))
    return round(ordered[index], 2)


def isolated_environment(data_dir: Path) -> None:
    os.environ.update({
        "MEMORY_GATEWAY_DATA": str(data_dir),
        "MEMORY_GATEWAY_DB": str(data_dir / "gateway.sqlite3"),
        "MEMORY_GATEWAY_BACKUP_DIR": str(data_dir / "backups"),
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
        "OPENROUTER_API_KEY": "",
        "EMBEDDING_ENABLED": "false",
        "PROVIDER_RECALL_ENABLED": "false",
        "OLLAMA_WARMUP_ENABLED": "false",
        "PYTHONDONTWRITEBYTECODE": "1",
    })


def request_recall(base_url: str) -> float:
    url = f"{base_url}/v1/recall?q={urllib.parse.quote(QUERY)}&limit=5"
    started = time.perf_counter()
    with urllib.request.urlopen(url, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"recall returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    elapsed_ms = (time.perf_counter() - started) * 1000
    if not payload.get("memories"):
        raise RuntimeError("synthetic benchmark records were not found")
    return elapsed_ms


def measured_recall(base_url: str) -> tuple[float | None, str | None]:
    try:
        return request_recall(base_url), None
    except Exception as exc:
        return None, type(exc).__name__


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="link-recall-benchmark-") as temporary:
        data_dir = Path(temporary) / "data"
        data_dir.mkdir(parents=True)
        isolated_environment(data_dir)
        sys.path.insert(0, str(ROOT / "gateway"))
        import server

        original_urlopen = urllib.request.urlopen

        class LoopbackRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, response, code, message, headers, new_url):
                if urlsplit(new_url).hostname not in {"127.0.0.1", "localhost"}:
                    raise RuntimeError("benchmark blocked a redirect to a non-loopback host")
                return super().redirect_request(request, response, code, message, headers, new_url)

        guarded_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            LoopbackRedirectHandler,
        )

        def loopback_only_urlopen(request: object, *args: object, **kwargs: object):
            url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
            if urlsplit(url).hostname not in {"127.0.0.1", "localhost"}:
                raise RuntimeError("benchmark blocked a non-loopback network request")
            return guarded_opener.open(request, *args, **kwargs)

        urllib.request.urlopen = loopback_only_urlopen  # type: ignore[assignment]

        class QuietHandler(server.Handler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        httpd.daemon_threads = True
        base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
        httpd_thread = __import__("threading").Thread(target=httpd.serve_forever, daemon=True)
        httpd_thread.start()
        results: list[dict[str, object]] = []
        total_records = 0
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                for size in SIZES:
                    now = datetime.now(timezone.utc).isoformat()
                    rows = [
                        (
                            f"perf-{index:06d}",
                            "fact",
                            f"Synthetic recallbenchmark syntheticneedle record {index} with a unique detail.",
                            "synthetic-performance",
                            f"perf-conversation-{index:06d}",
                            0.9,
                            "{}",
                            now,
                            now,
                        )
                        for index in range(total_records, size)
                    ]
                    with server.DB_LOCK:
                        server.DB.executemany(
                            "INSERT INTO memories(id,kind,text,source,conversation_id,confidence,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                            rows,
                        )
                        server.DB.commit()
                    total_records = size

                    for _ in range(10):
                        request_recall(base_url)
                    sequential_results = [measured_recall(base_url) for _ in range(SAMPLES)]
                    wall_started = time.perf_counter()
                    concurrent_results = list(pool.map(lambda _index: measured_recall(base_url), range(SAMPLES)))
                    concurrent_wall_seconds = time.perf_counter() - wall_started
                    sequential = [value for value, error in sequential_results if value is not None and error is None]
                    concurrent_samples = [value for value, error in concurrent_results if value is not None and error is None]
                    if not sequential or not concurrent_samples:
                        raise RuntimeError(f"benchmark had no successful samples at {size} records")
                    results.append({
                        "records": size,
                        "sequential_ms": {
                            "p50": percentile(sequential, 0.50),
                            "p95": percentile(sequential, 0.95),
                            "max": round(max(sequential), 2),
                            "requests_per_second": round(len(sequential) / (sum(sequential) / 1000), 2),
                            "errors": sum(error is not None for _value, error in sequential_results),
                        },
                        "four_worker_load_ms": {
                            "p50": percentile(concurrent_samples, 0.50),
                            "p95": percentile(concurrent_samples, 0.95),
                            "max": round(max(concurrent_samples), 2),
                            "requests_per_second": round(len(concurrent_samples) / concurrent_wall_seconds, 2),
                            "errors": sum(error is not None for _value, error in concurrent_results),
                        },
                    })
        finally:
            urllib.request.urlopen = original_urlopen  # type: ignore[assignment]
            httpd.shutdown()
            httpd.server_close()
            httpd_thread.join(timeout=5)
            server.DB.close()

    print(json.dumps({
        "benchmark": "local_gateway_http_recall",
        "providers": "disabled",
        "database": "temporary SQLite; deleted at exit",
        "network": "loopback only",
        "query": QUERY,
        "samples_per_mode": SAMPLES,
        "thresholds": "none; owner workload/SLA not yet defined",
        "results": results,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
