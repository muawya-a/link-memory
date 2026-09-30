"""Preview or import Claude Code local JSONL session transcripts.

Only text in user/assistant messages is imported. Tool inputs/outputs, local
absolute paths, session IDs, and other transcript metadata are excluded.
Source transcript files are read-only and are never moved or deleted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if not sys.path or sys.path[0] != str(ROOT):
    sys.path.insert(0, str(ROOT))

from gateway.outbound_http import urlopen_no_proxy_redirects  # noqa: E402

DEFAULT_GATEWAY = os.getenv("MEMORY_GATEWAY_URL", "http://127.0.0.1:18000").rstrip("/")
DEFAULT_CLAUDE_HOME = pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR", pathlib.Path.home() / ".claude"))


def text_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for block in value:
            if isinstance(block, dict) and block.get("type", "text") == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts).strip()
    return ""


def read_session(path: pathlib.Path, max_messages: int, max_chars: int) -> dict[str, Any] | None:
    messages: list[dict[str, str]] = []
    total_chars = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                role = record.get("type")
                if role not in {"user", "assistant"}:
                    continue
                message = record.get("message")
                if not isinstance(message, dict) or message.get("role", role) != role:
                    continue
                content = text_content(message.get("content"))
                if not content:
                    continue
                if len(messages) >= max_messages or total_chars >= max_chars:
                    break
                content = content[: max_chars - total_chars]
                if not content:
                    break
                messages.append({"role": role, "content": content})
                total_chars += len(content)
    except OSError:
        return None
    if not messages:
        return None
    session_key = hashlib.sha256(str(path).lower().encode("utf-8")).hexdigest()[:24]
    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    return {
        "source": "claude-code-history",
        "conversation_id": f"claude-code-session:{session_key}",
        "messages": messages,
        "occurred_at": modified,
        "metadata": {"capture": "claude_code_history_import", "message_count": len(messages)},
    }


def post(gateway: str, document: dict[str, Any], batch_id: str, discard_raw: bool) -> dict[str, Any]:
    payload = {"source": "claude-code-history", "batch_id": batch_id, "documents": [document], "delete_after_success": discard_raw}
    request = urllib.request.Request(
        gateway.rstrip("/") + "/v1/import",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen_no_proxy_redirects(request, timeout=900) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude-home", default=str(DEFAULT_CLAUDE_HOME), help="Claude Code config directory (default: CLAUDE_CONFIG_DIR or ~/.claude)")
    parser.add_argument("--file", action="append", help="Import only this transcript JSONL file; repeat to select several")
    parser.add_argument("--gateway", default=DEFAULT_GATEWAY)
    parser.add_argument("--limit", type=int, default=0, help="Maximum transcript files; 0 means all discovered files")
    parser.add_argument("--max-messages", type=int, default=1000)
    parser.add_argument("--max-chars", type=int, default=200000)
    parser.add_argument("--discard-raw-after-success", action="store_true", help="Delete the Gateway's temporary raw copy after extraction")
    parser.add_argument("--confirm-import", action="store_true", help="Confirm that the selected local conversations may be imported")
    args = parser.parse_args()

    if args.file:
        files = [pathlib.Path(name).expanduser().resolve() for name in args.file]
    else:
        root = pathlib.Path(args.claude_home).expanduser().resolve() / "projects"
        files = sorted(root.rglob("*.jsonl"), key=lambda item: item.stat().st_mtime) if root.is_dir() else []
    if args.limit > 0:
        files = files[: args.limit]
    documents = [(path, read_session(path, args.max_messages, args.max_chars)) for path in files]
    ready = [(path, doc) for path, doc in documents if doc]
    summary = {"transcript_files_found": len(files), "documents_ready": len(ready), "messages_ready": sum(len(doc["messages"]) for _, doc in ready), "characters_ready": sum(sum(len(msg["content"]) for msg in doc["messages"]) for _, doc in ready), "dry_run": not args.confirm_import}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.confirm_import:
        print("Nothing was sent. Review this preview, then rerun with --confirm-import to import these conversations.", file=sys.stderr)
        return 2

    failures = 0
    for index, (path, document) in enumerate(ready, start=1):
        try:
            safe_session_id = hashlib.sha256(str(path).lower().encode("utf-8")).hexdigest()[:16]
            result = post(args.gateway, document, f"claude-code-{safe_session_id}-{index}", args.discard_raw_after_success)
            print(json.dumps({"file": path.name, "status": result.get("status"), "processed": result.get("processed", 0), "failed": result.get("failed", 0)}, ensure_ascii=False))
            failures += int(result.get("failed", 0) or 0)
        except (OSError, ValueError) as exc:
            print(json.dumps({"file": path.name, "status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            failures += 1
    return 3 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
