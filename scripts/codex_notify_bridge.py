"""Capture completed Codex turns and forward them to the local Memory Gateway."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if not sys.path or sys.path[0] != str(ROOT):
    sys.path.insert(0, str(ROOT))

from gateway.outbound_http import urlopen_no_proxy_redirects  # noqa: E402

DATA_DIR = ROOT / "data"
LOG_PATH = DATA_DIR / "codex-hook-events.jsonl"
def local_setting(name: str, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
            entry = line.strip()
            if entry and not entry.startswith("#") and "=" in entry:
                key, candidate = entry.split("=", 1)
                if key.strip() == name:
                    return candidate.strip()
    except OSError:
        pass
    return default


GATEWAY_URL = local_setting("MEMORY_GATEWAY_URL", "http://127.0.0.1:18000").rstrip("/")
API_KEY = local_setting("MEMORY_GATEWAY_API_KEY")
DISCARD_RAW_AFTER_SUCCESS = local_setting("MEMORY_GATEWAY_DISCARD_RAW_AFTER_SUCCESS", "false").lower() in {"1", "true", "yes"}
LEGACY_NOTIFY = os.getenv(
    "CODEX_LEGACY_NOTIFY",
    "",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validated_identifier(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 256:
        return None
    return normalized


def log_event(event: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": now_iso(), **event}, ensure_ascii=False) + "\n")


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, dict) and isinstance(item.get("content"), str):
                parts.append(item["content"])
        return "\n".join(parts).strip()
    if isinstance(content, dict):
        return content_text(content.get("text", content.get("content", "")))
    return str(content or "").strip()


def extract_turn_messages(transcript_path: Path, turn_id: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    with transcript_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = record.get("payload", {})
            if not isinstance(payload, dict) or payload.get("type") != "message":
                continue
            passthrough = payload.get("internal_chat_message_metadata_passthrough", {})
            if not isinstance(passthrough, dict) or str(passthrough.get("turn_id", "")) != turn_id:
                continue
            role = str(payload.get("role", ""))
            if role not in {"user", "assistant"}:
                continue
            text = content_text(payload.get("content"))
            if not text:
                continue
            key = (role, text)
            if key not in seen:
                seen.add(key)
                messages.append({"role": role, "content": text})
    return messages


def post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    request = urllib.request.Request(f"{GATEWAY_URL}{path}", data=body, headers=headers, method="POST")
    # Ollama may need to load the local model on the first turn. The notify
    # hook is fire-and-forget, so waiting here does not block Codex itself.
    with urlopen_no_proxy_redirects(request, timeout=120) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def forward_legacy_notify(event_name: str, payload: dict[str, Any]) -> None:
    if not LEGACY_NOTIFY or not Path(LEGACY_NOTIFY).exists():
        return
    child_payload: dict[str, str] = {"hook_event_name": event_name}
    for key in ("turn_id", "session_id"):
        value = payload.get(key)
        if isinstance(value, str) and value and len(value) <= 256:
            child_payload[key] = value
    try:
        subprocess.Popen(
            [LEGACY_NOTIFY, event_name, json.dumps(child_payload, separators=(",", ":"))],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        pass


def main() -> int:
    hook_args = sys.argv[1:]
    if not hook_args:
        return 0
    payload_json = hook_args[-1]
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        log_event({"status": "ignored", "reason": "invalid_hook_payload"})
        return 0
    if not isinstance(payload, dict):
        log_event({"status": "ignored", "reason": "invalid_hook_payload"})
        return 0

    event_name = str(payload.get("hook_event_name", hook_args[0] if hook_args else ""))
    if event_name not in {"turn-ended", "turn_ended"}:
        log_event({"status": "ignored", "reason": "unsupported_event"})
        return 0

    turn_id = validated_identifier(payload, "turn_id")
    if turn_id is None:
        reason = "turn_id_missing" if "turn_id" not in payload else "turn_id_invalid"
        log_event({"status": "skipped", "reason": reason})
        return 0
    session_id = validated_identifier(payload, "session_id")
    if session_id is None:
        reason = "session_id_missing" if "session_id" not in payload else "session_id_invalid"
        log_event({"status": "skipped", "reason": reason})
        return 0
    forward_legacy_notify(event_name, {"turn_id": turn_id, "session_id": session_id})

    transcript_value = payload.get("transcript_path")
    transcript_path = Path(str(transcript_value)) if transcript_value else None
    if not transcript_path or not transcript_path.exists():
        log_event({"status": "skipped", "reason": "transcript_missing", "turn_id": turn_id, "session_id": session_id})
        return 0

    messages: list[dict[str, str]] = []
    for _ in range(3):
        messages = extract_turn_messages(transcript_path, turn_id)
        if messages:
            break
        time.sleep(0.25)
    if not messages:
        log_event({"status": "skipped", "reason": "no_turn_messages", "turn_id": turn_id, "session_id": session_id})
        return 0

    request_payload = {
        "source": "codex",
        "conversation_id": f"codex:{session_id}:{turn_id}",
        "messages": messages,
        "delete_after_success": DISCARD_RAW_AFTER_SUCCESS,
        "metadata": {
            "capture": "codex_turn_ended_hook",
            "session_id": session_id,
            "turn_id": turn_id,
            "model": payload.get("model"),
        },
    }
    try:
        result = post_json("/v1/ingest", request_payload)
        log_event({
            "status": "submitted",
            "turn_id": turn_id,
            "session_id": session_id,
            "messages": len(messages),
            "characters": sum(len(item["content"]) for item in messages),
            "gateway": {key: result.get(key) for key in ("status", "job_id", "saved_count", "deleted_after_success") if key in result},
        })
    except (OSError, ValueError, urllib.error.URLError) as exc:
        log_event({"status": "failed", "reason": "gateway_unreachable", "turn_id": turn_id, "session_id": session_id, "error_type": type(exc).__name__})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
