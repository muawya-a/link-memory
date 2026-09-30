"""Launch the existing Gateway with project .env keys blocked in local staging."""

from __future__ import annotations

import os
import re
import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_KEY = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", re.IGNORECASE)


def block_project_env(env_file: Path) -> None:
    """Only inspect names; empty values block server.py's setdefault import."""
    if not env_file.is_file():
        return
    with env_file.open(encoding="utf-8-sig") as stream:
        for line in stream:
            match = ENV_KEY.match(line)
            if match:
                os.environ[match.group(1)] = ""
                # The current Gateway parser treats "export KEY" as a literal
                # environment name. Block that spelling as well.
                raw_name = line.split("=", 1)[0].strip()
                if raw_name != match.group(1):
                    os.environ[raw_name] = ""


def apply_staging_settings(project_root: Path) -> None:
    data = project_root / "staging-data"
    settings = {
        "MEMORY_GATEWAY_DATA": str(data),
        "MEMORY_GATEWAY_DB": str(data / "sandbox.sqlite3"),
        "MEMORY_GATEWAY_BACKUP_DIR": str(data / "backups"),
        "MEMORY_GATEWAY_INBOX": str(data / "inbox"),
        "MEMORY_GATEWAY_PROCESSED": str(data / "processed"),
        "MEMORY_GATEWAY_HOST": "127.0.0.1",
        "MEMORY_GATEWAY_PORT": "28000",
        "MEMORY_DASHBOARD_HOST": "127.0.0.1",
        "MEMORY_DASHBOARD_PORT": "28765",
        "MEMORY_GATEWAY_URL": "http://127.0.0.1:28000",
        "MEMORY_GATEWAY_CORS_ORIGINS": "http://127.0.0.1:28765,http://localhost:28765",
        "MEMORY_GATEWAY_ALLOW_LAN_CORS": "false",
        "MEMORY_GATEWAY_EGRESS_ALLOWLIST": "",
        "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED": "false",
        "MEMORY_GATEWAY_NEO4J_ALLOWLIST": "",
        "OLLAMA_ENABLED": "false",
        "OLLAMA_WARMUP_ENABLED": "false",
        "RERANKER_ENABLED": "false",
        "EMBEDDING_ENABLED": "false",
        "PROVIDER_RECALL_ENABLED": "false",
        "OPENMEMORY_ENABLED": "false",
        "GRAPHITI_ENABLED": "false",
        "MEMPALACE_ENABLED": "false",
        "OLLAMA_URL": "",
        "RERANKER_URL": "",
        "OPENMEMORY_URL": "",
        "GRAPHITI_URL": "",
        "MEMPALACE_URL": "",
        "OPENROUTER_URL": "",
        "MODEL_API_KEY": "",
        "OPENROUTER_API_KEY": "",
        "GRAPHITI_OPENROUTER_API_KEY": "",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "GEMINI_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
        "XAI_API_KEY": "",
        "AWS_ACCESS_KEY_ID": "",
        "AWS_SECRET_ACCESS_KEY": "",
        "MEMORY_GATEWAY_API_KEY": "",
        "OPENROUTER_LOCAL_FALLBACK": "false",
        "PRIVACY_REDACTION_ENABLED": "true",
        "OPENROUTER_REQUEST_TIMEOUT": "90",
        "OPENROUTER_MAX_RETRIES": "1",
        "OPENROUTER_MAX_PARALLEL": "3",
        "MEMORY_GATEWAY_MAX_BATCH_ITEMS": "100",
        "MEMORY_GATEWAY_MAX_DOCUMENT_CHARS": "2000000",
        "PROVIDER_RECALL_TIMEOUT": "8",
        "PROVIDER_RECALL_LIMIT": "6",
        "MEMORY_INTERACTIVE_RECALL_SCORE_FLOOR": "-4.5",
        "ANALYSIS_CHUNK_CHARS": "6000",
        "ANALYSIS_CHUNK_OVERLAP": "600",
        "ANALYSIS_MAX_CHUNKS": "128",
        "ANALYSIS_ASYNC_THRESHOLD": "6000",
        "MEMORY_ANALYSIS_RETRY_MAX_ATTEMPTS": "3",
        "MEMORY_ANALYSIS_RETRY_POLL_SECONDS": "15",
        "REVIEW_AUTO_SAVE_MIN_CONFIDENCE": "0.55",
        "MEMORY_RETRY_INTERVAL_SECONDS": "60",
        "MEMORY_RETRY_MAX_ATTEMPTS": "8",
        "MEMORY_PROVIDER_STALE_QUEUE_SECONDS": "120",
        "OLLAMA_WARMUP_TIMEOUT": "180",
        "MEMORY_GATEWAY_GPU_LIMIT": "90",
        "MEMORY_GATEWAY_GPU_GUARD_TIMEOUT": "12",
        "MEMORY_GATEWAY_GPU_GUARD_POLL_SECONDS": "0.25",
        "MEMORY_GATEWAY_MAX_REQUEST_BYTES": "32000000",
    }
    os.environ.update(settings)


def main() -> None:
    if sys.argv[1:] != ["--link-memory-profile=staging"]:
        raise SystemExit("The staging Gateway requires the staging profile marker.")
    block_project_env(ROOT / ".env")
    apply_staging_settings(ROOT)
    gateway_dir = ROOT / "gateway"
    sys.path.insert(0, str(gateway_dir))
    runpy.run_path(str(gateway_dir / "server.py"), run_name="__main__")


if __name__ == "__main__":
    main()
