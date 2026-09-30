from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
bridge = importlib.import_module("codex_notify_bridge")


class CodexNotifyBridgeTests(unittest.TestCase):
    def test_non_object_json_payload_is_ignored_without_dispatch_or_exception(self):
        for payload_json in ("null", "[]"):
            with self.subTest(payload=payload_json), tempfile.TemporaryDirectory(prefix="codex-notify-invalid-shape-") as directory:
                root = Path(directory)
                executable = root / "legacy-notify.exe"
                executable.write_bytes(b"synthetic placeholder")
                log_path = root / "data" / "codex-hook-events.jsonl"

                with (
                    patch.object(bridge, "LEGACY_NOTIFY", str(executable)),
                    patch.object(bridge, "DATA_DIR", log_path.parent),
                    patch.object(bridge, "LOG_PATH", log_path),
                    patch.object(bridge, "extract_turn_messages") as extract,
                    patch.object(bridge, "post_json") as post_json,
                    patch.object(bridge.subprocess, "Popen") as popen,
                    patch.object(sys, "argv", ["codex_notify_bridge.py", "turn-ended", payload_json]),
                ):
                    exit_code = bridge.main()

                event = json.loads(log_path.read_text(encoding="utf-8"))
                self.assertEqual(exit_code, 0)
                self.assertEqual(event["status"], "ignored")
                self.assertEqual(event["reason"], "invalid_hook_payload")
                extract.assert_not_called()
                post_json.assert_not_called()
                popen.assert_not_called()

    def test_malformed_turn_and_session_ids_fail_closed_before_any_dispatch(self):
        invalid_values = (
            ("json_null", None),
            ("numeric", 42),
            ("whitespace", " \t "),
            ("oversized", "x" * 257),
        )
        for field, reason in (("turn_id", "turn_id_invalid"), ("session_id", "session_id_invalid")):
            for value_name, invalid_value in invalid_values:
                with self.subTest(field=field, value=value_name), tempfile.TemporaryDirectory(prefix="codex-notify-invalid-id-") as directory:
                    root = Path(directory)
                    transcript = root / "synthetic.jsonl"
                    transcript.write_text("{}\n", encoding="utf-8")
                    executable = root / "legacy-notify.exe"
                    executable.write_bytes(b"synthetic placeholder")
                    log_path = root / "data" / "codex-hook-events.jsonl"
                    payload_value = {
                        "hook_event_name": "turn-ended",
                        "turn_id": "synthetic-turn",
                        "session_id": "synthetic-session",
                        "transcript_path": str(transcript),
                    }
                    payload_value[field] = invalid_value
                    payload = json.dumps(payload_value)

                    with (
                        patch.object(bridge, "LEGACY_NOTIFY", str(executable)),
                        patch.object(bridge, "DATA_DIR", log_path.parent),
                        patch.object(bridge, "LOG_PATH", log_path),
                        patch.object(bridge, "extract_turn_messages", return_value=[{"role": "user", "content": "synthetic"}]) as extract,
                        patch.object(bridge, "post_json") as post_json,
                        patch.object(bridge.subprocess, "Popen") as popen,
                        patch.object(sys, "argv", ["codex_notify_bridge.py", "turn-ended", payload]),
                    ):
                        exit_code = bridge.main()

                    event = json.loads(log_path.read_text(encoding="utf-8"))
                    self.assertEqual(exit_code, 0)
                    self.assertEqual(event["status"], "skipped")
                    self.assertEqual(event["reason"], reason)
                    self.assertNotIn("turn_id", event)
                    self.assertNotIn("session_id", event)
                    extract.assert_not_called()
                    post_json.assert_not_called()
                    popen.assert_not_called()

    def test_missing_session_id_fails_closed_without_using_transcript_stem(self):
        with tempfile.TemporaryDirectory(prefix="codex-notify-missing-session-") as directory:
            root = Path(directory)
            transcript = root / "private-path-stem-sentinel.jsonl"
            records = [{"payload": {
                "type": "message",
                "role": "user",
                "content": "synthetic question",
                "internal_chat_message_metadata_passthrough": {"turn_id": "synthetic-turn"},
            }}]
            transcript.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
            executable = root / "legacy-notify.exe"
            executable.write_bytes(b"synthetic placeholder")
            log_path = root / "data" / "codex-hook-events.jsonl"
            payload = json.dumps({
                "hook_event_name": "turn-ended",
                "turn_id": "synthetic-turn",
                "transcript_path": str(transcript),
            })

            with (
                patch.object(bridge, "LEGACY_NOTIFY", str(executable)),
                patch.object(bridge, "DATA_DIR", log_path.parent),
                patch.object(bridge, "LOG_PATH", log_path),
                patch.object(bridge, "post_json") as post_json,
                patch.object(bridge.subprocess, "Popen") as popen,
                patch.object(sys, "argv", ["codex_notify_bridge.py", "turn-ended", payload]),
            ):
                exit_code = bridge.main()

            logged_text = log_path.read_text(encoding="utf-8")
            event = json.loads(logged_text)
            self.assertEqual(exit_code, 0)
            self.assertEqual(event["status"], "skipped")
            self.assertEqual(event["reason"], "session_id_missing")
            self.assertNotIn("private-path-stem-sentinel", logged_text)
            post_json.assert_not_called()
            popen.assert_not_called()

    def test_unsupported_event_does_not_invoke_legacy_notify_child(self):
        with tempfile.TemporaryDirectory(prefix="codex-notify-child-invalid-event-") as directory:
            root = Path(directory)
            executable = root / "legacy-notify.exe"
            executable.write_bytes(b"synthetic placeholder")
            log_path = root / "data" / "codex-hook-events.jsonl"
            payload = json.dumps({"hook_event_name": "synthetic-private-event"})

            with (
                patch.object(bridge, "LEGACY_NOTIFY", str(executable)),
                patch.object(bridge, "DATA_DIR", log_path.parent),
                patch.object(bridge, "LOG_PATH", log_path),
                patch.object(bridge.subprocess, "Popen") as popen,
                patch.object(sys, "argv", ["codex_notify_bridge.py", "unknown", payload]),
            ):
                exit_code = bridge.main()

            self.assertEqual(exit_code, 0)
            popen.assert_not_called()

    def test_legacy_notify_receives_only_allowlisted_turn_fields(self):
        with tempfile.TemporaryDirectory(prefix="codex-notify-child-payload-") as directory:
            root = Path(directory)
            executable = root / "legacy-notify.exe"
            executable.write_bytes(b"synthetic placeholder")
            transcript = root / "private-transcript-path-sentinel.jsonl"
            records = [
                {"payload": {
                    "type": "message",
                    "role": "user",
                    "content": "synthetic question",
                    "internal_chat_message_metadata_passthrough": {"turn_id": "synthetic-turn"},
                }},
                {"payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": "synthetic answer",
                    "internal_chat_message_metadata_passthrough": {"turn_id": "synthetic-turn"},
                }},
            ]
            transcript.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
            normalized_session_id = "s" * 256
            payload = json.dumps({
                "hook_event_name": "turn-ended",
                "turn_id": " synthetic-turn ",
                "session_id": f" {normalized_session_id} ",
                "model": "private-model-sentinel",
                "transcript_path": str(transcript),
                "private_extra": "private-payload-sentinel",
            })
            log_path = root / "data" / "codex-hook-events.jsonl"
            submitted: list[tuple[str, dict[str, object]]] = []

            with (
                patch.object(bridge, "LEGACY_NOTIFY", str(executable)),
                patch.object(bridge, "DATA_DIR", log_path.parent),
                patch.object(bridge, "LOG_PATH", log_path),
                patch.object(bridge, "post_json", side_effect=lambda path, body: submitted.append((path, body)) or {"status": "queued"}),
                patch.object(bridge.subprocess, "Popen") as popen,
                patch.object(sys, "argv", ["codex_notify_bridge.py", "turn-ended", payload]),
            ):
                exit_code = bridge.main()

            self.assertEqual(exit_code, 0)
            popen.assert_called_once()
            self.assertEqual(len(submitted), 1)
            endpoint, gateway_payload = submitted[0]
            self.assertEqual(endpoint, "/v1/ingest")
            self.assertEqual(gateway_payload["conversation_id"], f"codex:{normalized_session_id}:synthetic-turn")
            self.assertEqual(gateway_payload["metadata"]["session_id"], normalized_session_id)
            self.assertEqual(gateway_payload["metadata"]["turn_id"], "synthetic-turn")
            child_args = popen.call_args.args[0]
            child_payload = json.loads(child_args[2])
            self.assertEqual(child_args[1], "turn-ended")
            self.assertEqual(child_payload, {
                "hook_event_name": "turn-ended",
                "turn_id": "synthetic-turn",
                "session_id": normalized_session_id,
            })
            serialized_child_payload = json.dumps(child_payload)
            self.assertNotIn("private-transcript-path-sentinel", serialized_child_payload)
            self.assertNotIn("private-model-sentinel", serialized_child_payload)
            self.assertNotIn("private-payload-sentinel", serialized_child_payload)

    def test_unsupported_event_name_is_not_written_to_event_log(self):
        with tempfile.TemporaryDirectory(prefix="codex-notify-event-redaction-") as directory:
            root = Path(directory)
            log_path = root / "data" / "codex-hook-events.jsonl"
            event_sentinel = "private-event-name-sentinel"
            payload = json.dumps({"hook_event_name": event_sentinel})

            with (
                patch.object(bridge, "DATA_DIR", log_path.parent),
                patch.object(bridge, "LOG_PATH", log_path),
                patch.object(sys, "argv", ["codex_notify_bridge.py", "unknown", payload]),
            ):
                exit_code = bridge.main()

            logged_text = log_path.read_text(encoding="utf-8")
            event = json.loads(logged_text)

            self.assertEqual(exit_code, 0)
            self.assertEqual(event["status"], "ignored")
            self.assertEqual(event["reason"], "unsupported_event")
            self.assertNotIn(event_sentinel, logged_text)

    def test_gateway_capture_metadata_omits_local_transcript_path(self):
        with tempfile.TemporaryDirectory(prefix="codex-notify-path-redaction-") as directory:
            root = Path(directory)
            transcript = root / "private-local-path-sentinel.jsonl"
            records = [
                {"payload": {
                    "type": "message",
                    "role": "user",
                    "content": "synthetic question",
                    "internal_chat_message_metadata_passthrough": {"turn_id": "synthetic-turn"},
                }},
                {"payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": "synthetic answer",
                    "internal_chat_message_metadata_passthrough": {"turn_id": "synthetic-turn"},
                }},
            ]
            transcript.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
            submitted: list[tuple[str, dict[str, object]]] = []
            payload = json.dumps({
                "hook_event_name": "turn-ended",
                "turn_id": "synthetic-turn",
                "session_id": "synthetic-session",
                "transcript_path": str(transcript),
                "model": "synthetic-model",
            })

            with (
                patch.object(bridge, "post_json", side_effect=lambda path, body: submitted.append((path, body)) or {"status": "queued"}),
                patch.object(sys, "argv", ["codex_notify_bridge.py", "turn-ended", payload]),
            ):
                exit_code = bridge.main()

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(submitted), 1)
            endpoint, request_body = submitted[0]
            metadata = request_body["metadata"]
            self.assertEqual(endpoint, "/v1/ingest")
            self.assertEqual(request_body["source"], "codex")
            self.assertEqual(request_body["conversation_id"], "codex:synthetic-session:synthetic-turn")
            self.assertEqual(metadata["turn_id"], "synthetic-turn")
            self.assertEqual(metadata["session_id"], "synthetic-session")
            self.assertNotIn("transcript_path", metadata)
            self.assertNotIn("private-local-path-sentinel", json.dumps(request_body))

    def test_gateway_error_log_keeps_status_but_redacts_exception_details(self):
        with tempfile.TemporaryDirectory(prefix="codex-notify-redaction-") as directory:
            root = Path(directory)
            transcript = root / "synthetic-session.jsonl"
            records = [
                {"payload": {
                    "type": "message",
                    "role": "user",
                    "content": "synthetic question",
                    "internal_chat_message_metadata_passthrough": {"turn_id": "synthetic-turn"},
                }},
                {"payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": "synthetic answer",
                    "internal_chat_message_metadata_passthrough": {"turn_id": "synthetic-turn"},
                }},
            ]
            transcript.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
            log_path = root / "data" / "codex-hook-events.jsonl"
            private_detail = "https://private.example/private-path?token=synthetic-secret"
            payload = json.dumps({
                "hook_event_name": "turn-ended",
                "turn_id": "synthetic-turn",
                "session_id": "synthetic-session",
                "transcript_path": str(transcript),
            })

            with (
                patch.object(bridge, "DATA_DIR", log_path.parent),
                patch.object(bridge, "LOG_PATH", log_path),
                patch.object(bridge, "post_json", side_effect=URLError(private_detail)),
                patch.object(sys, "argv", ["codex_notify_bridge.py", "turn-ended", payload]),
            ):
                exit_code = bridge.main()

            logged_text = log_path.read_text(encoding="utf-8")
            event = json.loads(logged_text)

            self.assertEqual(exit_code, 0)
            self.assertEqual(event["status"], "failed")
            self.assertEqual(event["reason"], "gateway_unreachable")
            self.assertNotIn("private.example", logged_text)
            self.assertNotIn("private-path", logged_text)
            self.assertNotIn("synthetic-secret", logged_text)
            self.assertEqual(event["error_type"], "URLError")
            self.assertNotIn("error", event)


if __name__ == "__main__":
    unittest.main()
