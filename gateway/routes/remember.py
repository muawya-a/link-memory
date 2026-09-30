"""HTTP handler for manually remembering a memory item."""

from __future__ import annotations

from http import HTTPStatus


def handle_remember(handler, services, payload: dict) -> None:
    """Save, fan out, and archive one remember request.

    Authentication, request-body parsing, and shared exception mapping stay in
    the HTTP dispatcher so every POST route retains the same outer contract.
    """
    source = str(payload.get("source", "manual"))
    if not services.hook_capture_allowed(source):
        raise ValueError("capture is disabled for this source")
    item = services.save_memory(payload, source, payload.get("conversation_id"), payload.get("occurred_at"))
    services.enqueue_memory_fanout(item, source, payload.get("conversation_id"), payload.get("occurred_at"))
    archive_result = services.write_portable_archive()
    handler.send_json({"status": "saved", "memory": item, "fanout": "queued", "archive": archive_result}, HTTPStatus.CREATED)
