"""Process-interruption recovery contracts using temporary synthetic databases."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def gateway_env(root: Path) -> dict[str, str]:
    """Keep the child environment small and route every Gateway path to temp."""
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


def run_child(root: Path, code: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, "-c", code, *args],
        cwd=PROJECT_ROOT,
        env=gateway_env(root),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


class RestoreCrashRecoveryTests(unittest.TestCase):
    def exercise_interruption(self, boundary: str, expected_current: set[str]) -> None:
        with tempfile.TemporaryDirectory(prefix=f"restore-crash-{boundary}-") as temp:
            root = Path(temp)
            setup = run_child(root, """
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "gateway"))
import server
data_root = Path(os.environ["MEMORY_GATEWAY_DATA"]).resolve()
assert server.DATA_DIR.resolve() == data_root
assert server.DB_PATH.resolve() == Path(os.environ["MEMORY_GATEWAY_DB"]).resolve()
assert server.BACKUP_DIR.resolve() == Path(os.environ["MEMORY_GATEWAY_BACKUP_DIR"]).resolve()
assert not any((server.OLLAMA_ENABLED, server.RERANKER_ENABLED, server.OPENMEMORY_ENABLED, server.GRAPHITI_ENABLED, server.MEMPALACE_ENABLED, server.EMBEDDING_ENABLED, server.PROVIDER_RECALL_ENABLED, server.OLLAMA_WARMUP_ENABLED))
assert not any((server.OLLAMA_URL, server.RERANKER_URL, server.OPENMEMORY_URL, server.GRAPHITI_URL, server.MEMPALACE_URL, server.OPENROUTER_URL))
baseline = server.save_memory({"text": "synthetic pre-restore baseline marker"}, "crash-test", "baseline-marker", "2026-09-26")
backup = server.create_backup({})
active = server.save_memory({"text": "synthetic active-state marker"}, "crash-test", "active-marker", "2026-09-26")
server.DB.commit()
print(json.dumps({"backup": backup["path"], "baseline_id": baseline["id"], "active_id": active["id"]}))
server.DB.close()
""")
            self.assertEqual(setup.returncode, 0, setup.stderr or setup.stdout)
            setup_result = json.loads(setup.stdout.strip().splitlines()[-1])
            backup_path = str(Path(setup_result["backup"]).resolve())
            baseline_id = setup_result["baseline_id"]
            active_id = setup_result["active_id"]
            expected_current = {
                setup_result.get(f"{marker}_id", marker)
                for marker in expected_current
            }

            crash = run_child(root, """
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "gateway"))
import server
data_root = Path(os.environ["MEMORY_GATEWAY_DATA"]).resolve()
assert server.DATA_DIR.resolve() == data_root
assert server.DB_PATH.resolve() == Path(os.environ["MEMORY_GATEWAY_DB"]).resolve()
assert server.BACKUP_DIR.resolve() == Path(os.environ["MEMORY_GATEWAY_BACKUP_DIR"]).resolve()
assert not any((server.OLLAMA_ENABLED, server.RERANKER_ENABLED, server.OPENMEMORY_ENABLED, server.GRAPHITI_ENABLED, server.MEMPALACE_ENABLED, server.EMBEDDING_ENABLED, server.PROVIDER_RECALL_ENABLED, server.OLLAMA_WARMUP_ENABLED))
assert not any((server.OLLAMA_URL, server.RERANKER_URL, server.OPENMEMORY_URL, server.GRAPHITI_URL, server.MEMPALACE_URL, server.OPENROUTER_URL))
mode, backup_path = sys.argv[1], sys.argv[2]
real_replace = Path.replace
database_path = server.DB_PATH.resolve()
def interrupt_replace(source, target):
    if source.name.startswith(f".{database_path.name}.restore-") and Path(target).resolve() == database_path:
        if mode == "before":
            os._exit(71)
        result = real_replace(source, target)
        os._exit(72)
    return real_replace(source, target)
Path.replace = interrupt_replace
server.restore_backup({"path": backup_path, "confirm": "RESTORE"})
raise AssertionError("the injected process interruption did not fire")
""", boundary, backup_path)
            expected_exit = 71 if boundary == "before" else 72
            self.assertEqual(crash.returncode, expected_exit, crash.stderr or crash.stdout)

            database_path = root / "data" / "gateway.sqlite3"
            current = sqlite3.connect(database_path)
            try:
                self.assertEqual(current.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                current_ids = {
                    row[0]
                    for row in current.execute(
                        "SELECT id FROM memories WHERE source='crash-test'"
                    ).fetchall()
                }
            finally:
                current.close()
            self.assertEqual(current_ids, expected_current)

            before_images = list((root / "data").glob(".gateway.sqlite3.pre-restore-*.sqlite3"))
            self.assertEqual(len(before_images), 1, "a terminated restore must leave its before-image for recovery")
            before = sqlite3.connect(before_images[0])
            try:
                self.assertEqual(before.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                before_ids = {
                    row[0]
                    for row in before.execute(
                        "SELECT id FROM memories WHERE source='crash-test'"
                    ).fetchall()
                }
            finally:
                before.close()
            self.assertEqual(before_ids, {baseline_id, active_id})

            restart = run_child(root, """
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "gateway"))
import server
try:
    data_root = Path(os.environ["MEMORY_GATEWAY_DATA"]).resolve()
    assert server.DATA_DIR.resolve() == data_root
    assert server.DB_PATH.resolve() == Path(os.environ["MEMORY_GATEWAY_DB"]).resolve()
    assert server.BACKUP_DIR.resolve() == Path(os.environ["MEMORY_GATEWAY_BACKUP_DIR"]).resolve()
    assert not any((server.OLLAMA_ENABLED, server.RERANKER_ENABLED, server.OPENMEMORY_ENABLED, server.GRAPHITI_ENABLED, server.MEMPALACE_ENABLED, server.EMBEDDING_ENABLED, server.PROVIDER_RECALL_ENABLED, server.OLLAMA_WARMUP_ENABLED))
    assert not any((server.OLLAMA_URL, server.RERANKER_URL, server.OPENMEMORY_URL, server.GRAPHITI_URL, server.MEMPALACE_URL, server.OPENROUTER_URL))
    assert server.DB.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    ids = {row[0] for row in server.DB.execute("SELECT id FROM memories WHERE source='crash-test'").fetchall()}
    assert ids == set(sys.argv[1:])
finally:
    server.DB.close()
""", *sorted(expected_current))
            self.assertEqual(restart.returncode, 0, restart.stderr or restart.stdout)

    def test_restore_interrupted_before_atomic_replace_keeps_old_database_and_recovery_copy(self) -> None:
        self.exercise_interruption("before", {"baseline", "active"})

    def test_restore_interrupted_after_atomic_replace_keeps_restored_database_and_recovery_copy(self) -> None:
        self.exercise_interruption("after", {"baseline"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
