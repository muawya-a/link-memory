"""Poll data/inbox for complete Codex/Claude/Gemini export files."""

from __future__ import annotations

import json
import os
import pathlib
import argparse
import hashlib
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
if not sys.path or sys.path[0] != str(ROOT):
    sys.path.insert(0, str(ROOT))

from gateway.outbound_http import urlopen_no_proxy_redirects  # noqa: E402

INBOX = pathlib.Path(os.getenv("MEMORY_GATEWAY_INBOX", str(ROOT / "data" / "inbox")))
PROCESSED = pathlib.Path(os.getenv("MEMORY_GATEWAY_PROCESSED", str(ROOT / "data" / "processed")))
GATEWAY = os.getenv("MEMORY_GATEWAY_URL", "http://127.0.0.1:18000")


def send(path: pathlib.Path, discard_raw: bool = False) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = {"documents": [{"conversation_id": path.stem, "text": text}]}
    if isinstance(value, list):
        value = {"documents": value}
    if not isinstance(value, dict):
        value = {"documents": [{"conversation_id": path.stem, "text": str(value)}]}
    documents = value.get("documents", value.get("conversations", value.get("items")))
    if not isinstance(documents, list):
        documents = [value]
    stable_id = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
    payload = {"source": value.get("source", f"file:{path.suffix.lower()}"), "batch_id": f"inbox-{stable_id}", "documents": documents, "delete_after_success": discard_raw}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(GATEWAY.rstrip("/") + "/v1/import", data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen_no_proxy_redirects(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-import", action="store_true", help="Confirm continuous inbox import; successful source files are moved into the processed folder")
    parser.add_argument("--once", action="store_true", help="Process current inbox contents once, then exit")
    parser.add_argument("--discard-raw-after-success", action="store_true", help="Discard the temporary raw Gateway copy after extraction")
    args = parser.parse_args()
    if not args.confirm_import:
        files = sorted(path.name for path in INBOX.glob("*") if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".md", ".txt"})
        print(json.dumps({"inbox": str(INBOX), "files_ready": files, "dry_run": True}, ensure_ascii=False, indent=2))
        print("Nothing was sent or moved. Review the file list, then rerun with --confirm-import.", file=sys.stderr)
        raise SystemExit(2)
    INBOX.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    print(f"Watching {INBOX}", flush=True)
    while True:
        for path in sorted(INBOX.iterdir()):
            if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl", ".md", ".txt"}:
                continue
            try:
                result = send(path, discard_raw=args.discard_raw_after_success)
                if result.get("status") in {"processed", "partial"}:
                    path.replace(PROCESSED / path.name)
                    print(json.dumps({"file": path.name, "result": result}, ensure_ascii=False), flush=True)
            except Exception as exc:
                print(json.dumps({"file": path.name, "error": str(exc)}, ensure_ascii=False), flush=True)
        if args.once:
            break
        time.sleep(10)


if __name__ == "__main__":
    main()
