"""Subprocess environment boundary tests with synthetic secrets only."""

import unittest
from pathlib import Path

from gateway.subprocess_policy import build_mempalace_child_env


class MemPalaceSubprocessPolicyTests(unittest.TestCase):
    def test_child_receives_only_platform_paths_and_local_storage(self):
        parent = {
            "PATH": r"C:\Python312;C:\Windows\System32",
            "SYSTEMROOT": r"C:\Windows",
            "TEMP": r"C:\Temp",
            "OPENROUTER_API_KEY": "synthetic-secret",
            "HTTP_PROXY": "http://127.0.0.1:9999",
            "MEMORY_GATEWAY_EGRESS_ALLOWLIST": "https://unexpected.example.test",
            "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED": "true",
            "PYTHONPATH": r"C:\private\modules",
        }
        child = build_mempalace_child_env(parent, Path("palace"), Path("sources"))
        self.assertEqual(child["PATH"], parent["PATH"])
        self.assertEqual(child["SYSTEMROOT"], parent["SYSTEMROOT"])
        self.assertEqual(child["MEMPALACE_PALACE_PATH"], "palace")
        self.assertEqual(child["MEMPALACE_SOURCE_PATH"], "sources")
        self.assertEqual(child["HF_HUB_OFFLINE"], "1")
        self.assertEqual(child["HF_HUB_DISABLE_TELEMETRY"], "1")
        for name in ("OPENROUTER_API_KEY", "HTTP_PROXY", "MEMORY_GATEWAY_EGRESS_ALLOWLIST", "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED", "PYTHONPATH"):
            self.assertNotIn(name, child)


if __name__ == "__main__":
    unittest.main()
