"""Optional Claude Code UserPromptSubmit hook for local Link Memory recall.

The script is intentionally not registered or installed automatically. It only
adds bounded local context and fails open when the Gateway is unavailable.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from codex_user_prompt_hook import MAX_STDIN_BYTES, _context_text, query_local_gateway as _query_local_gateway


CLAUDE_ENDPOINT = "/v1/hooks/claude/user-prompt-context"


def query_local_gateway(prompt: str) -> dict[str, Any]:
    """Query the local-only Claude hook route through the shared HTTP client."""
    return _query_local_gateway(prompt, endpoint=CLAUDE_ENDPOINT)


def process_hook_payload(payload: Any, gateway_call: Callable[[str], dict[str, Any]]) -> str:
    """Return plain-text additional context for Claude Code, or empty output."""
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "UserPromptSubmit":
        return ""
    prompt = payload.get("user_prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return ""
    try:
        response = gateway_call(prompt[:2000])
        return _context_text(response.get("context_packet")) if isinstance(response, dict) else ""
    except Exception:
        return ""


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
        payload = json.loads(raw.decode("utf-8")) if len(raw) <= MAX_STDIN_BYTES else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = None
    context = process_hook_payload(payload, query_local_gateway)
    if context:
        sys.stdout.write(context + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
