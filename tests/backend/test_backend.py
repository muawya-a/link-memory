"""Isolated Gateway and MCP round-trip smoke test for memory and recovery paths."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import tomllib
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path


def call(base: str, method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{base}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise AssertionError(f"{method} {path} failed with {exc.code}: {detail}") from exc


def assert_lexical_recall_order(server) -> None:
    """Keep a highly lexical match ahead of newer one-token BM25 distractors."""
    exact = server.save_memory(
        {"text": "mangosteen telescope itinerary exact evidence"},
        "synthetic-ranking",
        "bm25-exact-old",
        "2020-01-01",
    )
    for index, term in enumerate(("mangosteen", "telescope", "itinerary"), start=1):
        server.save_memory(
            {"text": f"{term} unrelated note"},
            "synthetic-ranking",
            f"bm25-distractor-{index}",
            f"2026-09-0{index}",
        )
    vector_search_before = server.vector_search
    server.vector_search = lambda *_args, **_kwargs: []
    try:
        results = server.search_memories("mangosteen telescope itinerary", limit=4, rerank=False)
    finally:
        server.vector_search = vector_search_before
    expected_ids = {
        row["id"]
        for row in server.DB.execute(
            "SELECT id FROM memories WHERE conversation_id LIKE 'bm25-%'"
        ).fetchall()
    }
    assert {item["id"] for item in results} == expected_ids, "FTS should return all synthetic OR-token matches, not fall back to phrase-only LIKE"
    assert results and results[0]["id"] == exact["id"], "BM25 lexical relevance must outrank newer one-token matches"


def assert_memory_fts_triggers_and_rebuild(server) -> None:
    """Memory insert/update/delete and schema rebuild must maintain searchable tokens."""
    old_token = "ftsupdateoldmarker"
    new_token = "ftsupdatenewmarker"
    item = server.save_memory(
        {"text": f"Synthetic {old_token} indexed memory."},
        "synthetic-fts-trigger",
        "fts-trigger-update-delete",
        "2026-09-26",
    )
    with server.DB_LOCK:
        server.DB.execute("UPDATE memories SET text=? WHERE id=?", (f"Synthetic {new_token} indexed memory.", item["id"]))
        server.DB.commit()
    old_results = server.search_memories(old_token, limit=10, rerank=False)
    new_results = server.search_memories(new_token, limit=10, rerank=False)
    assert not any(value["id"] == item["id"] for value in old_results), "memory update trigger must remove stale FTS tokens"
    assert any(value["id"] == item["id"] for value in new_results), "memory update trigger must index replacement text"

    server.change_memory_state({"id": item["id"], "confirm": "DELETE"}, "delete")
    deleted_results = server.search_memories(new_token, limit=10, rerank=False)
    assert not any(value["id"] == item["id"] for value in deleted_results), "memory delete trigger must remove deleted FTS tokens"

    rebuild_token = "ftsstalerebuildmarker"
    rebuild_id = server.uuid.uuid4().hex
    timestamp = server.now_iso()
    try:
        with server.DB_LOCK:
            server.DB.execute("DROP TRIGGER memories_ai")
            server.DB.execute(
                "INSERT INTO memories(id,kind,text,source,confidence,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (rebuild_id, "fact", f"Synthetic {rebuild_token} pending rebuild.", "synthetic-fts-rebuild", 0.9, "{}", timestamp, timestamp),
            )
            server.DB.commit()
            before_rebuild = server.DB.execute(
                "SELECT m.id FROM memory_fts f JOIN memories m ON m.rowid=f.rowid WHERE memory_fts MATCH ?",
                (f'"{rebuild_token}"',),
            ).fetchall()
        assert not before_rebuild, "synthetic row without its insert trigger must be absent from the derived FTS index"

        server.initialize_schema(server.DB)
        with server.DB_LOCK:
            after_rebuild = server.DB.execute(
                "SELECT m.id FROM memory_fts f JOIN memories m ON m.rowid=f.rowid WHERE memory_fts MATCH ?",
                (f'"{rebuild_token}"',),
            ).fetchall()
        assert [row["id"] for row in after_rebuild] == [rebuild_id], "schema initialization must rebuild stale external-content FTS rows"
    finally:
        server.initialize_schema(server.DB)
        with server.DB_LOCK:
            server.DB.execute("DELETE FROM memories WHERE id=?", (rebuild_id,))
            server.DB.commit()


def assert_provider_failure_details_are_sanitized(server) -> None:
    """Provider failures must not persist or return synthetic secret details."""
    sentinel = "SYNTHETIC_PROVIDER_FAILURE_SENTINEL_74821"
    item = server.save_memory(
        {"text": f"synthetic private memory {sentinel}"},
        "synthetic-provider-failure",
        "provider-failure-redaction",
        "2026-09-26",
    )
    original_url = server.OPENMEMORY_URL
    original_enabled = server.provider_enabled
    original_urlopen = server.urlopen_no_proxy_redirects
    synthetic_url = f"http://user:{sentinel}@127.0.0.1:18099/adapter?token={sentinel}"

    def raise_synthetic_http_error(request, timeout):
        assert sentinel in request.full_url
        raise urllib.error.HTTPError(
            request.full_url,
            503,
            f"failure {sentinel}",
            {},
            __import__("io").BytesIO(f"provider echoed {sentinel}".encode()),
        )

    server.OPENMEMORY_URL = synthetic_url
    server.provider_enabled = lambda url, _enabled: url == synthetic_url
    server.urlopen_no_proxy_redirects = raise_synthetic_http_error
    try:
        outcome = server.fanout_memory(item, "synthetic-provider-failure", "provider-failure-redaction", "2026-09-26")
    finally:
        server.OPENMEMORY_URL = original_url
        server.provider_enabled = original_enabled
        server.urlopen_no_proxy_redirects = original_urlopen

    link = next(link for link in server.list_provider_links(item["id"]) if link["provider"] == "openmemory")
    explained_link = next(link for link in server.memory_explain(item["id"])["provider_links"] if link["provider"] == "openmemory")
    exposed = json.dumps({"outcome": outcome, "link": link, "explained_link": explained_link}, ensure_ascii=False)
    assert sentinel not in exposed, "provider URL, error body, and memory markers must not escape failure handling"
    assert outcome.get("openmemory_error") == "provider_http_5xx"
    assert link["status"] == "failed" and link["last_error"] == "provider_http_5xx"
    assert explained_link["last_error"] == "provider_http_5xx"

    original_request_json = server.request_json
    server.request_json = lambda *_args, **_kwargs: {
        "status": "failed", "detail": sentinel, "source_file": f"/private/{sentinel}.md",
    }
    try:
        name, reported_error = server._send_provider(
            "openmemory", item["id"], {"text": sentinel}, "http://127.0.0.1/synthetic", 1
        )
    finally:
        server.request_json = original_request_json
    stored_reported = next(link for link in server.list_provider_links(item["id"]) if link["provider"] == "openmemory")
    assert (name, reported_error) == ("openmemory_error", "provider_reported_failure")
    assert sentinel not in json.dumps({"reported": reported_error, "stored": stored_reported}, ensure_ascii=False)


    legacy_item = server.save_memory(
        {"text": "synthetic legacy provider link"}, "synthetic-provider-failure", "provider-legacy-link", "2026-09-26"
    )
    server.DB.execute(
        "INSERT INTO provider_links(memory_id,provider,status,attempts,last_error,queued_at) VALUES(?,?,?,?,?,?)",
        (legacy_item["id"], "graphiti", "failed", 1, f"legacy exception {sentinel}", server.now_iso()),
    )
    server.DB.commit()
    legacy_link = next(link for link in server.list_provider_links(legacy_item["id"]) if link["provider"] == "graphiti")
    legacy_explained = next(link for link in server.memory_explain(legacy_item["id"])["provider_links"] if link["provider"] == "graphiti")
    assert legacy_link["last_error"] == legacy_explained["last_error"] == "provider_error"
    assert sentinel not in json.dumps({"legacy_link": legacy_link, "legacy_explained": legacy_explained}, ensure_ascii=False)

    try:
        server.request_json(f"unsupported-{sentinel}://127.0.0.1/resource", {"text": "synthetic"}, timeout=1)
    except Exception as exc:
        assert str(exc) == "provider_invalid_request", "invalid endpoint errors must not echo configured URL text"
    else:
        raise AssertionError("invalid synthetic endpoint should fail before any network operation")

    original_ollama_url = server.OLLAMA_URL
    original_ollama_enabled = server.OLLAMA_ENABLED
    original_warmup_enabled = server.OLLAMA_WARMUP_ENABLED
    original_ollama_model = server.OLLAMA_MODEL
    original_embed_model = server.OLLAMA_EMBED_MODEL
    original_warmup_state = dict(server.WARMUP_STATE)
    original_urlopen = server.urlopen_no_proxy_redirects
    server.OLLAMA_URL = f"http://user:{sentinel}@127.0.0.1:1"
    server.OLLAMA_ENABLED = True
    server.OLLAMA_WARMUP_ENABLED = True
    server.OLLAMA_MODEL = "synthetic-model"
    server.OLLAMA_EMBED_MODEL = "synthetic-embed"
    server.urlopen_no_proxy_redirects = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        urllib.error.URLError(f"synthetic connection failure {sentinel}")
    )
    try:
        server.warmup_ollama_models()
        warmup_error = str(server.WARMUP_STATE.get("error") or "")
    finally:
        server.OLLAMA_URL = original_ollama_url
        server.OLLAMA_ENABLED = original_ollama_enabled
        server.OLLAMA_WARMUP_ENABLED = original_warmup_enabled
        server.OLLAMA_MODEL = original_ollama_model
        server.OLLAMA_EMBED_MODEL = original_embed_model
        server.urlopen_no_proxy_redirects = original_urlopen
        server.WARMUP_STATE.clear()
        server.WARMUP_STATE.update(original_warmup_state)
    assert warmup_error == "provider_connection_error", "warmup status must retain safe error class without URL or credentials"

    try:
        server.get_json(f"unsupported-{sentinel}://127.0.0.1/health", timeout=1)
    except Exception as exc:
        assert str(exc) == "service_invalid_request", "health probe failures must not echo endpoint text"
    else:
        raise AssertionError("invalid synthetic health endpoint should fail before network access")

    original_openmemory_url = server.OPENMEMORY_URL
    original_openmemory_enabled = server.OPENMEMORY_ENABLED
    original_recall_enabled = server.PROVIDER_RECALL_ENABLED
    original_provider_enabled = server.provider_enabled
    original_urlopen = server.urlopen_no_proxy_redirects
    recall_url = f"http://user:{sentinel}@127.0.0.1:1"
    server.OPENMEMORY_URL = recall_url
    server.OPENMEMORY_ENABLED = True
    server.PROVIDER_RECALL_ENABLED = True
    server.provider_enabled = lambda url, _enabled: url == recall_url
    server.urlopen_no_proxy_redirects = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        urllib.error.URLError(f"synthetic recall failure {sentinel}")
    )
    try:
        _, recall_trace = server.provider_recall(sentinel, limit=1)
    finally:
        server.OPENMEMORY_URL = original_openmemory_url
        server.OPENMEMORY_ENABLED = original_openmemory_enabled
        server.PROVIDER_RECALL_ENABLED = original_recall_enabled
        server.provider_enabled = original_provider_enabled
        server.urlopen_no_proxy_redirects = original_urlopen
    recall_failure = json.dumps(recall_trace.get("errors", {}), ensure_ascii=False)
    assert recall_trace["errors"].get("openmemory") == "provider_connection_error"
    assert sentinel not in recall_failure, "provider recall trace must not echo endpoint credentials or query text"

    original_openrouter_url = server.OPENROUTER_URL
    original_get_openrouter_key = server.get_openrouter_key
    original_urlopen = server.urlopen_no_proxy_redirects
    server.OPENROUTER_URL = f"http://user:{sentinel}@127.0.0.1:1/{sentinel}"
    server.get_openrouter_key = lambda: ""
    server.urlopen_no_proxy_redirects = lambda request, timeout: (_ for _ in ()).throw(
        urllib.error.HTTPError(request.full_url, 429, "quota", {}, __import__("io").BytesIO(sentinel.encode()))
    )
    try:
        try:
            server._openrouter_request("models", timeout=1)
        except ValueError as exc:
            assert str(exc) == "OpenRouter HTTP 429", "OpenRouter quota status should survive without response content"
        else:
            raise AssertionError("synthetic OpenRouter HTTP failure should be surfaced")
    finally:
        server.OPENROUTER_URL = original_openrouter_url
        server.get_openrouter_key = original_get_openrouter_key
        server.urlopen_no_proxy_redirects = original_urlopen


def assert_provider_health_dtos_are_projected(server, base: str) -> None:
    """Provider health DTOs retain useful status only, never raw diagnostics."""
    sentinel = "SYNTHETIC_PROVIDER_HEALTH_SENTINEL_91743"
    names = (
        "OPENMEMORY_URL", "OPENMEMORY_ENABLED", "GRAPHITI_URL", "GRAPHITI_ENABLED",
        "MEMPALACE_URL", "MEMPALACE_ENABLED", "RERANKER_URL", "RERANKER_ENABLED",
        "OLLAMA_ENABLED", "OLLAMA_WARMUP_ENABLED", "OLLAMA_MODEL", "OLLAMA_EMBED_MODEL",
        "OLLAMA_KEEP_ALIVE", "OLLAMA_WARMUP_TIMEOUT", "get_json", "request_json",
    )
    original = {name: getattr(server, name) for name in names}
    original_warmup = dict(server.WARMUP_STATE)
    try:
        server.OPENMEMORY_URL = "http://127.0.0.1/synthetic-openmemory"
        server.GRAPHITI_URL = "http://127.0.0.1/synthetic-graphiti"
        server.MEMPALACE_URL = "http://127.0.0.1/synthetic-mempalace"
        server.RERANKER_URL = "http://127.0.0.1/synthetic-reranker"
        server.OPENMEMORY_ENABLED = server.GRAPHITI_ENABLED = server.MEMPALACE_ENABLED = True
        server.RERANKER_ENABLED = True
        server.OLLAMA_ENABLED = True
        server.OLLAMA_WARMUP_ENABLED = True
        server.OLLAMA_MODEL = "synthetic-chat-model"
        server.OLLAMA_EMBED_MODEL = "synthetic-embedding-model"
        server.OLLAMA_KEEP_ALIVE = "0"
        server.OLLAMA_WARMUP_TIMEOUT = 1
        server.WARMUP_STATE.clear()
        server.WARMUP_STATE.update({"enabled": True, "state": "not_started", "started_at": None, "finished_at": None, "error": None})
        server.request_json = lambda *_args, **_kwargs: {"error": sentinel}
        server.warmup_ollama_models()
        assert server.WARMUP_STATE["state"] == "failed"
        assert server.WARMUP_STATE["error"] == "provider_reported_failure"
        assert sentinel not in json.dumps(server.WARMUP_STATE, ensure_ascii=False)

        responses = {
            "synthetic-openmemory": {
                "data": {"ok": True, "store": {"working_memory": 7, "path": sentinel}},
                "available": False, "state": sentinel, "url": sentinel, "secret": sentinel,
            },
            "synthetic-graphiti": {
                "ok": True, "ready": True, "available": False, "state": sentinel,
                "database_path": sentinel, "url": sentinel, "error": sentinel,
            },
            "synthetic-mempalace": {
                "ok": True, "available": False, "state": sentinel, "palace": f"C:/private/{sentinel}",
                "status": {"source_path": sentinel}, "url": sentinel,
            },
            "synthetic-reranker": {
                "ok": True, "ready": True, "available": False, "model": sentinel,
                "device": sentinel, "secret": sentinel,
            },
        }
        server.get_json = lambda url, timeout=1.5: next(
            value for marker, value in responses.items() if marker in url
        )

        health = call(base, "GET", "/health")
        status = call(base, "GET", "/v1/status")
        recall = call(base, "GET", "/v1/recall?q=synthetic-status-check")
        layers = call(base, "GET", "/v1/memory-layers")
        for dto in (health, status, recall, layers):
            assert sentinel not in json.dumps(dto, ensure_ascii=False), "raw adapter diagnostics must not escape Gateway DTOs"

        providers = health["providers"]
        assert providers["openmemory"]["configured"] is True and providers["openmemory"]["enabled"] is True
        assert providers["openmemory"]["available"] is True and providers["openmemory"]["state"] == "ready"
        assert providers["openmemory"]["mode"] == "local-adapter"
        assert providers["openmemory"]["data"] == {"ok": True, "store": {"working_memory": 7}}
        assert providers["graphiti"]["available"] is True and providers["graphiti"]["state"] == "ready"
        assert providers["mempalace"]["available"] is True and providers["mempalace"]["state"] == "ready", repr(providers["mempalace"])
        assert providers["mempalace"]["mode"] == "local-adapter"
        assert providers["reranker"]["available"] is True and providers["reranker"]["state"] == "ready"
        assert health["ollama"]["warmup"]["error"] == "provider_reported_failure"
        assert status["providers"]["mempalace"]["enabled"] is True
        assert recall["providers"]["openmemory"]["data"]["store"]["working_memory"] == 7
        assert layers["status"]["openmemory"]["data"]["store"]["working_memory"] == 7
        assert layers["status"]["mempalace"]["available"] is True
    finally:
        for name, value in original.items():
            setattr(server, name, value)
        server.WARMUP_STATE.clear()
        server.WARMUP_STATE.update(original_warmup)


def test_mcp_invalid_limit_error_does_not_echo_argument() -> None:
    marker = "SYNTHETIC_SECRET_LIMIT_MARKER_51742"
    project_root = Path(__file__).resolve().parents[2]
    environment = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if key in os.environ
    }
    environment["MEMORY_GATEWAY_URL"] = "http://127.0.0.1:1"
    environment["MEMORY_GATEWAY_API_KEY"] = ""
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "memory_recall", "arguments": {"query": "synthetic", "limit": marker},
        }},
    ]
    process = subprocess.Popen(
        [sys.executable, str(project_root / "gateway" / "mcp_server.py")],
        cwd=str(project_root / "gateway"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        stdout, stderr = process.communicate(
            "\n".join(json.dumps(message) for message in messages) + "\n",
            timeout=30,
        )
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    error_message = next(response["error"]["message"] for response in responses if response.get("id") == 1)
    assert process.returncode == 0
    assert error_message and marker not in stdout and "ValueError" not in error_message
    assert "ValueError" in stderr and marker not in stderr


class SyntheticFailureHandler(BaseHTTPRequestHandler):
    detail_marker = "SYNTHETIC_INTERNAL_PROVIDER_DETAIL_73915"

    def do_GET(self) -> None:
        body = self.detail_marker.encode("ascii")
        self.send_response(500)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


def assert_restore_failure_preserves_live_db(server) -> None:
    """A failed restore must leave pre-restore synthetic data recoverable."""
    def database_contains(memory_id: str) -> bool:
        connection = server.sqlite3.connect(str(server.DB_PATH))
        try:
            return connection.execute("SELECT 1 FROM memories WHERE id=?", (memory_id,)).fetchone() is not None
        except server.sqlite3.DatabaseError:
            return False
        finally:
            connection.close()

    def assert_preserved(memory_id: str) -> None:
        if database_contains(memory_id):
            return
        # A red run against the old implementation can leave its synthetic DB
        # replaced; close that handle so the isolated temp directory can clean up.
        try:
            server.DB.close()
        except server.sqlite3.Error:
            pass
        raise AssertionError("a failed restore must preserve the current database before-image")

    backup = server.create_backup({})
    marker = server.save_memory(
        {"text": "Synthetic pre-restore recovery marker."},
        "synthetic-restore-recovery",
        "restore-recovery-marker",
        "2026-09-26",
    )
    original_initialize_schema = server.initialize_schema
    failure_state = {"raised": False}

    def fail_during_candidate_validation(connection):
        if not failure_state["raised"]:
            failure_state["raised"] = True
            raise RuntimeError("synthetic restore initialization failure")
        return original_initialize_schema(connection)

    server.initialize_schema = fail_during_candidate_validation
    try:
        try:
            server.restore_backup({"path": backup["path"], "confirm": "RESTORE"})
        except RuntimeError as exc:
            assert "synthetic restore initialization failure" in str(exc)
        else:
            raise AssertionError("restore should report the injected candidate validation failure")
    finally:
        server.initialize_schema = original_initialize_schema
    assert failure_state["raised"]
    assert_preserved(marker["id"])

    rollback_backup = server.create_backup({})
    rollback_marker = server.save_memory(
        {"text": "Synthetic post-replacement rollback marker."},
        "synthetic-restore-recovery",
        "restore-rollback-marker",
        "2026-09-26",
    )
    original_connect_db = server.connect_db
    reopen_state = {"raised": False}

    def fail_first_reopen():
        if not reopen_state["raised"]:
            reopen_state["raised"] = True
            raise RuntimeError("synthetic post-replacement reopen failure")
        return original_connect_db()

    server.connect_db = fail_first_reopen
    try:
        try:
            server.restore_backup({"path": rollback_backup["path"], "confirm": "RESTORE"})
        except RuntimeError as exc:
            assert "synthetic post-replacement reopen failure" in str(exc)
        else:
            raise AssertionError("restore should report the injected post-replacement failure")
    finally:
        server.connect_db = original_connect_db
    assert reopen_state["raised"]
    assert_preserved(rollback_marker["id"])

    recovery_backup = server.create_backup({})
    recovery_marker = server.save_memory(
        {"text": "Synthetic marker for retained before-image recovery."},
        "synthetic-restore-recovery",
        "restore-retained-before-image-marker",
        "2026-09-26",
    )
    recovery_connect = server.connect_db
    recovery_state = {"calls": 0}

    def fail_candidate_and_rollback_reopens():
        recovery_state["calls"] += 1
        if recovery_state["calls"] <= 2:
            raise RuntimeError("synthetic recovery reopen failure")
        return recovery_connect()

    server.connect_db = fail_candidate_and_rollback_reopens
    retained_name = ""
    try:
        try:
            server.restore_backup({"path": recovery_backup["path"], "confirm": "RESTORE"})
        except RuntimeError as exc:
            retained_name = str(exc).partition("recovery copy retained as ")[2]
            assert retained_name, "a failed rollback must report the retained before-image name"
        else:
            raise AssertionError("restore must report when both candidate reopen and rollback reopen fail")
    finally:
        server.connect_db = recovery_connect
    assert recovery_state["calls"] == 2
    retained_before_image = server.DB_PATH.with_name(retained_name)
    assert retained_before_image.is_file(), "a failed rollback must preserve its pre-restore recovery copy"
    assert_preserved(recovery_marker["id"])
    server.DB = recovery_connect()
    server.initialize_schema(server.DB)
    retained_before_image.unlink()


def main() -> None:
    test_mcp_invalid_limit_error_does_not_echo_argument()
    with tempfile.TemporaryDirectory(prefix="memory-gateway-smoke-") as temp:
        temp_path = Path(temp)
        os.environ["MEMORY_GATEWAY_DATA"] = str(temp_path / "data")
        os.environ["MEMORY_GATEWAY_DB"] = str(temp_path / "data" / "gateway.sqlite3")
        os.environ["MEMORY_GATEWAY_BACKUP_DIR"] = str(temp_path / "backups")
        os.environ["MEMORY_GATEWAY_URL"] = "http://127.0.0.1:18013"
        os.environ["OLLAMA_ENABLED"] = "false"
        os.environ["RERANKER_ENABLED"] = "false"
        os.environ["OPENMEMORY_ENABLED"] = "false"
        os.environ["GRAPHITI_ENABLED"] = "false"
        os.environ["MEMPALACE_ENABLED"] = "false"
        os.environ["PROVIDER_RECALL_ENABLED"] = "false"
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gateway"))
        import server
        assert_memory_fts_triggers_and_rebuild(server)
        assert_restore_failure_preserves_live_db(server)
        assert_provider_failure_details_are_sanitized(server)

        # Deferred ingest must redact every persisted text field before the
        # payload enters the durable job queue or capture-event metadata.
        # The marker is synthetic and the paused queue keeps this deterministic.
        test_secret = "sk-" + "A" * 32
        server.set_runtime_setting("analysis_paused", "true")
        try:
            deferred = server.ingest({
                "source": "synthetic-regression",
                "conversation_id": "deferred-redaction-regression",
                "messages": [{"role": "user", "content": f"Keep this note; {test_secret}"}],
                "metadata": {"note": test_secret},
            })
            queued = server.DB.execute("SELECT payload_json FROM analysis_jobs WHERE id=?", (deferred["job_id"],)).fetchone()
            event = server.DB.execute("SELECT message_count,source,metadata_json,privacy_redactions FROM capture_events WHERE job_id=?", (deferred["job_id"],)).fetchone()
            persisted_payload = queued["payload_json"]
            persisted_event_metadata = event["metadata_json"]
            assert test_secret not in persisted_payload, "queued analysis payload must not persist a detectable secret"
            assert test_secret not in persisted_event_metadata, "capture-event metadata must not persist a detectable secret"
            assert event["message_count"] == 1 and event["source"] == "synthetic-regression"
            assert event["privacy_redactions"] == 2, "queued capture should retain redaction count across both text fields"
            queued_payload = json.loads(persisted_payload)
            assert "Keep this note" in queued_payload["messages"][0]["content"]
            assert "[REDACTED:openai_key]" in queued_payload["messages"][0]["content"]
            assert "[REDACTED:openai_key]" in json.dumps(queued_payload["metadata"])
            assert queued_payload["_privacy_redactions"] == ["openai_key", "openai_key"]
        finally:
            server.set_runtime_setting("analysis_paused", "false")

        # A completed async job no longer needs its retry payload, but its
        # result and portable archive representation must remain available.
        job_id = "synthetic-completed-job-payload-retention"
        job_payload = {
            "source": "synthetic-retention",
            "conversation_id": "synthetic-retention-conversation",
            "text": "SYNTHETIC_SOURCE_PAYLOAD_MARKER",
            "_run_in_background": True,
        }
        with server.DB_LOCK:
            server.DB.execute(
                "INSERT INTO analysis_jobs(id,source,conversation_id,payload_json,status,created_at,next_retry_at,stage) VALUES(?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    job_payload["source"],
                    job_payload["conversation_id"],
                    json.dumps(job_payload, ensure_ascii=False),
                    "queued",
                    server.now_iso(),
                    server.now_iso(),
                    "queued",
                ),
            )
            server.DB.commit()
        original_process_document = server.process_document
        server.process_document = lambda _payload: {
            "status": "processed",
            "saved": [{"id": "synthetic-saved-memory", "text": "Synthetic durable memory"}],
            "saved_count": 1,
        }
        try:
            server._run_analysis_job(job_id, job_payload)
        finally:
            server.process_document = original_process_document
        completed_row = server.DB.execute(
            "SELECT status,payload_json,result_json FROM analysis_jobs WHERE id=?", (job_id,)
        ).fetchone()
        assert completed_row["status"] == "completed"
        assert completed_row["payload_json"] == "{}", "completed jobs must release their duplicate source payload"
        completed_result = json.loads(completed_row["result_json"])
        assert completed_result["saved"][0]["text"] == "Synthetic durable memory"
        assert server.analysis_job(job_id)["result"] == completed_result
        portable_archive = json.loads(server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8"))
        exported_job = next(job for job in portable_archive["tables"]["analysis_jobs"] if job["id"] == job_id)
        assert exported_job["status"] == "completed" and exported_job["payload_json"] == {}
        assert "SYNTHETIC_SOURCE_PAYLOAD_MARKER" not in json.dumps(exported_job, ensure_ascii=False)

        # An archive-refresh failure must not turn a committed successful job
        # back into a retry or persist the archive exception in job details.
        archive_failure_job_id = "synthetic-completed-job-archive-failure"
        with server.DB_LOCK:
            server.DB.execute(
                "INSERT INTO analysis_jobs(id,source,conversation_id,payload_json,status,created_at,next_retry_at,stage) VALUES(?,?,?,?,?,?,?,?)",
                (
                    archive_failure_job_id,
                    job_payload["source"],
                    job_payload["conversation_id"],
                    json.dumps(job_payload, ensure_ascii=False),
                    "queued",
                    server.now_iso(),
                    server.now_iso(),
                    "queued",
                ),
            )
            server.DB.commit()
        original_write_portable_archive = server.write_portable_archive
        archive_failure_marker = "SYNTHETIC_ARCHIVE_FAILURE_MARKER"
        server.process_document = lambda _payload: {
            "status": "processed",
            "saved": [{"id": "synthetic-archive-failure-memory", "text": "Synthetic memory"}],
            "saved_count": 1,
        }
        server.write_portable_archive = lambda: (_ for _ in ()).throw(OSError(archive_failure_marker))
        try:
            with redirect_stdout(StringIO()) as archive_log:
                server._run_analysis_job(archive_failure_job_id, job_payload)
        finally:
            server.process_document = original_process_document
            server.write_portable_archive = original_write_portable_archive
        archive_failure_row = server.DB.execute(
            "SELECT status,payload_json,result_json,error_json FROM analysis_jobs WHERE id=?",
            (archive_failure_job_id,),
        ).fetchone()
        assert archive_failure_row["status"] == "completed"
        assert archive_failure_row["payload_json"] == "{}"
        assert json.loads(archive_failure_row["result_json"])["status"] == "processed"
        assert archive_failure_row["error_json"] is None
        assert archive_failure_marker not in archive_log.getvalue()
        assert "archive refresh failed (OSError)" in archive_log.getvalue()
        assert server.get_runtime_setting("portable_archive_refresh_pending"), "failed export must leave a durable refresh request"
        assert server.retry_pending_portable_archive_once() is True, "retry worker should rebuild a pending portable export"
        assert server.get_runtime_setting("portable_archive_refresh_pending") == "", "successful rebuild should clear the pending refresh token"
        recovered_archive = json.loads(server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8"))
        recovered_job = next(job for job in recovered_archive["tables"]["analysis_jobs"] if job["id"] == archive_failure_job_id)
        assert recovered_job["status"] == "completed" and recovered_job["payload_json"] == {}

        # Terminal review and discard outcomes also update the archive. Review
        # jobs keep their retry/source payload; exhausted exceptions discard it.
        review_job_id = "synthetic-analysis-needs-review-archive"
        discard_job_id = "synthetic-analysis-discarded-archive"
        with server.DB_LOCK:
            for terminal_job_id in (review_job_id, discard_job_id):
                server.DB.execute(
                    "INSERT INTO analysis_jobs(id,source,conversation_id,payload_json,status,created_at,attempts,next_retry_at,stage) VALUES(?,?,?,?,?,?,?,?,?)",
                    (terminal_job_id, job_payload["source"], job_payload["conversation_id"], json.dumps(job_payload), "queued", server.now_iso(), server.ANALYSIS_RETRY_MAX_ATTEMPTS - 1, server.now_iso(), "queued"),
                )
            server.DB.commit()
        server.process_document = lambda _payload: {"status": "failed", "error": "synthetic terminal analysis failure", "saved": [], "saved_count": 0}
        try:
            server._run_analysis_job(review_job_id, job_payload)
        finally:
            server.process_document = original_process_document
        review_row = server.DB.execute("SELECT status,payload_json FROM analysis_jobs WHERE id=?", (review_job_id,)).fetchone()
        review_archive = json.loads(server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8"))
        exported_review_job = next(job for job in review_archive["tables"]["analysis_jobs"] if job["id"] == review_job_id)
        assert review_row["status"] == "needs_review" and review_row["payload_json"] != "{}"
        assert exported_review_job["status"] == "needs_review" and exported_review_job["payload_json"]

        server.process_document = lambda _payload: (_ for _ in ()).throw(RuntimeError("synthetic terminal exception"))
        try:
            server._run_analysis_job(discard_job_id, job_payload)
        finally:
            server.process_document = original_process_document
        discarded_row = server.DB.execute("SELECT status,payload_json FROM analysis_jobs WHERE id=?", (discard_job_id,)).fetchone()
        assert discarded_row["status"] == "discarded" and discarded_row["payload_json"] == "{}"
        assert server.get_runtime_setting("portable_archive_refresh_pending"), "exception discard must leave a durable archive request"
        assert server.retry_pending_portable_archive_once() is True
        discard_archive = json.loads(server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8"))
        exported_discard_job = next(job for job in discard_archive["tables"]["analysis_jobs"] if job["id"] == discard_job_id)
        assert exported_discard_job["status"] == "discarded" and exported_discard_job["payload_json"] == {}

        # Startup recovery and historical duplicate collapse are persisted in
        # the same transaction as a durable archive refresh request.
        running_job_id = "synthetic-running-job-recovered-on-startup"
        duplicate_job_ids = ("synthetic-history-duplicate-a", "synthetic-history-duplicate-b")
        with server.DB_LOCK:
            server.DB.execute(
                "INSERT INTO analysis_jobs(id,source,conversation_id,payload_json,status,created_at,attempts,next_retry_at,stage) VALUES(?,?,?,?,?,?,?,?,?)",
                (running_job_id, "synthetic-restart", "restart-conversation", json.dumps(job_payload), "running", server.now_iso(), 1, None, "analyzing"),
            )
            for duplicate_id in duplicate_job_ids:
                server.DB.execute(
                    "INSERT INTO analysis_jobs(id,source,conversation_id,payload_json,status,created_at,attempts,next_retry_at,stage) VALUES(?,?,?,?,?,?,?,?,?)",
                    (duplicate_id, "codex-history", "same-history-conversation", json.dumps(job_payload), "queued", server.now_iso(), 0, server.now_iso(), "queued"),
                )
            server.DB.commit()
        server.initialize_schema(server.DB)
        recovered_running = server.DB.execute("SELECT status FROM analysis_jobs WHERE id=?", (running_job_id,)).fetchone()
        collapsed_duplicate = server.DB.execute("SELECT status,payload_json FROM analysis_jobs WHERE id=?", (duplicate_job_ids[1],)).fetchone()
        assert recovered_running["status"] == "queued"
        assert collapsed_duplicate["status"] == "completed" and collapsed_duplicate["payload_json"] == "{}"
        assert server.get_runtime_setting("portable_archive_refresh_pending"), "startup recovery must refresh the portable archive"
        assert server.retry_pending_portable_archive_once() is True
        startup_archive = json.loads(server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8"))
        exported_duplicate = next(job for job in startup_archive["tables"]["analysis_jobs"] if job["id"] == duplicate_job_ids[1])
        assert exported_duplicate["status"] == "completed" and exported_duplicate["payload_json"] == {}

        sync_secret = "ghp_" + "B" * 30
        sync_result = server.process_document({
            "source": "synthetic-sync-redaction",
            "conversation_id": "sync-metadata-redaction-regression",
            "text": "I prefer concise answers.",
            "metadata": {"note": sync_secret},
        })
        sync_metadata = server.DB.execute(
            "SELECT metadata_json FROM raw_documents WHERE id=?", (sync_result["raw_document_id"],)
        ).fetchone()[0]
        assert sync_secret not in sync_metadata, "synchronous raw-document metadata must be redacted before persistence"

        mcp_status = server.mcp_status()
        assert mcp_status["mcp_available"] is True
        assert mcp_status["shared_hook_contract"] is False
        assert "memory_layers" in mcp_status["tools"]
        assert mcp_status["ok"] is mcp_status["mcp_available"]  # Backward-compatible alias, not a client connection check.
        assert mcp_status["gateway_url"] == "http://127.0.0.1:18013"
        client_configs = mcp_status["client_configs"]
        codex_config = client_configs["codex"]
        assert codex_config["format"] == "toml" and codex_config["filename"] == "link-memory-mcp-snippet.toml"
        codex_snippet = tomllib.loads(codex_config["content"])["mcp_servers"]["link-memory-memory"]
        claude_config = client_configs["claude_code"]
        assert claude_config["format"] == "json" and claude_config["filename"] == "link-memory.mcp.json"
        claude_json = json.loads(claude_config["content"])
        assert set(claude_json) == {"mcpServers"}
        claude_snippet = claude_json["mcpServers"]["link-memory-memory"]
        shared_config = mcp_status["config"]["mcpServers"]["link-memory-memory"]
        assert {key: codex_snippet[key] for key in ("command", "args", "cwd", "env")} == shared_config
        assert set(claude_snippet) == {"command", "args", "env"}
        assert {key: claude_snippet[key] for key in ("command", "args", "env")} == {
            key: shared_config[key] for key in ("command", "args", "env")
        }
        assert "cwd" not in claude_snippet
        assert shared_config["env"]["MEMORY_GATEWAY_URL"] == "http://127.0.0.1:18013"
        assert shared_config["env"]["PYTHONIOENCODING"] == "utf-8"
        codex = next(client for client in mcp_status["clients"] if client["name"] == "Codex")
        assert codex["mcp_available"] is True
        assert codex["bridge_present"] is True
        assert codex["connected"] is False and codex["active"] is False
        assert "غير متحققة" in codex["status"]
        for client in mcp_status["clients"]:
            assert client["connected"] is False and client["active"] is False
        claude = next(client for client in mcp_status["clients"] if client["name"] == "Claude")
        assert claude["mcp_available"] is True
        assert "غير متحققين" in claude["status"]

        # OpenRouter free models may return an equivalent JSON array wrapped
        # in a markdown fence. Verify that the same durable-memory contract
        # is accepted and that provenance stays on the remote backend.
        server.set_runtime_setting("history_analysis_backend", "openrouter")
        server.set_runtime_setting("openrouter_model", "test/free")
        server.set_runtime_setting("openrouter_free_only", "true")
        server.get_openrouter_key = lambda: "test-key"
        server.openrouter_model_is_free = lambda _model: True
        consent_status = server.configure_external_ingest_consent({"external_ingest_consent": False})
        assert consent_status["external_ingest_consent"] is False
        server.set_runtime_setting("history_analysis_backend", "openrouter")
        external_ingest_requests = []
        server._openrouter_request = lambda *args, **kwargs: external_ingest_requests.append((args, kwargs)) or {}
        assert server.openrouter_status()["external_ingest_consent"] is False
        blocked_candidates = server.analyze_with_ollama("I prefer concise answers.", "openrouter-no-consent")
        assert not external_ingest_requests, "capture analysis must not send conversations to an external model without consent"
        assert not blocked_candidates, "external-only analysis must not pretend it extracted memories without consent"
        consent_status = server.configure_external_ingest_consent({"external_ingest_consent": True})
        assert consent_status["external_ingest_consent"] is True
        server.set_runtime_setting("history_analysis_backend", "openrouter")
        legacy_context_secret = "sk-" + "D" * 32
        original_analysis_memory_context = server._analysis_memory_context
        server._analysis_memory_context = lambda _text: [{"id": "legacy-secret", "text": legacy_context_secret}]
        outbound_model_requests: list[str] = []
        def capture_openrouter_request(*args, **kwargs):
            outbound_model_requests.append(json.dumps(kwargs.get("payload", {}), ensure_ascii=False))
            return {
            "choices": [{"message": {"content": '''```json
[{"text":"I prefer concise answers.","type":"preference","confidence":0.9,"id":"new","categories":["preference.communication"],"localized":{"ar":"أفضل الإجابات الموجزة.","en":"I prefer concise answers."},"source_language":"en"}]
```'''}}]
            }
        server._openrouter_request = capture_openrouter_request
        remote_candidates = server.analyze_with_ollama("I prefer concise answers.", "openrouter-test")
        assert outbound_model_requests and legacy_context_secret not in outbound_model_requests[0], "legacy memory context must be redacted before external model requests"
        server._analysis_memory_context = original_analysis_memory_context
        assert remote_candidates and remote_candidates[0]["kind"] == "preference"
        assert remote_candidates[0]["metadata"]["classification_action"] == "new"
        assert remote_candidates[0]["metadata"]["analysis_backend"] == "openrouter"
        assert "preference.communication" in remote_candidates[0]["metadata"]["categories"]
        assert remote_candidates[0]["metadata"]["localized"]["ar"] == "أفضل الإجابات الموجزة."
        assert server.detect_text_language("السلام عليكم") == "ar"
        assert server.detect_text_language("Hello, how are you?") == "en"
        legacy_display = server._localize_memory({"text": "An older English memory", "metadata": {"text_language": "en"}}, "ar")
        assert legacy_display["display_text"] == "An older English memory" and legacy_display["translation_available"] is False
        server._openrouter_request = lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("remote unavailable"))
        try:
            server._analyze_chunk_with_ollama("I prefer concise answers.", "openrouter-test", 0, 1)
        except server.AnalysisBackendError:
            pass
        else:
            raise AssertionError("selected OpenRouter backend must retain failures instead of silently using local analysis")
        retry_secret = "ghp_" + "C" * 30
        retry_result = server.process_document({
            "source": "synthetic-retry-redaction",
            "conversation_id": "retry-metadata-redaction-regression",
            "text": "I prefer concise answers.",
            "metadata": {"note": retry_secret},
        })
        assert retry_result["status"] == "queued", "remote analysis failure should retain a retryable job"
        assert server.get_runtime_setting("portable_archive_refresh_pending") == "", "newly queued analysis must refresh its portable archive"
        retry_archive = json.loads(server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8"))
        exported_retry_job = next(job for job in retry_archive["tables"]["analysis_jobs"] if job["id"] == retry_result["job_id"])
        assert exported_retry_job["status"] == "queued" and exported_retry_job["payload_json"]
        retry_payload = server.DB.execute(
            "SELECT payload_json FROM analysis_jobs WHERE id=?", (retry_result["job_id"],)
        ).fetchone()[0]
        retry_raw_metadata = server.DB.execute(
            "SELECT metadata_json FROM raw_documents WHERE id=?", (retry_result["raw_document_id"],)
        ).fetchone()[0]
        assert retry_secret not in retry_payload, "failed-provider retry payload must not persist detectable secrets"
        assert retry_secret not in retry_raw_metadata, "failed-provider raw metadata must not persist detectable secrets"

        manual_retry_ids = ("synthetic-manual-retry-single", "synthetic-manual-retry-batch")
        prior_pause_state = server.get_runtime_setting("analysis_paused", "false")
        server.set_analysis_pause(True)
        with server.DB_LOCK:
            for manual_job_id in manual_retry_ids:
                server.DB.execute(
                    "INSERT INTO analysis_jobs(id,source,conversation_id,payload_json,status,created_at,attempts,next_retry_at,stage) VALUES(?,?,?,?,?,?,?,?,?)",
                    (manual_job_id, "synthetic-manual-retry", manual_job_id, json.dumps(job_payload), "failed", server.now_iso(), 0, None, "failed"),
                )
            server.DB.commit()
        single_retry = server.retry_analysis_job(manual_retry_ids[0])
        batch_retry = server.retry_failed_analysis(limit=10)
        manual_archive = json.loads(server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8"))
        exported_manual_jobs = {job["id"]: job for job in manual_archive["tables"]["analysis_jobs"]}
        assert single_retry["submitted"] is False and batch_retry["requeued"] == 1
        assert exported_manual_jobs[manual_retry_ids[0]]["status"] == "queued"
        assert exported_manual_jobs[manual_retry_ids[1]]["status"] == "queued"
        with server.DB_LOCK:
            server.DB.execute("DELETE FROM analysis_jobs WHERE id IN (?,?)", manual_retry_ids)
            server.DB.commit()
        server.set_analysis_pause(prior_pause_state.lower() in {"1", "true", "yes", "on"})

        server.set_runtime_setting("history_analysis_backend", "ollama")
        server.set_runtime_setting("external_ingest_consent", "false")

        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            health = call(base, "GET", "/health")
            assert health["ok"] is True
            assert_provider_health_dtos_are_projected(server, base)

            # Direct memory saves must redact every nested caller-controlled
            # text field before persistence, indexing, export, or provider fanout.
            remember_secrets = {
                "api": "sk-" + "F" * 32,
                "github": "ghp_" + "G" * 30,
                "bearer": "Bearer " + "synthetic.Token_0123456789",
            }
            privacy_before = server.PRIVACY_REDACTION_ENABLED
            submit_before = server.PROVIDER_EXECUTOR.submit
            queued_remember_calls = []
            server.PRIVACY_REDACTION_ENABLED = True
            server.PROVIDER_EXECUTOR.submit = lambda function, *args, **kwargs: queued_remember_calls.append(
                (function, args, kwargs)
            )
            try:
                remembered = call(base, "POST", "/v1/remember", {
                    "source": f"synthetic-{remember_secrets['github']}",
                    "conversation_id": f"remember-{remember_secrets['bearer']}",
                    "occurred_at": remember_secrets["api"],
                    "text": f"Keep this preference; {remember_secrets['api']}",
                    "localized": {"ar": f"{remember_secrets['bearer']} prefers concise replies."},
                    "tags": [remember_secrets["github"]],
                    "metadata": {
                        "nested": {"note": remember_secrets["github"]},
                        "localized": {"en": f"Bearer detail: {remember_secrets['bearer']}"},
                        "tags": [remember_secrets["api"]],
                    },
            })
            finally:
                server.PROVIDER_EXECUTOR.submit = submit_before
                server.PRIVACY_REDACTION_ENABLED = privacy_before
            remembered_json = json.dumps(remembered, ensure_ascii=False)
            assert all(secret not in remembered_json for secret in remember_secrets.values()), "remember response must redact text and nested memory metadata"
            assert "[REDACTED:openai_key]" in remembered_json
            assert "[REDACTED:github_token]" in remembered_json
            assert "[REDACTED:bearer_token]" in remembered_json
            memory_id = remembered["memory"]["id"]
            persisted_rows = {
                "memory": dict(server.DB.execute("SELECT text,source,conversation_id,metadata_json FROM memories WHERE id=?", (memory_id,)).fetchone()),
                "versions": [dict(row) for row in server.DB.execute("SELECT text,metadata_json FROM memory_versions WHERE memory_id=?", (memory_id,)).fetchall()],
                "audit": [dict(row) for row in server.DB.execute("SELECT metadata_json FROM memory_audit WHERE memory_id=?", (memory_id,)).fetchall()],
            }
            persisted_json = json.dumps(persisted_rows, ensure_ascii=False)
            assert all(secret not in persisted_json for secret in remember_secrets.values()), "memory, version, and audit rows must contain sanitized values"
            indexed_rows = {
                "memory_text": server.DB.execute(
                    "SELECT text FROM memory_fts WHERE rowid=(SELECT rowid FROM memories WHERE id=?)", (memory_id,)
                ).fetchone()[0],
                "localized": [row[0] for row in server.DB.execute(
                    "SELECT localized_text FROM memory_localized_fts WHERE memory_id=?", (memory_id,)
                ).fetchall()],
            }
            assert all(secret not in json.dumps(indexed_rows, ensure_ascii=False) for secret in remember_secrets.values()), "memory indexes must use sanitized text"
            archive_json = server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8")
            assert all(secret not in archive_json for secret in remember_secrets.values()), "portable export must not contain secrets from direct remember saves"
            assert len(queued_remember_calls) == 1
            fanout_function, fanout_args, fanout_kwargs = queued_remember_calls[0]
            assert fanout_function is server.fanout_memory and not fanout_kwargs
            fanout_memory_json = json.dumps(fanout_args[0], ensure_ascii=False)
            assert all(secret not in fanout_memory_json for secret in remember_secrets.values()), "provider fanout must receive the sanitized memory"
            assert all(secret not in json.dumps(fanout_args, ensure_ascii=False) for secret in remember_secrets.values()), "provider fanout metadata must not reintroduce secrets from direct-save arguments"

            privacy_before = server.PRIVACY_REDACTION_ENABLED
            server.PRIVACY_REDACTION_ENABLED = False
            try:
                disabled_redaction_secret = "sk-" + "H" * 32
                unsanitized_by_policy = server.save_memory(
                    {"text": f"Privacy redaction disabled: {disabled_redaction_secret}"},
                    "synthetic-privacy-toggle",
                    "redaction-disabled-regression",
                    None,
                )
                assert disabled_redaction_secret in unsanitized_by_policy["text"], "direct saves must preserve the existing redaction-disabled setting semantics"
            finally:
                server.PRIVACY_REDACTION_ENABLED = privacy_before

            mcp_environment = {
                key: os.environ[key]
                for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
                if key in os.environ
            }
            mcp_environment["MEMORY_GATEWAY_URL"] = base
            mcp_environment["MEMORY_GATEWAY_API_KEY"] = ""
            mcp_messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "synthetic-roundtrip-test", "version": "1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "memory_remember", "arguments": {"text": "Synthetic MCP round-trip marker for desktop clients.", "source": "mcp"}}},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "memory_recall", "arguments": {"query": "Synthetic MCP round-trip marker", "limit": 5}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}},
            ]
            mcp_process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve().parents[2] / "gateway" / "mcp_server.py")],
                cwd=str(Path(__file__).resolve().parents[2] / "gateway"),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=mcp_environment,
            )
            try:
                mcp_stdout, mcp_stderr = mcp_process.communicate(
                    "\n".join(json.dumps(message) for message in mcp_messages) + "\n",
                    timeout=30,
                )
            finally:
                if mcp_process.poll() is None:
                    mcp_process.kill()
                    mcp_process.communicate(timeout=5)
            mcp_responses = [json.loads(line) for line in mcp_stdout.splitlines() if line.strip()]
            assert mcp_process.returncode == 0, f"MCP round-trip process failed: {mcp_stderr[-500:]}"
            mcp_initialize = next(response["result"] for response in mcp_responses if response.get("id") == 1)
            mcp_tools = next(response["result"]["tools"] for response in mcp_responses if response.get("id") == 4)
            assert mcp_initialize["serverInfo"]["name"] == "memory-gateway"
            assert {"memory_remember", "memory_recall"} <= {tool["name"] for tool in mcp_tools}
            mcp_write = next(response["result"]["structuredContent"] for response in mcp_responses if response.get("id") == 2)
            mcp_read = next(response["result"]["structuredContent"] for response in mcp_responses if response.get("id") == 3)
            written_memory_id = mcp_write["memory"]["id"]
            assert mcp_write["status"] == "saved" and mcp_write["memory"]["source"] == "mcp"
            assert any(memory.get("id") == written_memory_id for memory in mcp_read["memories"]), "MCP memory_recall must read back the memory written through MCP"

            synthetic_failure_server = ThreadingHTTPServer(("127.0.0.1", 0), SyntheticFailureHandler)
            synthetic_failure_thread = threading.Thread(target=synthetic_failure_server.serve_forever, daemon=True)
            synthetic_failure_thread.start()
            failure_environment = dict(mcp_environment)
            failure_environment["MEMORY_GATEWAY_URL"] = f"http://127.0.0.1:{synthetic_failure_server.server_address[1]}"
            failure_messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "synthetic-failure-test", "version": "1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "memory_status", "arguments": {}}},
            ]
            failure_process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve().parents[2] / "gateway" / "mcp_server.py")],
                cwd=str(Path(__file__).resolve().parents[2] / "gateway"),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=failure_environment,
            )
            try:
                failure_stdout, _ = failure_process.communicate(
                    "\n".join(json.dumps(message) for message in failure_messages) + "\n",
                    timeout=30,
                )
            finally:
                if failure_process.poll() is None:
                    failure_process.kill()
                    failure_process.communicate(timeout=5)
                synthetic_failure_server.shutdown()
                synthetic_failure_server.server_close()
                synthetic_failure_thread.join(timeout=5)
            failure_responses = [json.loads(line) for line in failure_stdout.splitlines() if line.strip()]
            failure_response = next(response for response in failure_responses if response.get("id") == 2)
            failure_message = failure_response["error"]["message"]
            assert failure_message == "Link Memory could not complete the request. Check the connection and try again."
            assert SyntheticFailureHandler.detail_marker not in failure_message, "MCP errors must not expose internal provider details"

            invalid_url_environment = dict(mcp_environment)
            invalid_url_environment["MEMORY_GATEWAY_URL"] = "http://[invalid"
            invalid_url_process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve().parents[2] / "gateway" / "mcp_server.py")],
                cwd=str(Path(__file__).resolve().parents[2] / "gateway"),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=invalid_url_environment,
            )
            try:
                invalid_url_stdout, _ = invalid_url_process.communicate(
                    "\n".join(json.dumps(message) for message in failure_messages) + "\n",
                    timeout=30,
                )
            finally:
                if invalid_url_process.poll() is None:
                    invalid_url_process.kill()
                    invalid_url_process.communicate(timeout=5)
            invalid_url_responses = [json.loads(line) for line in invalid_url_stdout.splitlines() if line.strip()]
            invalid_url_response = next(response for response in invalid_url_responses if response.get("id") == 2)
            assert invalid_url_response["error"]["message"] == "Link Memory could not complete the request. Check the connection and try again."

            archived_retry_memory = server.save_memory(
                {"text": "Synthetic memory that must stay archived."},
                "synthetic-archive-retry",
                "archive-retry-regression",
                None,
            )
            server.DB.execute(
                "INSERT INTO provider_links(memory_id,provider,status,attempts,last_error,queued_at) VALUES(?,?,?,?,?,?)",
                (archived_retry_memory["id"], "openmemory", "failed", 1, "synthetic failure", server.now_iso()),
            )
            server.DB.commit()
            server.change_memory_state({"id": archived_retry_memory["id"]}, "archive")
            original_enqueue_memory_fanout = server.enqueue_memory_fanout
            queued_archived_retries = []
            server.enqueue_memory_fanout = lambda *args: queued_archived_retries.append(args)
            try:
                archived_retry_result = server.retry_failed_links(memory_id=archived_retry_memory["id"])
            finally:
                server.enqueue_memory_fanout = original_enqueue_memory_fanout
            assert archived_retry_result["count"] == 0 and not queued_archived_retries, "manual provider retry must skip archived memories"

            scheduled_retry_memory = server.save_memory(
                {"text": "Synthetic memory archived before retry execution."},
                "synthetic-archive-retry-race",
                "archive-retry-race-regression",
                None,
            )
            server.DB.execute(
                "INSERT INTO provider_links(memory_id,provider,status,attempts,last_error,queued_at) VALUES(?,?,?,?,?,?)",
                (scheduled_retry_memory["id"], "openmemory", "failed", 1, "synthetic failure", server.now_iso()),
            )
            server.DB.commit()
            retry_fanout_results = []
            original_enqueue_memory_fanout = server.enqueue_memory_fanout

            def archive_before_retry_execution(item, source, conversation_id, occurred_at):
                server.change_memory_state({"id": item["id"]}, "archive")
                retry_fanout_results.append(server.fanout_memory(item, source, conversation_id, occurred_at))

            server.enqueue_memory_fanout = archive_before_retry_execution
            try:
                server.retry_failed_links(memory_id=scheduled_retry_memory["id"])
            finally:
                server.enqueue_memory_fanout = original_enqueue_memory_fanout
            assert retry_fanout_results == [{"status": "skipped", "reason": "memory_archived_or_missing"}], "queued provider fan-out must recheck memory state before sending"

            saved_openrouter_url = server.OPENROUTER_URL
            server.OPENROUTER_URL = ""
            try:
                catalog_request = urllib.request.Request(f"{base}/v1/openrouter/models?refresh=1")
                try:
                    urllib.request.urlopen(catalog_request, timeout=10)
                except urllib.error.HTTPError as exc:
                    assert exc.code == 503
                    assert json.loads(exc.read().decode("utf-8")) == {"error": "model catalog unavailable"}
                else:
                    raise AssertionError("an unconfigured catalog must return a safe unavailable response")
            finally:
                server.OPENROUTER_URL = saved_openrouter_url

            initial_openrouter_status = call(base, "GET", "/v1/openrouter/status")
            assert initial_openrouter_status["external_ingest_consent"] is False
            enabled_consent = call(base, "POST", "/v1/privacy/external-ingest-consent", {"external_ingest_consent": True})
            assert enabled_consent["external_ingest_consent"] is True
            assert call(base, "GET", "/v1/openrouter/status")["external_ingest_consent"] is True
            disabled_consent = call(base, "POST", "/v1/privacy/external-ingest-consent", {"external_ingest_consent": False})
            assert disabled_consent["external_ingest_consent"] is False
            assert call(base, "GET", "/v1/openrouter/status")["external_ingest_consent"] is False
            try:
                call(base, "POST", "/v1/openrouter/config", {"external_ingest_consent": True})
            except AssertionError as exc:
                assert "failed with 400" in str(exc)
            else:
                raise AssertionError("provider configuration must reject consent changes")
            assert call(base, "GET", "/v1/openrouter/status")["external_ingest_consent"] is False
            try:
                call(base, "POST", "/v1/privacy/external-ingest-consent", {"external_ingest_consent": "true"})
            except AssertionError as exc:
                assert "failed with 400" in str(exc)
            else:
                raise AssertionError("consent updates must require an explicit JSON boolean")
            assert call(base, "GET", "/v1/openrouter/status")["external_ingest_consent"] is False

            search_marker = "private-search-log-probe-73915"
            request_log = StringIO()
            with redirect_stdout(request_log):
                call(base, "GET", f"/v1/recall?q={search_marker}")
            assert search_marker not in request_log.getvalue(), "HTTP access logs must not retain search query text"

            # Open-ended recall uses the same topic-neutral path for every
            # subject; the list can be broad while injected assistant context
            # remains bounded. All data lives in this test's temporary DB.
            expected_course_memories = []
            assert_lexical_recall_order(server)
            for index in range(16):
                text = f"User is enrolled in university course BUS{110 + index} and is studying academic management topic {index}."
                expected_course_memories.append(text)
                server.save_memory({"text": text, "kind": "fact"}, "smoke", f"education-{index}", None)
            server.save_memory({"text": "User prefers concise LinkedIn posts about marketing campaigns.", "kind": "preference"}, "smoke", "unrelated", None)
            bilingual = server.save_memory({
                "text": "The user studies at Al Noor University.", "kind": "fact",
                "metadata": {"text_language": "ar", "localized": {"ar": "يدرس المستخدم في جامعة النور.", "en": "The user studies at Al Noor University."}},
            }, "smoke", "bilingual-university", None)
            arabic_index_hits = server.search_memories("جامعة النور", limit=10, rerank=False)
            assert any(item["id"] == bilingual["id"] for item in arabic_index_hits), "Arabic search must find an English canonical memory through its localized index"
            arabic_view = server.interactive_context("ما اسم الجامعة؟", limit=100)
            assert arabic_view["query_language"] == "ar"
            arabic_match = next(item for item in arabic_view["search_results"] if item["id"] == bilingual["id"])
            assert arabic_match["display_text"] == "يدرس المستخدم في جامعة النور."
            assert arabic_match["display_language"] == "ar"
            english_view = server.interactive_context("Which university does the user attend?", limit=100)
            assert english_view["query_language"] == "en"
            english_match = next(item for item in english_view["search_results"] if item["id"] == bilingual["id"])
            assert english_match["display_text"] == "The user studies at Al Noor University."
            assert "education.university" in bilingual["categories"]

            # Low-ranked candidates remain visible for inspection but must not
            # leak into the bounded context sent to an assistant.
            original_unified_recall = server.unified_recall
            server.unified_recall = lambda _query, _limit: ([
                {"id": "strong-room", "text": "The user's home is in Riyadh.", "reranker_score": -2.0, "confidence": 0.9},
                {"id": "weak-room", "text": "The user likes English lessons.", "reranker_score": -7.0, "confidence": 0.9},
            ], {"providers": {}})
            try:
                room_view = server.interactive_context("Tell me about the user's home", limit=10)
            finally:
                server.unified_recall = original_unified_recall
            assert [item["id"] for item in room_view["context_packet"]] == ["strong-room"]
            assert {item["id"]: item["match_quality"] for item in room_view["search_results"]} == {"strong-room": "strong", "weak-room": "possible"}
            assert room_view["recall"]["possible_results"] == 1

            broad_recall = server.interactive_context("Tell me everything about university", limit=100)
            returned_texts = {item["text"] for item in broad_recall["search_results"]}
            assert set(expected_course_memories) <= returned_texts, "broad retrieval should include related records without an education-only scan"
            assert not any("LinkedIn posts about marketing" in text for text in returned_texts), "broad university query must keep unrelated memories out"
            assert len(broad_recall["context_packet"]) <= 12, "assistant context must remain bounded separately from browsable search results"
            assert len(broad_recall["search_results"]) > len(broad_recall["context_packet"]), "inspection results and injected context must have separate limits"

            server.save_memory({"text": "The user's home has a small garden in Riyadh.", "kind": "fact"}, "smoke", "home-garden", None)
            server.save_memory({"text": "The user's home has two bedrooms.", "kind": "fact"}, "smoke", "home-rooms", None)
            home_recall = server.interactive_context("What do you know about my home?", limit=100)
            home_texts = {item["text"] for item in home_recall["search_results"]}
            assert any("small garden" in text for text in home_texts) and any("two bedrooms" in text for text in home_texts), "a different open-ended subject must use the same broad recall behavior"
            assert len(server._general_recall_probes("وش الأشياء اللي تذكرها عن بيتي؟")) == 1, "Arabic open-ended queries should receive one generic, topic-neutral retrieval probe"
            assert "بيت" in server._generic_recall_focus("وش الأشياء اللي تذكرها عن بيتي؟"), "Arabic topic focus should reduce common inflections without relying on a subject taxonomy"
            assert "home" in server._generic_recall_focus("What do you know about my home?"), "English topic focus should keep the same topic-neutral retrieval behavior"

            # Remote generation must be opt-in and must return evidence refs.
            options_before = server.interactive_answer_options
            context_before = server.interactive_context
            request_before = server._openrouter_request
            try:
                server.interactive_answer_options = lambda: {"available": True, "provider": "openrouter", "remote": True, "destination": "OpenRouter", "may_cost": False}
                answer_secret = "sk-" + "E" * 32
                server.interactive_context = lambda _message, _limit: {
                    "query_language": "en",
                    "context_packet": [{"text": f"The user's home has a small garden in Riyadh; token {answer_secret}.", "source": "smoke", "date": "2026-09-25"}],
                }
                answer_requests: list[str] = []
                def capture_answer_request(*args, **kwargs):
                    answer_requests.append(json.dumps(kwargs.get("payload", {}), ensure_ascii=False))
                    return {"choices": [{"message": {"content": json.dumps({"answer": "The home has a small garden in Riyadh [1].", "citations": [1]})}}]}
                server._openrouter_request = capture_answer_request
                server.INTERACTIVE_ANSWER_REQUESTS.clear()
                consent = server.interactive_answer(f"What do you know about my home? {answer_secret}", allow_external=False, client_key="test")
                assert consent["status"] == "consent_required", "remote model must not receive memories before explicit consent"
                answer = server.interactive_answer(f"What do you know about my home? {answer_secret}", allow_external=True, client_key="test")
                assert answer_requests and answer_secret not in answer_requests[0], "remote answers must redact recognizable secrets from both question and memory context"
                assert answer["status"] == "ok" and answer["citations"] == [1] and answer["references"][0]["source"] == "smoke"
            finally:
                server.interactive_answer_options = options_before
                server.interactive_context = context_before
                server._openrouter_request = request_before

            plain_request = urllib.request.Request(
                f"{base}/v1/remember",
                data=b"{}",
                headers={"Content-Type": "text/plain"},
                method="POST",
            )
            try:
                urllib.request.urlopen(plain_request, timeout=10)
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
            else:
                raise AssertionError("non-JSON POST bodies must be rejected")

            connection = HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
            connection.putrequest("POST", "/v1/remember")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", "-1")
            connection.endheaders()
            response = connection.getresponse()
            assert response.status == 400
            response.read()
            connection.close()

            imported = call(base, "POST", "/v1/import", {
                "source": "smoke",
                "documents": [
                    {"conversation_id": "conversation-a", "messages": [{"role": "user", "content": "I prefer concise answers."}]},
                    {"conversation_id": "conversation-b", "messages": [{"role": "user", "content": "We decided to use SQLite."}]},
                ],
            })
            assert imported["processed"] == 2
            recall = call(base, "GET", "/v1/recall?q=concise")
            assert recall["memories"], "expected imported memory to be recallable"

            conflict_batch = call(base, "POST", "/v1/import", {
                "source": "smoke",
                "documents": [{"conversation_id": "conversation-a", "text": "I prefer very long answers."}],
            })
            assert conflict_batch["conflicts"] == 1
            conflicts = call(base, "GET", "/v1/conflicts?status=open")
            assert len(conflicts["conflicts"]) == 1
            conflict_id = conflicts["conflicts"][0]["id"]
            resolved = call(base, "POST", "/v1/conflicts/resolve", {"conflict_id": conflict_id, "status": "ignored"})
            assert resolved["conflict"]["status"] == "ignored"

            deleted = call(base, "POST", "/v1/ingest", {
                "source": "smoke",
                "conversation_id": "delete-after-success",
                "messages": [{"role": "user", "content": "I prefer safe deletion."}],
                "delete_after_success": True,
            })
            assert deleted["status"] == "processed" and deleted["deleted_after_success"] is True

            retention = call(base, "POST", "/v1/retention", {"max_age_days": 0, "apply": False})
            assert retention["status"] == "dry_run"

            backup = call(base, "POST", "/v1/backup", {})
            marker = call(base, "POST", "/v1/remember", {"source": "smoke", "text": "restore-only marker"})
            assert marker["status"] == "saved"
            restored = call(base, "POST", "/v1/restore", {"path": backup["path"], "confirm": "RESTORE"})
            assert restored["status"] == "restored"
            marker_recall = call(base, "GET", "/v1/recall?q=restore-only")
            assert not marker_recall["memories"], "restore should remove data added after the backup"
            print(json.dumps({"health": True, "imported": imported["processed"], "conflict": True, "retention": True, "backup_restore": True}))
        finally:
            httpd.shutdown()
            httpd.server_close()
            server.DB.close()


if __name__ == "__main__":
    main()
