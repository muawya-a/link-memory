# Privacy notes for the local preview

This preview is intended to run on one computer. The Gateway and dashboard bind to `127.0.0.1` by default. Memory data, SQLite files, backups, and inbox files are stored under the local checkout's `data/` directory.

The default configuration does not require a hosted Link Memory account or AI API key. Optional model and provider settings can make the app send request content to the service selected by the operator. The app cannot promise local-only processing after an external provider is enabled; review that provider's current terms and privacy documentation first.

The dashboard stores its selected API base URL in browser `localStorage` and an optional API key in `sessionStorage`. Do not use a shared browser profile for secrets. The application has no account system, multi-user isolation, cloud sync, or production data-retention guarantees in this preview.

The supplied launcher does not start the optional inbox watcher. If you run it manually, it reads supported files from the configured inbox and moves successfully processed inbox files into a processed subfolder. Review the script and the files first. The Codex/Claude Code import scripts are read-only on source transcripts and require an explicit `--confirm-import` before sending text to the Gateway.

The Gateway keeps the temporary raw import copy by default. Import scripts provide `--discard-raw-after-success` to opt into removing that temporary Gateway copy after extraction; the optional Codex turn notifier has the equivalent `MEMORY_GATEWAY_DISCARD_RAW_AFTER_SUCCESS` setting, which defaults to false. Extracted memory records remain. These options never delete the original source file. A configured remote model or memory provider may receive content needed for its operation. The Gateway's network allowlist and integration flags must be reviewed before enabling any remote connection.

There is no automatic integration with ChatGPT/Codex Cloud or Claude.ai history. Locally stored Codex CLI and Claude Code transcripts can be selected for import. Hosted-account exports must be obtained and reviewed by the user.

Do not submit real personal or confidential information in public issues, screenshots, recordings, or benchmark fixtures. Before any wider test, use synthetic data and verify deletion, backups, and provider egress for the exact configuration being tested.
