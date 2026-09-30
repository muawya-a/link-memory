# Importing conversation history

Importers read local files and send selected conversation text to the Link Memory Gateway address you provide. The default Gateway URL is `http://127.0.0.1:18000`. Check `--gateway` before use; a remote URL sends data to that remote server.

## What gets imported

- **Codex CLI:** `user` and `assistant` message text from JSONL session files. Tool calls, command output, and other record types are skipped.
- **Claude Code:** text blocks in `user` and `assistant` messages from JSONL transcript files. Tool-use and tool-result records are skipped.
- **OpenAI/ChatGPT export:** user/assistant text from a locally selected `conversations.json` export. Only the branch marked as current in the export is retained when available; tool messages, titles, node IDs, timestamps, and raw platform conversation IDs are excluded. The conversation ID sent to the Gateway is a truncated SHA-256-derived opaque value.
- **Claude Code JSONL export:** a locally selected transcript is recognized by the generic importer and contributes user/assistant text blocks only.
- **Generic export:** a JSON object, JSON array, JSONL, Markdown, or plain text file selected by you.

These file parsers do not sign in to or download data from any hosted account. OpenAI's export format supports `conversations.json`; this does not establish complete support for every Codex Cloud-specific file or schema. Preview each export and verify the output before confirming an import.

Imports are bounded by message and character limits where available. The source files are opened read-only and are never moved or deleted. Importers send only the documented conversation fields; they do not copy machine-specific absolute source paths or provider turn identifiers.

For Codex CLI sessions, each imported document contains `source: "codex-history"`, an opaque stable `conversation_id` derived from the local session path, `occurred_at` from the source file's modification time, user/assistant message roles and text, and metadata containing only the importer name (`capture`) and imported message count (`message_count`). The original path, filename, file size, and Codex `turn_id` values are not sent. Turn IDs are used only in memory while deduplicating repeated records in one import. The stable conversation ID is a one-way SHA-256-derived identifier; moving or renaming a session file changes it.

## 1. Preview Codex CLI sessions

With Link Memory running, preview all eligible local session files:

```powershell
python .\scripts\codex_history_import.py --dry-run
```

Choose a different Codex data directory, for example:

```powershell
python .\scripts\codex_history_import.py --codex-home 'D:\CodexData' --since-days 30 --limit 25 --dry-run
```

By default, the importer reads `CODEX_HOME` when it is set, otherwise `%USERPROFILE%\.codex`. It reads `sessions/` below that directory. It skips sessions modified in the last five minutes; `--include-active` overrides that guard.

## 2. Preview Claude Code sessions

Preview local Claude Code transcripts:

```powershell
python .\scripts\claude_code_history_import.py --limit 25
```

Select one or more files instead of scanning the default transcript directory:

```powershell
python .\scripts\claude_code_history_import.py --file 'D:\exports\session.jsonl'
```

By default, it scans `%USERPROFILE%\.claude\projects`. `CLAUDE_CONFIG_DIR` can point to a different Claude Code config directory.

These locations and JSONL structures reflect current local implementations; the transcript formats are not a stable cross-product import API and may change. Start with a small preview/import and confirm the resulting memories before importing a large archive.

## 3. Confirm an import

Inspect the preview counts and selected source. Then rerun the same command with `--confirm-import`:

```powershell
python .\scripts\codex_history_import.py --since-days 30 --limit 25 --confirm-import
python .\scripts\claude_code_history_import.py --limit 25 --confirm-import
```

The importer reports per-batch results. A failed/partial result must be reviewed before retrying. Idempotency identifiers reduce duplicate processing on retries, but they do not replace checking the Gateway's import status.

To import a file you exported yourself:

```powershell
python .\scripts\import_file.py 'D:\exports\conversation.json'
python .\scripts\import_file.py 'D:\exports\conversation.json' --confirm-import
```

The first command previews; only the second sends. Avoid putting exports inside the repository or sharing them in public issues.

## Raw copy retention

By default, the Gateway keeps its raw import document as well as extracted memories. If you prefer the Gateway to discard the temporary raw document after successful extraction, add `--discard-raw-after-success`. This does not delete or alter the original Codex/Claude/export files, and it does not delete the extracted memories. Backups and logs may still contain metadata; review retention before importing sensitive data.

## Optional inbox watcher

The inbox watcher is not started automatically. Its preview lists supported files under `data/inbox` without reading or sending them:

```powershell
python .\scripts\watch_inbox.py
```

After you review that list, `--confirm-import --once` imports the current inbox one time. Successful source files are moved into `data/processed`; the original bytes are retained there. `--confirm-import` without `--once` continuously watches for new files and imports them as they arrive. Add `--discard-raw-after-success` only if you also want the Gateway's temporary raw copy removed after extraction.

## Hosted/cloud history

These scripts do not log in to ChatGPT, Codex Cloud, Claude.ai, or other hosted accounts. They cannot read a remote account's history. If the provider offers an export that you are authorized to process, download it yourself, review its contents, then select the relevant files with the generic importer. Do not assume a cloud export is compatible until its structure has been checked in preview.

## Before you confirm

1. Confirm the Gateway URL points to the intended local or remote server.
2. Confirm you have authorization to process every selected conversation.
3. Review the file selection and preview counts; exclude credentials and third-party private content.
4. Review [PRIVACY.md](PRIVACY.md) and any enabled provider's data terms.
5. Keep a backup before a large import and test with a small selection first.
