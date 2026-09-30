"""Import one complete conversation-export file as one Gateway batch.

Supported input: a JSON object with ``documents``/``conversations``/``items``,
a JSON array, JSONL, or a plain Markdown/text file. The file is sent as one
batch so the Gateway can process conversations internally without shipping the
whole corpus on every recall request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
if not sys.path or sys.path[0] != str(ROOT):
    sys.path.insert(0, str(ROOT))

from gateway.outbound_http import urlopen_no_proxy_redirects  # noqa: E402
from scripts.importers.claude_code import parse_claude_code_jsonl  # noqa: E402
from scripts.importers.openai_export import parse_openai_conversations  # noqa: E402


def post(url: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url.rstrip("/") + "/v1/import", data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen_no_proxy_redirects(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def load_documents(path: pathlib.Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    try:
        value = json.loads(text)
        if _looks_like_openai_export(value):
            return parse_openai_conversations(value)
        if isinstance(value, dict) and _looks_like_claude_code_transcript([value]):
            stable_id = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
            document = parse_claude_code_jsonl(text, stable_id)
            return [document] if document else []
        if isinstance(value, dict):
            for key in ("documents", "conversations", "items"):
                if isinstance(value.get(key), list):
                    return [item if isinstance(item, dict) else {"text": str(item)} for item in value[key]]
            return [value]
        if isinstance(value, list):
            return [item if isinstance(item, dict) else {"text": str(item)} for item in value]
    except json.JSONDecodeError:
        pass
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        parsed = []
        for line in lines:
            try:
                item = json.loads(line)
                parsed.append(item if isinstance(item, dict) else {"text": str(item)})
            except json.JSONDecodeError:
                parsed = []
                break
        if parsed:
            if _looks_like_claude_code_transcript(parsed):
                stable_id = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
                document = parse_claude_code_jsonl(text, stable_id)
                return [document] if document else []
            return parsed
    stable_id = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
    return [{"conversation_id": f"text-file:{stable_id}", "text": text}]


def _looks_like_openai_export(value: object) -> bool:
    if isinstance(value, dict):
        if isinstance(value.get("mapping"), dict):
            return True
        conversations = value.get("conversations")
        return isinstance(conversations, list) and any(
            isinstance(item, dict) and isinstance(item.get("mapping"), dict) for item in conversations
        )
    return isinstance(value, list) and any(
        isinstance(item, dict) and isinstance(item.get("mapping"), dict) for item in value
    )


def _looks_like_claude_code_transcript(rows: list[dict]) -> bool:
    return any(
        row.get("type") in {"user", "assistant"} and isinstance(row.get("message"), dict)
        for row in rows
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--source", default="conversation-export")
    parser.add_argument("--gateway", default="http://127.0.0.1:18000")
    parser.add_argument("--discard-raw-after-success", action="store_true", help="Delete the Gateway's temporary raw copy after extraction")
    parser.add_argument("--confirm-import", action="store_true", help="Confirm that this file may be sent to the configured Gateway")
    args = parser.parse_args()
    path = pathlib.Path(args.path).resolve()
    documents = load_documents(path)
    stable_id = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
    if not args.confirm_import:
        print(json.dumps({"source_file": path.name, "documents_ready": len(documents), "characters_ready": sum(len(json.dumps(doc, ensure_ascii=False)) for doc in documents), "dry_run": True}, ensure_ascii=False, indent=2))
        print("Nothing was sent. Review the summary, then rerun with --confirm-import to import this file.", file=sys.stderr)
        raise SystemExit(2)
    payload = {"source": args.source, "batch_id": f"file-import-{stable_id}", "documents": documents, "delete_after_success": args.discard_raw_after_success}
    print(json.dumps(post(args.gateway, payload), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
