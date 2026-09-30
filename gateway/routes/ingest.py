"""HTTP handler for ingesting a payload through the configured services."""

from __future__ import annotations

from http import HTTPStatus


def handle_ingest(handler, services, payload: dict) -> None:
    """Dispatch the original payload and return the accepted service result.

    Authentication, request-body parsing, and shared exception mapping stay in
    the HTTP dispatcher so every POST route retains the same outer contract.
    """
    handler.send_json(services.ingest(payload), HTTPStatus.ACCEPTED)
