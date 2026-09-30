"""Parse the conversation JSON shape found in ChatGPT data exports.

This is a local-file parser, not an account connector. Export schemas can
change; callers should preview parsed messages before importing them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
from typing import Any


def _plain_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            text = part.strip()
        elif isinstance(part, Mapping) and part.get("content_type", part.get("type", "text")) == "text":
            value = part.get("text", part.get("content"))
            text = value.strip() if isinstance(value, str) else ""
        else:
            # Ignore images, tool payloads, and unknown structured blocks.
            text = ""
        if text:
            parts.append(text)
    return "\n".join(parts)


def _conversation_list(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        nested = value.get("conversations")
        if isinstance(nested, list):
            candidates = nested
        elif isinstance(value.get("mapping"), Mapping):
            candidates = [value]
        else:
            raise ValueError("Expected an OpenAI conversation export with a conversations list or mapping object")
    elif isinstance(value, list):
        candidates = value
    else:
        raise ValueError("Expected a JSON object or array of conversations")
    conversations = [item for item in candidates if isinstance(item, Mapping) and isinstance(item.get("mapping"), Mapping)]
    if not conversations:
        raise ValueError("No conversations with a message mapping were found")
    return conversations


def _message_rows(conversation: Mapping[str, Any]) -> list[tuple[float, int, dict[str, str]]]:
    rows: list[tuple[float, int, dict[str, str]]] = []
    mapping = conversation["mapping"]
    assert isinstance(mapping, Mapping)
    positions = {node_id: index for index, node_id in enumerate(mapping)}
    ordered_nodes: list[tuple[int, Any]] = []
    current_node = conversation.get("current_node")
    selected_active_branch = isinstance(current_node, str) and current_node in mapping
    if selected_active_branch:
        # Follow only the active branch back to its root. Other mapping nodes
        # can be abandoned assistant alternatives and should not be imported.
        branch: list[tuple[int, Any]] = []
        seen: set[str] = set()
        node_id: str | None = current_node
        while node_id is not None and node_id in mapping and node_id not in seen:
            seen.add(node_id)
            node = mapping[node_id]
            branch.append((positions[node_id], node))
            parent = node.get("parent") if isinstance(node, Mapping) else None
            node_id = parent if isinstance(parent, str) else None
        ordered_nodes = list(reversed(branch))
    else:
        ordered_nodes = list(enumerate(mapping.values()))
    for index, node in ordered_nodes:
        if not isinstance(node, Mapping):
            continue
        message = node.get("message")
        if not isinstance(message, Mapping):
            continue
        author = message.get("author")
        role = author.get("role") if isinstance(author, Mapping) else None
        if not isinstance(role, str) or role not in {"user", "assistant"}:
            continue
        metadata = message.get("metadata")
        if isinstance(metadata, Mapping) and metadata.get("is_visually_hidden_from_conversation") is True:
            continue
        content = message.get("content")
        content_value = content.get("parts", content.get("text", "")) if isinstance(content, Mapping) else content
        text = _plain_text(content_value)
        if not text:
            continue
        try:
            created = float(message.get("create_time") or 0)
        except (TypeError, ValueError):
            created = 0
        rows.append((created, index, {"role": str(role), "content": text}))
    if not selected_active_branch:
        rows.sort(key=lambda row: (row[0], row[1]))
    return rows


def parse_openai_conversations(
    value: Any,
    *,
    max_messages: int = 1000,
    max_chars: int = 200_000,
) -> list[dict[str, Any]]:
    """Convert exported OpenAI conversation records into Gateway documents.

    Only user/assistant text is retained. Tool messages, non-text blocks,
    titles, account metadata, node IDs, timestamps, and local paths are omitted.
    """
    if max_messages < 0 or max_chars < 0:
        raise ValueError("message and character limits must be non-negative")
    documents: list[dict[str, Any]] = []
    for index, conversation in enumerate(_conversation_list(value)):
        messages: list[dict[str, str]] = []
        remaining = max_chars
        for _, _, message in _message_rows(conversation):
            if len(messages) >= max_messages or remaining <= 0:
                break
            text = message["content"][:remaining]
            if not text:
                continue
            messages.append({"role": message["role"], "content": text})
            remaining -= len(text)
        if not messages:
            continue
        raw_id = conversation.get("id")
        identifier = str(raw_id).strip() if isinstance(raw_id, (str, int)) else ""
        if identifier:
            # Keep a stable opaque identifier while preventing platform export
            # IDs from being transmitted to the selected Gateway.
            identifier = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:24]
        else:
            identifier = f"conversation-{index + 1}"
        documents.append({
            "source": "openai-conversation-export",
            "conversation_id": f"openai-export:{identifier}",
            "messages": messages,
        })
    return documents
