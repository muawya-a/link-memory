"""MCP tools must not forward internal retrieval topology to the client."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "gateway"))
import mcp_server


class McpCustomerProjectionTests(unittest.TestCase):
    def call_with(self, name, payload, arguments=None):
        with patch.object(mcp_server, "gateway_request", return_value=payload):
            result = mcp_server.call_tool(name, arguments or {})
        return result, json.dumps(result, ensure_ascii=False)

    def test_status_exposes_link_state_without_service_and_provider_details(self):
        result, serialized = self.call_with("memory_status", {
            "ok": True,
            "service": "INTERNAL_GATEWAY_SERVICE_SENTINEL",
            "providers": {"graphiti": {"model": "INTERNAL_MODEL_SENTINEL", "url": "INTERNAL_URL_SENTINEL"}},
        })
        self.assertEqual(result["structuredContent"], {"available": True})
        self.assertNotIn("INTERNAL_", serialized)

    def test_status_and_layer_states_fail_closed_on_non_boolean_values(self):
        status, _ = self.call_with("memory_status", {"ok": "false", "providers": {}})
        self.assertEqual(status["structuredContent"], {"available": False})
        layers, _ = self.call_with("memory_layers", {
            "ok": "false",
            "status": {"openmemory": {"available": "false"}, "graphiti": None, "mempalace": {"available": True}},
        })
        self.assertEqual(layers["structuredContent"], {
            "available": False,
            "layers": [
                {"kind": "facts_and_decisions", "available": False},
                {"kind": "events_and_relationships", "available": False},
                {"kind": "original_sources", "available": True},
            ],
        })

    def test_layers_expose_capabilities_as_concepts_not_provider_topology(self):
        raw = {
            "ok": True,
            "topology": "INTERNAL_TOPOLOGY_SENTINEL",
            "join_keys": ["INTERNAL_JOIN_KEY_SENTINEL"],
            "layers": {
                "openmemory": {"role": "facts", "name": "INTERNAL_PROVIDER_SENTINEL", "link_counts": {"id": "INTERNAL_LINK_SENTINEL"}},
                "graphiti": {"role": "relationships", "name": "INTERNAL_PROVIDER_SENTINEL", "retrieval_stats": {"score": "INTERNAL_STATS_SENTINEL"}},
                "mempalace": {"role": "source_text", "name": "INTERNAL_PROVIDER_SENTINEL"},
            },
            "status": {
                "openmemory": {"available": True, "url": "INTERNAL_URL_SENTINEL"},
                "graphiti": {"available": False, "error": "INTERNAL_ERROR_SENTINEL"},
                "mempalace": {"available": True},
            },
        }
        result, serialized = self.call_with("memory_layers", raw)
        self.assertEqual(result["structuredContent"], {
            "available": True,
            "layers": [
                {"kind": "facts_and_decisions", "available": True},
                {"kind": "events_and_relationships", "available": False},
                {"kind": "original_sources", "available": True},
            ],
        })
        self.assertNotIn("INTERNAL_", serialized)

    def test_recall_keeps_memory_evidence_but_omits_provider_ids_scores_and_trace(self):
        result, serialized = self.call_with("memory_recall", {
            "query": "synthetic question",
            "memories": [{
                "id": "INTERNAL_MEMORY_ID_SENTINEL",
                "text": "Synthetic evidence remains visible.",
                "type": "fact",
                "source": "openmemory",
                "date": "2026-09-27",
                "tags": ["preference", "openmemory", "graphiti"],
                "provider": "INTERNAL_PROVIDER_SENTINEL",
                "conversation_id": "INTERNAL_CONVERSATION_SENTINEL",
                "reranker_score": 0.99,
                "metadata": {"path": "INTERNAL_PATH_SENTINEL"},
            }],
            "recall": {"providers": {"graphiti": {"items": ["INTERNAL_TRACE_SENTINEL"]}}},
        })
        self.assertEqual(result["structuredContent"], {
            "query": "synthetic question",
            "memories": [{
                "text": "Synthetic evidence remains visible.",
                "type": "fact",
                "date": "2026-09-27",
                "tags": ["preference"],
            }],
        })
        self.assertNotIn("INTERNAL_", serialized)
        self.assertNotIn("openmemory", serialized)
        self.assertNotIn("graphiti", serialized)

    def test_interactive_context_keeps_bounded_text_but_omits_decomposition_and_diagnostics(self):
        result, serialized = self.call_with("memory_interactive_context", {
            "query": "Synthetic current question",
            "context": "- [fact] Synthetic context evidence.",
            "context_packet": [{
                "text": "Synthetic context evidence.",
                "display_text": "Synthetic context evidence.",
                "type": "fact",
                "source": "codex",
                "date": "2026-09-26",
                "id": "INTERNAL_MEMORY_ID_SENTINEL",
                "matched_queries": ["INTERNAL_QUERY_SENTINEL"],
                "match_quality": "INTERNAL_MATCH_SENTINEL",
            }],
            "search_results": [{"provider": "INTERNAL_PROVIDER_SENTINEL"}],
            "recall": {"queries": {"INTERNAL_QUERY_SENTINEL": {"providers": ["INTERNAL_TRACE_SENTINEL"]}}},
            "answer_options": {"model": "INTERNAL_MODEL_SENTINEL"},
        })
        self.assertEqual(result["structuredContent"], {
            "query": "Synthetic current question",
            "context": "- [fact] Synthetic context evidence.",
            "context_packet": [{
                "text": "Synthetic context evidence.",
                "type": "fact",
                "source": "codex",
                "date": "2026-09-26",
            }],
        })
        self.assertNotIn("INTERNAL_", serialized)

    def test_capture_returns_action_result_without_memory_or_document_identifiers(self):
        result, serialized = self.call_with("memory_capture", {
            "status": "processed",
            "saved_count": 1,
            "saved": [{"id": "INTERNAL_MEMORY_ID_SENTINEL", "text": "PRIVATE_CAPTURE_SENTINEL"}],
            "raw_document_id": "INTERNAL_RAW_DOCUMENT_SENTINEL",
            "capture_event_id": "INTERNAL_CAPTURE_EVENT_SENTINEL",
            "analyzer": "INTERNAL_ANALYZER_SENTINEL",
            "providers": {"graphiti": {"queued": True}},
            "deleted_after_success": True,
            "privacy_redactions": 1,
        }, {"source": "mcp", "text": "PRIVATE_CAPTURE_SENTINEL"})
        self.assertEqual(result["structuredContent"], {
            "status": "processed",
            "saved_count": 1,
            "deleted_after_success": True,
        })
        self.assertNotIn("INTERNAL_", serialized)
        self.assertNotIn("PRIVATE_CAPTURE_SENTINEL", serialized)

    def test_remember_and_import_expose_user_action_counts_not_backend_results(self):
        remember, remember_text = self.call_with("memory_remember", {
            "status": "saved",
            "memory": {"id": "INTERNAL_MEMORY_ID_SENTINEL", "text": "Private text", "source": "mcp"},
            "fanout": "queued",
            "archive": {"json_path": "INTERNAL_PATH_SENTINEL"},
        }, {"text": "Private text"})
        self.assertEqual(remember["structuredContent"], {"status": "saved"})
        self.assertNotIn("INTERNAL_", remember_text)
        imported, imported_text = self.call_with("memory_import", {
            "batch_id": "INTERNAL_BATCH_SENTINEL",
            "status": "partial",
            "total": 2,
            "processed": 1,
            "duplicates": 0,
            "conflicts": 1,
            "failed": 0,
            "results": [{"raw_document_id": "INTERNAL_RAW_SENTINEL", "error": "INTERNAL_ERROR_SENTINEL"}],
        }, {"source": "codex", "documents": ["synthetic"]})
        self.assertEqual(imported["structuredContent"], {
            "status": "partial", "total": 2, "processed": 1,
            "duplicates": 0, "conflicts": 1, "failed": 0,
        })
        self.assertNotIn("INTERNAL_", imported_text)

    def test_conflicts_keep_review_text_and_action_handle_without_raw_document_metadata(self):
        result, serialized = self.call_with("memory_conflicts", {"conflicts": [{
            "id": "SAFE_ACTION_HANDLE_SENTINEL",
            "source": "codex",
            "conversation_id": "INTERNAL_CONVERSATION_SENTINEL",
            "existing_document_id": "INTERNAL_EXISTING_DOCUMENT_SENTINEL",
            "incoming_document_id": "INTERNAL_INCOMING_DOCUMENT_SENTINEL",
            "reason": "INTERNAL_REASON_SENTINEL",
            "details": {
                "existing": {"id": "INTERNAL_ID_SENTINEL", "text": "Existing user evidence", "metadata": {"path": "INTERNAL_PATH_SENTINEL"}},
                "incoming": {"id": "INTERNAL_ID_SENTINEL", "text": "Proposed user evidence", "metadata": {"provider": "INTERNAL_PROVIDER_SENTINEL"}},
            },
        }]})
        self.assertEqual(result["structuredContent"], {"conflicts": [{
            "conflict_id": "SAFE_ACTION_HANDLE_SENTINEL",
            "status": "needs_review",
            "source": "codex",
            "existing": {"text": "Existing user evidence"},
            "incoming": {"text": "Proposed user evidence"},
        }]})
        for marker in ("INTERNAL_", "metadata"):
            self.assertNotIn(marker, serialized)

    def test_context_alias_and_ingest_keep_customer_results_only(self):
        context, context_text = self.call_with("memory_context", {
            "query": "Synthetic question",
            "context": "- [fact] User evidence.",
            "context_packet": [{"text": "User evidence.", "type": "fact", "source": "claude", "date": "2026-09-20", "id": "INTERNAL_ID_SENTINEL"}],
            "recall": {"providers": {"graphiti": {"error": "INTERNAL_ERROR_SENTINEL"}}},
            "answer_options": {"model": "INTERNAL_MODEL_SENTINEL"},
        })
        self.assertEqual(context["structuredContent"], {
            "query": "Synthetic question",
            "context": "- [fact] User evidence.",
            "memories": [{"text": "User evidence.", "type": "fact", "source": "claude", "date": "2026-09-20"}],
        })
        self.assertNotIn("INTERNAL_", context_text)
        ingest, ingest_text = self.call_with("memory_ingest", {
            "status": "queued", "saved_count": 0, "submitted": True,
            "retryable": True, "job_id": "INTERNAL_JOB_SENTINEL",
            "raw_document_id": "INTERNAL_RAW_SENTINEL", "provider": "INTERNAL_PROVIDER_SENTINEL",
        }, {"source": "codex", "text": "Synthetic input"})
        self.assertEqual(ingest["structuredContent"], {
            "status": "queued", "saved_count": 0, "submitted": True, "retryable": True,
        })
        self.assertNotIn("INTERNAL_", ingest_text)

    def test_conflict_resolution_projects_wrapped_result(self):
        result, serialized = self.call_with("memory_conflicts", {
            "conflict": {
                "id": "SAFE_CONFLICT_ACTION_SENTINEL",
                "status": "resolved",
                "source": "claude",
                "conversation_id": "INTERNAL_CONVERSATION_SENTINEL",
                "details": {"existing": {"text": "Previous value", "metadata": {"path": "INTERNAL_PATH_SENTINEL"}}},
            },
            "saved": {"id": "INTERNAL_MEMORY_SENTINEL"},
        }, {"conflict_id": "SAFE_CONFLICT_ACTION_SENTINEL", "resolution": "resolved"})
        self.assertEqual(result["structuredContent"], {"conflict": {
            "conflict_id": "SAFE_CONFLICT_ACTION_SENTINEL",
            "status": "resolved",
            "source": "claude",
            "existing": {"text": "Previous value"},
        }})
        self.assertNotIn("INTERNAL_", serialized)

    def test_tool_catalog_uses_product_terms_not_backend_service_names(self):
        serialized = json.dumps(mcp_server.TOOLS, ensure_ascii=False).lower()
        self.assertNotIn("openmemory", serialized)
        self.assertNotIn("graphiti", serialized)
        self.assertNotIn("mempalace", serialized)


if __name__ == "__main__":
    unittest.main()
