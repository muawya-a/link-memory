from __future__ import annotations

import json
import importlib
import sys
from pathlib import Path
from unittest.mock import patch

from scripts.importers.claude_code import parse_claude_code_jsonl
from scripts.importers.openai_export import parse_openai_conversations


TESTS = Path(__file__).resolve().parents[1]
FIXTURES = TESTS / "fixtures" / "imports"
import_file = importlib.import_module("scripts.import_file")


def test_openai_conversations_export_extracts_only_user_and_assistant_text():
    payload = json.loads((FIXTURES / "openai_conversations_export.json").read_text(encoding="utf-8"))

    documents = parse_openai_conversations(payload)

    assert len(documents) == 1
    assert [message["role"] for message in documents[0]["messages"]] == ["user", "assistant"]
    assert "synthetic data" in documents[0]["messages"][0]["content"]
    assert "Never import tool output" not in json.dumps(documents)
    assert "mapping" not in documents[0]
    assert "metadata" not in documents[0]
    assert payload[0]["id"] not in json.dumps(documents)


def test_openai_export_uses_only_the_selected_branch_in_message_order():
    payload = [{
        "id": "branching",
        "current_node": "a1",
        "mapping": {
            "u": {"parent": None, "message": {"author": {"role": "user"}, "create_time": 2, "content": {"parts": ["question"]}}},
            "a1": {"parent": "u", "message": {"author": {"role": "assistant"}, "create_time": 3, "content": {"parts": ["first answer"]}}},
            "a2": {"parent": "u", "message": {"author": {"role": "assistant"}, "create_time": 4, "content": {"parts": ["alternate answer"]}}},
        },
    }]

    documents = parse_openai_conversations(payload)

    assert [message["content"] for message in documents[0]["messages"]] == ["question", "first answer"]


def test_claude_code_jsonl_keeps_text_blocks_and_drops_tools_and_file_paths():
    raw = (FIXTURES / "claude_code_session.jsonl").read_text(encoding="utf-8")

    document = parse_claude_code_jsonl(raw, conversation_id="fixture-session")

    assert document is not None
    assert [message["role"] for message in document["messages"]] == ["user", "assistant"]
    assert "I will remember it." in document["messages"][1]["content"]
    assert "private/example.txt" not in json.dumps(document)
    assert "Do not import tool output" not in json.dumps(document)


def test_parsers_bound_message_and_character_counts():
    payload = [{"id": "bounded", "mapping": {
        "u": {"message": {"author": {"role": "user"}, "content": {"parts": ["one"]}}},
        "a": {"message": {"author": {"role": "assistant"}, "content": {"parts": ["two"]}}},
    }}]

    doc = parse_openai_conversations(payload, max_messages=1, max_chars=3)[0]

    assert doc["messages"] == [{"role": "user", "content": "one"}]
    assert parse_claude_code_jsonl('{"type":"user","message":{"content":"abcdef"}}', "bounded", max_chars=3)["messages"][0]["content"] == "abc"


def test_generic_import_entrypoint_detects_openai_json_export(tmp_path):
    source = tmp_path / "conversations.json"
    source.write_bytes((FIXTURES / "openai_conversations_export.json").read_bytes())

    documents = import_file.load_documents(source)

    assert documents[0]["source"] == "openai-conversation-export"
    assert len(documents[0]["messages"]) == 2


def test_generic_import_entrypoint_detects_single_line_claude_jsonl(tmp_path):
    source = tmp_path / "one-message.jsonl"
    source.write_text('{"type":"user","message":{"role":"user","content":"one local line"}}\n', encoding="utf-8")

    documents = import_file.load_documents(source)

    assert documents[0]["source"] == "claude-code-history"
    assert documents[0]["messages"] == [{"role": "user", "content": "one local line"}]


def test_generic_import_entrypoint_detects_claude_jsonl_and_requires_confirmation(tmp_path):
    source = tmp_path / "session.jsonl"
    source.write_bytes((FIXTURES / "claude_code_session.jsonl").read_bytes())
    args = ["import_file.py", str(source)]

    with patch.object(sys, "argv", args), patch.object(import_file, "post") as post:
        try:
            import_file.main()
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("dry-run should request explicit confirmation")
        post.assert_not_called()

    with patch.object(sys, "argv", [*args, "--confirm-import"]), patch.object(import_file, "post", return_value={"status": "ok"}) as post:
        import_file.main()
        payload = post.call_args.args[1]
        assert payload["source"] == "conversation-export"
        assert len(payload["documents"]) == 1
        assert payload["documents"][0]["source"] == "claude-code-history"
        assert "private/example.txt" not in json.dumps(payload)
