"""Parse local Claude Code JSONL transcript files without retaining tool data."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def _text_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for block in value:
        if isinstance(block, Mapping) and block.get("type", "text") == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts)


def parse_claude_code_jsonl(
    raw: str,
    conversation_id: str,
    *,
    max_messages: int = 1000,
    max_chars: int = 200_000,
) -> dict[str, Any] | None:
    """Extract bounded user/assistant message text from a transcript string."""
    if max_messages < 0 or max_chars < 0:
        raise ValueError("message and character limits must be non-negative")
    messages: list[dict[str, str]] = []
    remaining = max_chars
    for line in raw.splitlines():
        if len(messages) >= max_messages or remaining <= 0:
            break
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(record, Mapping):
            continue
        role = record.get("type")
        message = record.get("message")
        if not isinstance(role, str) or role not in {"user", "assistant"} or not isinstance(message, Mapping):
            continue
        if message.get("role", role) != role:
            continue
        text = _text_content(message.get("content"))[:remaining]
        if not text:
            continue
        messages.append({"role": str(role), "content": text})
        remaining -= len(text)
    if not messages:
        return None
    return {
        "source": "claude-code-history",
        "conversation_id": f"claude-code-session:{conversation_id}",
        "messages": messages,
    }
