"""Import historical Codex session files into the local Memory Gateway.

Each JSONL session is sent as one Gateway batch document.  The Gateway then
chunks and analyses the conversation internally, so recall never ships the
whole session back to a model.  Imports are idempotent by source/session id:
rerunning this command does not reprocess an unchanged file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


DEFAULT_CODEX_HOME = pathlib.Path(os.environ.get("CODEX_HOME", pathlib.Path.home() / ".codex"))
ROOT = pathlib.Path(__file__).resolve().parents[1]
if not sys.path or sys.path[0] != str(ROOT):
    sys.path.insert(0, str(ROOT))

from gateway.outbound_http import urlopen_no_proxy_redirects  # noqa: E402

DEFAULT_GATEWAY = os.getenv("MEMORY_GATEWAY_URL", "http://127.0.0.1:18000").rstrip("/")


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text", item.get("content"))
                if isinstance(value, str):
                    parts.append(value)
        return "\n".join(parts).strip()
    if isinstance(content, dict):
        return content_text(content.get("text", content.get("content", "")))
    return str(content or "").strip()


def iter_messages(path: pathlib.Path, max_messages: int | None = None, max_chars: int | None = None) -> Iterable[dict[str, str]]:
    """Yield only user/assistant messages from a Codex JSONL session."""

    seen: set[tuple[str, str, str]] = set()
    total_chars = 0
    yielded = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "message":
                continue
            role = str(payload.get("role", ""))
            if role not in {"user", "assistant"}:
                continue
            text = content_text(payload.get("content"))
            if not text:
                continue
            passthrough = payload.get("internal_chat_message_metadata_passthrough")
            turn_id = str(passthrough.get("turn_id", "")) if isinstance(passthrough, dict) else ""
            key = (turn_id, role, text)
            if key in seen:
                continue
            if max_messages is not None and yielded >= max_messages:
                return
            if max_chars is not None and total_chars >= max_chars:
                return
            if max_chars is not None and total_chars + len(text) > max_chars:
                text = text[: max_chars - total_chars].rstrip()
            if not text:
                return
            seen.add(key)
            yielded += 1
            total_chars += len(text)
            yield {"role": role, "content": text, "turn_id": turn_id}


def session_document(path: pathlib.Path, max_messages: int | None, max_chars: int | None) -> dict[str, Any] | None:
    messages = list(iter_messages(path, max_messages=max_messages, max_chars=max_chars))
    if not messages:
        return None
    session_key = hashlib.sha256(str(path).lower().encode("utf-8")).hexdigest()[:32]
    stat = path.stat()
    return {
        "source": "codex-history",
        "conversation_id": f"codex-session:{session_key}",
        "messages": [{"role": item["role"], "content": item["content"]} for item in messages],
        "occurred_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "metadata": {
            "capture": "codex_history_import",
            "message_count": len(messages),
        },
    }


def post_batch(gateway: str, documents: list[dict[str, Any]], batch_id: str, keep_raw: bool) -> dict[str, Any]:
    payload = {
        "source": "codex-history",
        "batch_id": batch_id,
        "documents": documents,
        "delete_after_success": not keep_raw,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        gateway.rstrip("/") + "/v1/import",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen_no_proxy_redirects(request, timeout=900) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def split_batches(documents: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Send one complete session per request so a slow session cannot block all history."""

    return [[document] for document in documents]


def discover_sessions(root: pathlib.Path, since_days: float | None, include_active: bool) -> list[pathlib.Path]:
    sessions_root = root / "sessions"
    if not sessions_root.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days) if since_days is not None else None
    files: list[pathlib.Path] = []
    for path in sessions_root.rglob("*.jsonl"):
        stat = path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        if cutoff and modified < cutoff:
            continue
        if not include_active and (datetime.now(timezone.utc) - modified).total_seconds() < 300:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.stat().st_mtime)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", default=str(DEFAULT_CODEX_HOME))
    parser.add_argument("--gateway", default=DEFAULT_GATEWAY)
    parser.add_argument("--since-days", type=float, default=None, help="Only sessions modified within this many days")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of session files; 0 means all")
    parser.add_argument("--max-messages", type=int, default=None, help="Bound each session document")
    parser.add_argument("--max-chars", type=int, default=None, help="Bound each session document")
    parser.add_argument("--include-active", action="store_true", help="Include a session modified in the last five minutes")
    parser.add_argument("--discard-raw-after-success", action="store_true", help="Delete the Gateway's temporary raw copy after extraction; source files are never changed")
    parser.add_argument("--confirm-import", action="store_true", help="Confirm that the selected conversation history may be imported into this Gateway")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    files = discover_sessions(pathlib.Path(args.codex_home).expanduser().resolve(), args.since_days, args.include_active)
    if args.limit > 0:
        files = files[: args.limit]
    documents: list[dict[str, Any]] = []
    skipped = 0
    for path in files:
        document = session_document(path, args.max_messages, args.max_chars)
        if document is None:
            skipped += 1
            continue
        documents.append(document)

    summary = {
        "codex_home": str(pathlib.Path(args.codex_home).expanduser().resolve()),
        "sessions_found": len(files),
        "documents_ready": len(documents),
        "skipped_empty": skipped,
        "messages_ready": sum(len(item["messages"]) for item in documents),
        "characters_ready": sum(sum(len(msg["content"]) for msg in item["messages"]) for item in documents),
        "dry_run": args.dry_run,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.dry_run or not documents:
        return 0
    if not args.confirm_import:
        print("Import stopped: review the dry-run summary, then rerun with --confirm-import to send these conversations to the configured Gateway.", file=sys.stderr)
        return 2

    # Each session remains one document.  Only the HTTP envelope is split when
    # needed; stable conversation IDs make retries safe and idempotent.
    batch_prefix = f"codex-history-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    results = []
    batches = split_batches(documents)
    for index, batch in enumerate(batches, start=1):
        try:
            result = post_batch(args.gateway, batch, f"{batch_prefix}-{index}", not args.discard_raw_after_success)
            results.append(result)
            print(
                json.dumps({"batch": index, "of": len(batches), "status": result.get("status"), "processed": result.get("processed", 0), "duplicates": result.get("duplicates", 0), "failed": result.get("failed", 0)}, ensure_ascii=False),
                flush=True,
            )
        except (OSError, ValueError, urllib.error.URLError) as exc:
            results.append({"status": "failed", "failed": 1, "conflicts": 0, "total": 1, "error": str(exc)})
            print(json.dumps({"batch": index, "of": len(batches), "status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
    aggregate = {
        "batches": len(results),
        "total": sum(int(item.get("total", 0)) for item in results),
        "processed": sum(int(item.get("processed", 0)) for item in results),
        "duplicates": sum(int(item.get("duplicates", 0)) for item in results),
        "conflicts": sum(int(item.get("conflicts", 0)) for item in results),
        "failed": sum(int(item.get("failed", 0)) for item in results),
    }
    print(json.dumps({"status": "submitted", "batch_prefix": batch_prefix, "gateway": aggregate, **summary}, ensure_ascii=False, indent=2))
    return 0 if aggregate["failed"] == 0 and aggregate["conflicts"] == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
