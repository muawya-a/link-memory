from __future__ import annotations

import ipaddress
import sys
import urllib.parse
import uuid
from http import HTTPStatus

if __package__:
    from .routes.ingest import handle_ingest
    from .routes.remember import handle_remember
else:
    from routes.ingest import handle_ingest
    from routes.remember import handle_remember


LOCAL_HOOK_CONTEXT_PATHS = {
    "/v1/hooks/codex/user-prompt-context",
    "/v1/hooks/claude/user-prompt-context",
}


class RequestParameterError(ValueError):
    """A malformed client parameter with a fixed, non-echoing message."""


def _request_int(value, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        raise RequestParameterError(f"{field} must be an integer") from None


def handle_get(handler, services, parsed):
        if parsed.path in {"/health", "/v1/status"}:
            if not services.auth_ok(handler):
                handler.send_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            with services.DB_LOCK:
                counts = {
                    "memories": services.DB.execute("SELECT COUNT(*) FROM memories WHERE archived=0").fetchone()[0],
                    "raw_documents": services.DB.execute("SELECT COUNT(*) FROM raw_documents").fetchone()[0],
                    "conversations": services.DB.execute("SELECT COUNT(DISTINCT NULLIF(conversation_id,'')) FROM capture_events").fetchone()[0],
                    "messages": services.DB.execute("SELECT COALESCE(SUM(message_count),0) FROM capture_events").fetchone()[0],
                    "memory_versions": services.DB.execute("SELECT COUNT(*) FROM memory_versions").fetchone()[0],
                    "embeddings": services.DB.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0],
                    "provider_links": services.DB.execute("SELECT COUNT(*) FROM provider_links").fetchone()[0],
                    "open_conflicts": services.DB.execute("SELECT COUNT(*) FROM conflicts WHERE status='open'").fetchone()[0],
                    "analysis_jobs": services.DB.execute("SELECT COUNT(*) FROM analysis_jobs WHERE status IN ('queued','running')").fetchone()[0],
                }
            handler.send_json({"ok": True, "service": "memory-gateway", "version": "0.1.1", "counts": counts, "providers": services.provider_status(), "ollama": {"enabled": services.OLLAMA_ENABLED, "model": services.OLLAMA_MODEL, "embedding_model": services.OLLAMA_EMBED_MODEL, "keep_alive": services.OLLAMA_KEEP_ALIVE, "warmup": dict(services.WARMUP_STATE)}, "analysis": services.analysis_status()})
            return
        if not services.auth_ok(handler):
            handler.send_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        if parsed.path == "/v1/recall":
            query = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
            kind = urllib.parse.parse_qs(parsed.query).get("type", [None])[0]
            memories, trace = services.unified_recall(query, kind=kind)
            handler.send_json({"query": query, "memories": memories, "recall": trace, "providers": services.provider_status()})
            return
        if parsed.path in {"/v1/context", "/v1/interactive/context"}:
            query = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
            handler.send_json(services.interactive_context(query))
            return
        if parsed.path == "/v1/conflicts":
            status = urllib.parse.parse_qs(parsed.query).get("status", [None])[0]
            handler.send_json({"conflicts": services.list_conflicts(status)})
            return
        if parsed.path == "/v1/jobs":
            job_id = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
            if not job_id:
                handler.send_json({"error": "id is required"}, HTTPStatus.BAD_REQUEST)
                return
            handler.send_json({"job": services.analysis_job(job_id)})
            return
        if parsed.path == "/v1/links":
            memory_id = urllib.parse.parse_qs(parsed.query).get("memory_id", [None])[0]
            handler.send_json({"links": services.list_provider_links(memory_id)})
            return
        if parsed.path == "/v1/metrics":
            handler.send_json({"metrics": services.metrics()})
            return
        if parsed.path == "/v1/monitoring":
            handler.send_json(services.monitoring_snapshot())
            return
        if parsed.path == "/v1/hooks":
            handler.send_json(services.hooks_status())
            return
        if parsed.path == "/v1/captures":
            query = urllib.parse.parse_qs(parsed.query)
            limit = query.get("limit", ["100"])[0]
            include_internal = query.get("include_internal", ["0"])[0].lower() in {"1", "true", "yes"}
            handler.send_json({"captures": services.list_capture_events(_request_int(limit, "limit"), include_internal)})
            return
        if parsed.path == "/v1/review":
            query = urllib.parse.parse_qs(parsed.query)
            handler.send_json({"review": services.list_review_items(query.get("status", ["open"])[0], _request_int(query.get("limit", ["100"])[0], "limit"))})
            return
        if parsed.path == "/v1/memories":
            query = urllib.parse.parse_qs(parsed.query)
            filters = {key: values[0] for key, values in query.items() if values}
            if "limit" in filters:
                filters["limit"] = _request_int(filters["limit"], "limit")
            handler.send_json({"memories": services.list_memories(filters)})
            return
        if parsed.path == "/v1/search/advanced":
            query = urllib.parse.parse_qs(parsed.query)
            filters = {key: values[0] for key, values in query.items() if values}
            if "limit" in filters:
                filters["limit"] = _request_int(filters["limit"], "limit")
            results = services.advanced_search(filters)
            handler.send_json({"memories": results, "filters": filters, "meta": {"mode": "hybrid" if filters.get("q") else "filtered", "reranked": bool(filters.get("q") and services.RERANKER_ENABLED and services.runtime_flag("local_reranker_enabled", True)), "count": len(results)}})
            return
        if parsed.path == "/v1/search/catalog":
            handler.send_json(services.search_catalog())
            return
        if parsed.path == "/v1/memory/explain":
            memory_id = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
            handler.send_json(services.memory_explain(memory_id))
            return
        if parsed.path == "/v1/backups":
            handler.send_json({"backups": services.list_backups()})
            return
        if parsed.path == "/v1/retry":
            provider = urllib.parse.parse_qs(parsed.query).get("provider", [None])[0]
            all_links = services.list_provider_links()
            failed = [link for link in all_links if link["status"] == "failed" and int(link.get("attempts") or 0) < services.RETRY_MAX_ATTEMPTS and (not provider or link["provider"] == provider)]
            handler.send_json({"links": failed, "ready": len(failed), "exhausted": sum(1 for link in all_links if link["status"] == "failed" and int(link.get("attempts") or 0) >= services.RETRY_MAX_ATTEMPTS and (not provider or link["provider"] == provider))})
            return
        if parsed.path == "/v1/analysis/status":
            handler.send_json(services.analysis_status())
            return
        if parsed.path == "/v1/performance":
            handler.send_json(services.performance_report())
            return
        if parsed.path == "/v1/openrouter/status":
            handler.send_json(services.openrouter_status())
            return
        if parsed.path == "/v1/models/status":
            handler.send_json(services.model_runtime_status())
            return
        if parsed.path == "/v1/memory-layers":
            handler.send_json(services.memory_layer_overview())
            return
        if parsed.path == "/v1/gpu/status":
            handler.send_json(services.gpu_guard_status())
            return
        if parsed.path == "/v1/openrouter/models":
            refresh = urllib.parse.parse_qs(parsed.query).get("refresh", ["0"])[0].lower() in {"1", "true", "yes"}
            try:
                handler.send_json(services.openrouter_catalog(refresh))
            except Exception:
                handler.send_json({"error": "model catalog unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if parsed.path == "/v1/accounts":
            handler.send_json({"accounts": services.list_source_accounts()})
            return
        if parsed.path == "/v1/mcp/status":
            handler.send_json(services.mcp_status())
            return
        if parsed.path == "/v1/archive/status":
            handler.send_json(services.portable_archive_status())
            return
        handler.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)


def _send_internal_error(handler, exc: Exception) -> None:
    error_id = str(uuid.uuid4())
    print(f"Gateway error {error_id} ({type(exc).__name__})", file=sys.stderr, flush=True)
    handler.send_json({"error": "internal error", "error_id": error_id}, HTTPStatus.INTERNAL_SERVER_ERROR)


def handle_get_safely(handler, services, parsed):
    """Map malformed GET parameters and unexpected failures without tracebacks."""
    try:
        handle_get(handler, services, parsed)
    except RequestParameterError:
        handler.send_json({"error": "invalid request"}, HTTPStatus.BAD_REQUEST)
    except ValueError as exc:
        if str(exc) in {"analysis job not found", "memory not found"}:
            handler.send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        else:
            _send_internal_error(handler, exc)
    except Exception as exc:
        _send_internal_error(handler, exc)


def handle_post(handler, services):
        if not services.auth_ok(handler):
            handler.send_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        path = urllib.parse.urlparse(handler.path).path
        if path == "/v1/mcp/connect":
            try:
                address = ipaddress.ip_address(str(handler.client_address[0]).split("%", 1)[0])
                is_loopback = address.is_loopback or bool(address.ipv4_mapped and address.ipv4_mapped.is_loopback)
            except (AttributeError, ValueError, TypeError):
                is_loopback = False
            if not is_loopback:
                handler.send_json({"error": "client setup is local only"}, HTTPStatus.FORBIDDEN)
                return
        if path in LOCAL_HOOK_CONTEXT_PATHS:
            try:
                address = ipaddress.ip_address(str(handler.client_address[0]).split("%", 1)[0])
                is_loopback = address.is_loopback or bool(address.ipv4_mapped and address.ipv4_mapped.is_loopback)
            except (AttributeError, ValueError, TypeError):
                is_loopback = False
            if not is_loopback:
                handler.send_json({"error": "local hook endpoint only"}, HTTPStatus.FORBIDDEN)
                return
            if not getattr(services, "API_KEY", ""):
                handler.send_json({"error": "local hook authentication is not configured"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            try:
                content_length = int(getattr(handler, "headers", {}).get("Content-Length", "0"))
            except (TypeError, ValueError):
                handler.send_json({"error": "invalid request size"}, HTTPStatus.BAD_REQUEST)
                return
            if content_length > 256 * 1024:
                handler.send_json({"error": "request is too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
        try:
            payload = handler.read_json()
            if path == "/v1/ingest":
                handle_ingest(handler, services, payload)
            elif path == "/v1/import":
                handler.send_json(services.import_batch(payload), HTTPStatus.ACCEPTED)
            elif path == "/v1/remember":
                handle_remember(handler, services, payload)
            elif path == "/v1/recall":
                memories, trace = services.unified_recall(str(payload.get("query", "")), _request_int(payload.get("limit", 8), "limit"), payload.get("type"))
                handler.send_json({"query": payload.get("query", ""), "memories": memories, "recall": trace, "providers": services.provider_status()})
            elif path in {"/v1/context", "/v1/interactive/context"}:
                handler.send_json(services.interactive_context(str(payload.get("message", payload.get("text", payload.get("query", "")))), _request_int(payload.get("limit", 8), "limit")))
            elif path in LOCAL_HOOK_CONTEXT_PATHS:
                try:
                    message = str(payload.get("message", ""))[:2000]
                    limit = max(1, min(int(payload.get("limit", 3)), 3))
                except (TypeError, ValueError):
                    handler.send_json({"error": "invalid local hook request"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    result = services.hook_local_context(message, limit)
                except Exception:
                    handler.send_json({"error": "local hook context unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                handler.send_json(result)
            elif path == "/v1/interactive/answer":
                handler.send_json(services.interactive_answer(
                    str(payload.get("message", "")),
                    allow_external=payload.get("allow_external") is True,
                    client_key=str(handler.client_address[0]),
                ))
            elif path == "/v1/conflicts/resolve":
                handler.send_json({"conflict": services.resolve_conflict(payload)})
            elif path == "/v1/retention":
                handler.send_json(services.apply_retention(payload))
            elif path == "/v1/backup":
                handler.send_json(services.create_backup(payload), HTTPStatus.CREATED)
            elif path == "/v1/archive/export":
                handler.send_json(services.write_portable_archive(), HTTPStatus.CREATED)
            elif path == "/v1/restore":
                handler.send_json(services.restore_backup(payload))
            elif path == "/v1/reindex":
                handler.send_json(services.reindex_embeddings())
            elif path == "/v1/metrics/refresh":
                handler.send_json({"metrics": services.metrics()})
            elif path == "/v1/captures":
                handler.send_json({"captures": services.list_capture_events(_request_int(payload.get("limit", 100), "limit"))})
            elif path == "/v1/review/resolve":
                handler.send_json({"review": services.resolve_review_item(payload)})
            elif path == "/v1/memory/update":
                handler.send_json({"memory": services.update_memory(payload)})
            elif path == "/v1/memory/archive":
                handler.send_json(services.change_memory_state(payload, "archive"))
            elif path == "/v1/memory/delete":
                handler.send_json(services.change_memory_state(payload, "delete"))
            elif path == "/v1/memory/merge":
                handler.send_json(services.merge_memories(payload))
            elif path == "/v1/preview":
                handler.send_json(services.preview_document(payload))
            elif path == "/v1/health/check":
                handler.send_json(services.run_health_check())
            elif path == "/v1/retry":
                handler.send_json(services.retry_failed_links(payload.get("provider"), payload.get("memory_id")), HTTPStatus.ACCEPTED)
            elif path == "/v1/backup/verify":
                handler.send_json(services.verify_backup(payload))
            elif path == "/v1/analysis/pause":
                handler.send_json(services.set_analysis_pause(bool(payload.get("paused", True))))
            elif path == "/v1/analysis/retry":
                handler.send_json(services.retry_analysis_job(str(payload.get("job_id", ""))) if payload.get("job_id") else services.retry_failed_analysis(_request_int(payload.get("limit", 100), "limit")))
            elif path == "/v1/openrouter/config":
                handler.send_json(services.configure_openrouter(payload))
            elif path == "/v1/privacy/external-ingest-consent":
                handler.send_json(services.configure_external_ingest_consent(payload))
            elif path == "/v1/provider/catalog":
                handler.send_json(services.provider_model_catalog(payload.get("provider"), payload.get("api_key")))
            elif path == "/v1/provider/discover":
                handler.send_json(services.discover_openai_compatible_models(payload.get("base_url"), payload.get("api_key", "")))
            elif path == "/v1/provider/test":
                handler.send_json(services.test_provider_connection(payload.get("provider"), payload.get("api_key", "")))
            elif path == "/v1/models/config":
                handler.send_json(services.configure_model_runtime(payload))
            elif path == "/v1/hooks":
                handler.send_json(services.set_hook_enabled(payload))
            elif path == "/v1/accounts":
                handler.send_json({"account": services.save_source_account(payload), "accounts": services.list_source_accounts()})
            elif path == "/v1/mcp/connect":
                handler.send_json(services.connect_mcp_client(payload))
            else:
                handler.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except PermissionError as exc:
            _send_internal_error(handler, exc)
        except ValueError as exc:
            handler.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # keep the local service alive without leaking internals
            error_id = str(uuid.uuid4())
            print(f"Gateway error {error_id} ({type(exc).__name__})", file=sys.stderr, flush=True)
            handler.send_json({"error": "internal error", "error_id": error_id}, HTTPStatus.INTERNAL_SERVER_ERROR)
