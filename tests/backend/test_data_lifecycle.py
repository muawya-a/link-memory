"""Local memory deletion must remove derived indexes and the managed export."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def isolated_env(root: Path) -> dict[str, str]:
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if key in os.environ
    }
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "MEMORY_GATEWAY_DATA": str(root / "data"),
        "MEMORY_GATEWAY_DB": str(root / "data" / "gateway.sqlite3"),
        "MEMORY_GATEWAY_BACKUP_DIR": str(root / "backups"),
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
        "EMBEDDING_ENABLED": "false",
        "PROVIDER_RECALL_ENABLED": "false",
        "OLLAMA_WARMUP_ENABLED": "false",
    })
    return env


def run_isolated(root: Path, code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code), str(PROJECT_ROOT)],
        cwd=PROJECT_ROOT,
        env=isolated_env(root),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


class MemoryDeletionLifecycleTests(unittest.TestCase):
    def test_permanent_delete_clears_memory_index_and_refreshes_export_but_retains_source_archive(self):
        with tempfile.TemporaryDirectory(prefix="memory-delete-lifecycle-") as directory:
            result = run_isolated(Path(directory), r'''
                import json
                import sys
                from pathlib import Path

                root = Path(sys.argv[1])
                sys.path.insert(0, str(root / "gateway"))
                import server

                export_dir = Path(server.DATA_DIR) / "managed-export"
                server.PORTABLE_ARCHIVE_DIR = export_dir
                server.PORTABLE_ARCHIVE_JSON = export_dir / "link-memory-memory-archive.json"
                server.PORTABLE_ARCHIVE_MARKDOWN = export_dir / "link-memory-memory-archive-ar.md"
                memory_id = "synthetic-memory-delete-lifecycle"
                deleted_text = "syntheticdeletioncanary extracted memory"
                localized_text = "syntheticlocalizedcanary translated memory"
                original_source_text = "synthetic-source-canary original conversation remains archived"
                timestamp = server.now_iso()
                server.archive_ingest_record(
                    original_source_text,
                    "synthetic",
                    "synthetic-delete-conversation",
                    {},
                )
                with server.DB_LOCK:
                    server.DB.execute(
                        "INSERT INTO memories(id,kind,text,source,confidence,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (memory_id, "fact", deleted_text, "synthetic", 0.9, "{}", timestamp, timestamp),
                    )
                    server.DB.execute(
                        "INSERT INTO memory_localized_fts(memory_id,language,localized_text) VALUES(?,?,?)",
                        (memory_id, "ar", localized_text),
                    )
                    server.DB.commit()
                server.write_portable_archive()
                assert deleted_text in server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8")
                assert deleted_text in server.PORTABLE_ARCHIVE_MARKDOWN.read_text(encoding="utf-8")
                assert original_source_text in server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8")

                response = server.change_memory_state({"id": memory_id, "confirm": "DELETE"}, "delete")

                assert response["status"] == "deleted"
                assert server.DB.execute(
                    "SELECT 1 FROM memory_localized_fts WHERE memory_id=?", (memory_id,)
                ).fetchone() is None, "localized search index must not retain deleted memory text"
                assert server.get_runtime_setting("portable_archive_refresh_pending") == ""
                portable = json.loads(server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8"))
                exported_memory_ids = {item["id"] for item in portable["tables"]["memories"]}
                assert memory_id not in exported_memory_ids, "managed export must no longer list the deleted memory"
                exported_json = server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8")
                exported_markdown = server.PORTABLE_ARCHIVE_MARKDOWN.read_text(encoding="utf-8")
                for exported in (exported_json, exported_markdown):
                    assert deleted_text not in exported, "managed export must not retain the deleted memory entry"
                    assert localized_text not in exported, "managed export must not retain the deleted translation"
                    assert original_source_text in exported, "separate source archive currently remains after memory deletion"
                server.DB.close()
            ''')
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_manual_edit_invalidates_stale_localized_search_and_refreshes_managed_export(self):
        with tempfile.TemporaryDirectory(prefix="memory-edit-lifecycle-") as directory:
            result = run_isolated(Path(directory), r'''
                import json
                import sys
                from pathlib import Path

                root = Path(sys.argv[1])
                sys.path.insert(0, str(root / "gateway"))
                import server

                export_dir = Path(server.DATA_DIR) / "managed-export"
                server.PORTABLE_ARCHIVE_DIR = export_dir
                server.PORTABLE_ARCHIVE_JSON = export_dir / "link-memory-memory-archive.json"
                server.PORTABLE_ARCHIVE_MARKDOWN = export_dir / "link-memory-memory-archive-ar.md"
                memory_id = "synthetic-memory-edit-lifecycle"
                original_text = "synthetic old canonical memory"
                localized_text = "synthetic old translated memory"
                edited_text = "synthetic revised canonical memory"
                timestamp = server.now_iso()
                metadata = json.dumps({"localized": {"ar": localized_text}}, ensure_ascii=False)
                with server.DB_LOCK:
                    server.DB.execute(
                        "INSERT INTO memories(id,kind,text,source,confidence,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (memory_id, "fact", original_text, "synthetic", 0.9, metadata, timestamp, timestamp),
                    )
                    server.DB.execute(
                        "INSERT INTO memory_localized_fts(memory_id,language,localized_text) VALUES(?,?,?)",
                        (memory_id, "ar", localized_text),
                    )
                    server.DB.commit()
                server.write_portable_archive()
                assert original_text in server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8")

                response = server.update_memory({"id": memory_id, "text": edited_text})

                assert response["text"] == edited_text
                assert response["portable_export_status"] == "current"
                assert server.DB.execute(
                    "SELECT 1 FROM memory_localized_fts WHERE memory_id=?", (memory_id,)
                ).fetchone() is None, "editing canonical text must invalidate old localized search text"
                current = server.DB.execute(
                    "SELECT metadata_json FROM memories WHERE id=?", (memory_id,)
                ).fetchone()
                assert "localized" not in json.loads(current["metadata_json"]), "stale translations must not remain attached to edited memory"
                assert server.get_runtime_setting("portable_archive_refresh_pending") == ""
                exported_json = server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8")
                exported_markdown = server.PORTABLE_ARCHIVE_MARKDOWN.read_text(encoding="utf-8")
                portable = json.loads(exported_json)
                current_export = next(item for item in portable["tables"]["memories"] if item["id"] == memory_id)
                assert current_export["text"] == edited_text, "managed export must reflect the successful manual edit"
                assert "localized" not in current_export["metadata_json"], "managed export must not retain a stale current translation"
                assert edited_text in exported_markdown
                assert original_text not in exported_markdown, "human-readable export must reflect the successful manual edit"
                assert localized_text not in exported_markdown
                server.DB.close()
            ''')
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_manual_edit_clears_old_vector_when_embedding_regeneration_fails(self):
        with tempfile.TemporaryDirectory(prefix="memory-edit-vector-failure-") as directory:
            result = run_isolated(Path(directory), r'''
                import json
                import sys
                from pathlib import Path

                root = Path(sys.argv[1])
                sys.path.insert(0, str(root / "gateway"))
                import server

                memory_id = "synthetic-memory-edit-vector-failure"
                original_text = "synthetic old vector canonical memory"
                edited_text = "synthetic edited vector canonical memory"
                timestamp = server.now_iso()
                with server.DB_LOCK:
                    server.DB.execute(
                        "INSERT INTO memories(id,kind,text,source,confidence,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (memory_id, "fact", original_text, "synthetic", 0.9, "{}", timestamp, timestamp),
                    )
                    server.DB.execute(
                        "INSERT INTO memory_embeddings(memory_id,model,dimensions,vector_json,created_at) VALUES(?,?,?,?,?)",
                        (memory_id, "synthetic-model", 2, json.dumps([1.0, 0.0]), timestamp),
                    )
                    server.DB.commit()
                server.write_portable_archive()
                server.embed_text = lambda value: [] if value == edited_text else [1.0, 0.0]

                response = server.update_memory({"id": memory_id, "text": edited_text})

                assert response["text"] == edited_text
                assert response["embedding_indexed"] is False
                assert server.DB.execute(
                    "SELECT 1 FROM memory_embeddings WHERE memory_id=?", (memory_id,)
                ).fetchone() is None, "failed regeneration must not leave the old vector indexed"
                assert all(item["id"] != memory_id for item in server.vector_search("synthetic lookup", 10)), "old vector must not retrieve the edited memory"
                server.DB.close()
            ''')
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_manual_edit_reports_pending_if_a_newer_export_refresh_arrives_during_write(self):
        with tempfile.TemporaryDirectory(prefix="memory-edit-export-race-") as directory:
            result = run_isolated(Path(directory), r'''
                import sys
                from pathlib import Path

                root = Path(sys.argv[1])
                sys.path.insert(0, str(root / "gateway"))
                import server

                export_dir = Path(server.DATA_DIR) / "managed-export"
                server.PORTABLE_ARCHIVE_DIR = export_dir
                server.PORTABLE_ARCHIVE_JSON = export_dir / "link-memory-memory-archive.json"
                server.PORTABLE_ARCHIVE_MARKDOWN = export_dir / "link-memory-memory-archive-ar.md"
                memory_id = "synthetic-memory-edit-export-race"
                timestamp = server.now_iso()
                with server.DB_LOCK:
                    server.DB.execute(
                        "INSERT INTO memories(id,kind,text,source,confidence,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (memory_id, "fact", "synthetic export race original", "synthetic", 0.9, "{}", timestamp, timestamp),
                    )
                    server.DB.commit()
                server.set_runtime_setting("analysis_paused", "true")
                server.write_portable_archive()

                original_retry = server.retry_pending_portable_archive_once

                def interleaved_retry():
                    # Model another edit committing after the export finishes
                    # but before update_memory reports its status.
                    refreshed = original_retry()
                    with server.DB_LOCK:
                        server.mark_portable_archive_refresh_pending_locked()
                        server.DB.commit()
                    return refreshed

                server.retry_pending_portable_archive_once = interleaved_retry
                response = server.update_memory({"id": memory_id, "text": "synthetic export race edited"})

                assert response["portable_export_status"] == "refresh_pending", response
                assert server.get_runtime_setting("portable_archive_refresh_pending"), "newer token must remain pending after older export write"
                server.DB.close()
            ''')
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_manual_edit_reports_pending_when_managed_export_refresh_fails(self):
        with tempfile.TemporaryDirectory(prefix="memory-edit-export-failure-") as directory:
            result = run_isolated(Path(directory), r'''
                import json
                import sys
                from pathlib import Path

                root = Path(sys.argv[1])
                sys.path.insert(0, str(root / "gateway"))
                import server

                export_dir = Path(server.DATA_DIR) / "managed-export"
                server.PORTABLE_ARCHIVE_DIR = export_dir
                server.PORTABLE_ARCHIVE_JSON = export_dir / "link-memory-memory-archive.json"
                server.PORTABLE_ARCHIVE_MARKDOWN = export_dir / "link-memory-memory-archive-ar.md"
                memory_id = "synthetic-memory-edit-export-failure"
                original_text = "synthetic export failure original"
                edited_text = "synthetic export failure edited"
                timestamp = server.now_iso()
                with server.DB_LOCK:
                    server.DB.execute(
                        "INSERT INTO memories(id,kind,text,source,confidence,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (memory_id, "fact", original_text, "synthetic", 0.9, "{}", timestamp, timestamp),
                    )
                    server.DB.commit()
                server.write_portable_archive()
                original_export = server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8")
                assert original_text in original_export
                server.write_portable_archive = lambda: (_ for _ in ()).throw(OSError("private-export-path-sentinel"))

                response = server.update_memory({"id": memory_id, "text": edited_text})

                assert response["text"] == edited_text
                assert response["portable_export_status"] == "refresh_pending", response
                current = server.DB.execute("SELECT text FROM memories WHERE id=?", (memory_id,)).fetchone()
                assert current["text"] == edited_text, "canonical edit must remain committed when export refresh fails"
                assert server.get_runtime_setting("portable_archive_refresh_pending"), "failed export refresh must retain a retry token"
                serialized_response = json.dumps(response, ensure_ascii=False)
                assert "private-export-path-sentinel" not in serialized_response
                assert original_text in server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8"), "previous export remains until retry"
                server.DB.close()
            ''')
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertNotIn("private-export-path-sentinel", result.stdout + result.stderr)

    def test_permanent_delete_reports_pending_when_managed_export_refresh_fails(self):
        with tempfile.TemporaryDirectory(prefix="memory-delete-export-failure-") as directory:
            result = run_isolated(Path(directory), r'''
                import json
                import sys
                from pathlib import Path

                root = Path(sys.argv[1])
                sys.path.insert(0, str(root / "gateway"))
                import server

                export_dir = Path(server.DATA_DIR) / "managed-export"
                server.PORTABLE_ARCHIVE_DIR = export_dir
                server.PORTABLE_ARCHIVE_JSON = export_dir / "link-memory-memory-archive.json"
                server.PORTABLE_ARCHIVE_MARKDOWN = export_dir / "link-memory-memory-archive-ar.md"
                memory_id = "synthetic-memory-delete-export-failure"
                memory_text = "synthetic-export-failure-canary memory text"
                timestamp = server.now_iso()
                with server.DB_LOCK:
                    server.DB.execute(
                        "INSERT INTO memories(id,kind,text,source,confidence,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (memory_id, "fact", memory_text, "synthetic", 0.9, "{}", timestamp, timestamp),
                    )
                    server.DB.commit()
                server.write_portable_archive()
                original_text = server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8")
                assert memory_text in original_text
                server.write_portable_archive = lambda: (_ for _ in ()).throw(OSError("private-export-path-sentinel"))

                response = server.change_memory_state({"id": memory_id, "confirm": "DELETE"}, "delete")

                assert response["status"] == "deleted", response
                assert response["portable_export_status"] == "refresh_pending", response
                assert server.DB.execute("SELECT 1 FROM memories WHERE id=?", (memory_id,)).fetchone() is None
                assert server.get_runtime_setting("portable_archive_refresh_pending"), "failed refresh must keep a retry token"
                assert "private-export-path-sentinel" not in json.dumps(response)
                assert memory_text in server.PORTABLE_ARCHIVE_JSON.read_text(encoding="utf-8"), "failed filesystem refresh leaves the previous export until retry"
                server.DB.close()
            ''')
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
