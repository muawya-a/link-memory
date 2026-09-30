import json
from pathlib import Path

from scripts.codex_history_import import session_document


def test_codex_import_retains_only_minimal_import_metadata(tmp_path: Path) -> None:
    session = tmp_path / "private-session-name.jsonl"
    session.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": "Remember the deployment window.",
                            "internal_chat_message_metadata_passthrough": {"turn_id": "private-turn-1"},
                        }
                    }
                ),
                json.dumps(
                    {
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": "I will remember it.",
                            "internal_chat_message_metadata_passthrough": {"turn_id": "private-turn-2"},
                        }
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    document = session_document(session, max_messages=None, max_chars=None)

    assert document is not None
    assert document["metadata"] == {
        "capture": "codex_history_import",
        "message_count": 2,
    }
    assert document["messages"] == [
        {"role": "user", "content": "Remember the deployment window."},
        {"role": "assistant", "content": "I will remember it."},
    ]
    serialized = json.dumps(document)
    assert "private-turn-" not in serialized
    assert "private-session-name" not in serialized
    assert str(tmp_path) not in serialized
