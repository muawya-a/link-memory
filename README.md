# Link Memory

[![CI](https://github.com/muawya-a/link-memory/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/muawya-a/link-memory/actions/workflows/ci.yml) [![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE) [![Platform: Windows x64](https://img.shields.io/badge/platform-Windows%20x64-0078D4)](#install-the-windows-app)

Link Memory is a desktop-first memory workspace that captures, organizes, and retrieves useful context from conversations. This repository contains the self-hosted/local prototype, including its Gateway, dashboard, import tools, MCP server, optional hooks, and optional memory-provider adapters.

> **Current release:** Download the Windows x64 installer from [GitHub Releases](https://github.com/muawya-a/link-memory/releases/latest). The first installer is not digitally signed, so Windows may display a SmartScreen warning. Review the source, release notes, and security guidance before installing.

The project is provided under the Apache License 2.0; see [LICENSE](LICENSE) and [source provenance](SOURCE_PROVENANCE.md). Third-party components retain their own terms; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [the dependency license inventory](DEPENDENCY_LICENSE_INVENTORY.csv). The inventory records package metadata declarations; it is not a legal opinion.

## Features

- Desktop dashboard for capture, search, review, and memory administration.
- Local Gateway with SQLite storage, backup helpers, audit/history paths, and MCP interface.
- Import from user-selected text, Markdown, JSON, JSONL, Codex CLI session files, and Claude Code transcript files.
- Optional local MCP connection for Codex and Claude Code from Settings when the selected client's CLI is installed. Prompt hooks stay separate and are never installed automatically.
- Optional Graphiti, MemPalace, reranker, and Ollama/OpenRouter integration code. These require their own configuration and dependencies; see [OPTIONAL_INTEGRATIONS.md](OPTIONAL_INTEGRATIONS.md).
- Low-resource fallback uses local deterministic rules. Better extraction can use an explicitly selected local model or API; the default does not download an AI model or send data to an external provider.
- Bilingual desktop interface with Arabic-capable system-font fallbacks; font files are not bundled.

The default launcher binds local services to loopback and does not enable external providers automatically. You can opt into supported integrations in your private `.env` after reviewing what data each integration receives.

## Install the Windows app

Download `LinkMemory-Setup-*.exe` from [GitHub Releases](https://github.com/muawya-a/link-memory/releases/latest), run it, then launch Link Memory from the Start menu. It installs per-user and bundles the Python runtime and prebuilt dashboard, so Python, Node.js, `node_modules`, and a terminal are not needed. `node_modules` is used only by GitHub Actions while building the dashboard and is excluded from the installer. Releases include a SHA-256 checksum file beside the installer. The installer is for Windows x64; optional provider/model integrations remain separate opt-ins. The executable is unsigned; Windows may show a SmartScreen warning. Use the source setup below only for development.

The app stores installed runtime data under `%LOCALAPPDATA%\Link Memory\data`, separately from the program files. The installer is designed to preserve this data folder during uninstall.

## Requirements

- The Windows x64 installer includes a bundled per-user Python runtime and a prebuilt dashboard; it does not require users to install Python, Node.js, or `node_modules`.
- The source-download route below is for developers. Its one-time setup requires Python, Node.js, and npm to build the dashboard.
- Windows 10 or 11 for the supplied PowerShell launcher.
- Python 3.10 or later.
- Node.js 20 or later and npm to build the dashboard.
- Optional services and Python packages only for the integration you choose.

## Install from source on Windows

Use this route for development or when you want to build from source.

1. Install Python 3.10 or later and Node.js 20 or later from their official sources.
2. Download or clone this repository. Do not place private conversation exports inside the project folder.
3. Run the setup script once. It installs frontend packages from the exact npm lockfile, builds the dashboard, starts the local Gateway and dashboard, and opens the desktop UI:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\Setup-Link-Memory.ps1
   ```

4. For later launches, use the desktop shortcut or run:

   ```powershell
   .\Start-Link-Memory.ps1
   ```

To install the locked frontend dependencies and build without starting local services, run `powershell -ExecutionPolicy Bypass -File .\Setup-Link-Memory.ps1 -BuildOnly`.

5. Open `http://127.0.0.1:18765/react/` if the browser did not open automatically.
6. Stop the local services with `.\scripts\stop.ps1`.

The desktop shortcut `Start-Link-Memory.vbs` starts the same local instance. For source runs, runtime records and backups are created under the ignored `data/` folder. The packaged installer stores them under `%LOCALAPPDATA%\Link Memory\data`; they are not part of the installer and are preserved separately from the app files.

## Import old conversations

Read [IMPORTING_DATA.md](IMPORTING_DATA.md) before importing. Every importer first previews what it found. Review the preview, then run again with `--confirm-import` to send selected conversation text to the Gateway. The source files are read-only; the importer does not move or delete them. A separate flag is required to discard the Gateway's temporary raw copy after extraction.

Codex CLI session import reads `CODEX_HOME/sessions` (or `~/.codex/sessions` if `CODEX_HOME` is unset). Claude Code import reads `CLAUDE_CONFIG_DIR/projects` (or `~/.claude/projects`) or accepts files selected with `--file`. Imports only include user/assistant text and omit tool payloads and machine-specific absolute paths.

This supports local Codex CLI and Claude Code files. It does **not** connect to or download history from ChatGPT/Codex Cloud, Claude.ai, or another hosted account. For cloud histories, use an export you obtain yourself and review it before importing with `scripts/import_file.py`.

## Connect Codex and Claude Code

From Settings, select Codex or Claude Code and choose **Connect** to register Link Memory's local MCP server in that user's client configuration. The matching client CLI must already be installed. Restart the client and review its trust prompt if shown. This does not install hooks or import/save conversations automatically; memory tools act only when explicitly used. Manual config snippets and optional prompt hooks are documented in [CLIENT_INTEGRATIONS.md](CLIENT_INTEGRATIONS.md). If you enable a remote model/provider in Link Memory, that provider may receive imported or queried content as described in [PRIVACY.md](PRIVACY.md).

## Privacy and data handling

- This preview runs on your computer; it is not the Link Memory hosted SaaS and has no hosted accounts, cross-device synchronization, tenancy, billing, or service guarantees.
- Source transcripts stay where they are. Imported text is stored in the local Gateway database; backups may also contain memory records.
- The default importer keeps the temporary raw copy in the Gateway. If you explicitly choose `--discard-raw-after-success`, the Gateway removes that temporary copy after processing; extracted memory records remain.
- Provider integrations are opt-in. Review provider terms, network settings, and data handling before enabling them.
- Before importing, make sure you have the right to process the conversations and that you want their selected content in this Gateway. Do not import credentials, secrets, or other people's private conversations without authorization.

Downloading this source code does not import anyone's old or new conversation data and does not signify consent to process it. Running an importer with `--confirm-import` is the explicit action that submits the selected data; review the file list and preview first.

## Project structure

| Path | Purpose |
| --- | --- |
| `dashboard-react/` | Dashboard source and build configuration |
| `dashboard/` | Local static-file server |
| `gateway/` | API, local database, MCP, hooks, and adapters |
| `scripts/` | Windows launchers, importers, backup, and client hook examples |
| `data/` | Runtime data created locally; ignored by Git |
| `packaging/windows/` | Windows installer definition and clean staging builder |
| `deployment/` | Local staging profile and deployment notes |
| `tests/` | Backend and dashboard test suites |
| Root Markdown guides | Changelog, import, privacy, integrations, provenance, and security guidance |

## Developer checks

The existing test suites are under `tests/`. On Windows x64 with Python 3.12, install developer-only packages with `python -m pip install --require-hashes -r requirements-dev-win-py312.lock.txt`; UI checks also need `python -m playwright install chromium`. Run backend tests with `python -m pytest tests/backend`. UI checks use Playwright and a running Link Memory dashboard. Some integration checks require their optional local services. Review each test's documented preconditions before running it. The staging profile is documented in [deployment/README.md](deployment/README.md).

## Typeface

No font files are bundled. The interface uses installed system fonts with Arabic-capable fallbacks. For recommended font choices and their licenses, see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Security

See [SECURITY.md](SECURITY.md) for the current reporting instructions. Before opening an issue, remove personal information, credentials, local paths, and private conversation content from logs or screenshots.

## العربية

Link Memory مساحة ذاكرة مكتبية تجمع بين الحفظ والبحث والاسترجاع من سياق المحادثات. يحتوي هذا المستودع على النموذج المحلي: لوحة التحكم، والـGateway، وقاعدة SQLite، وأدوات الاستيراد، وMCP، وملفات التكامل الاختيارية مع Codex وClaude Code ومزوّدات الذاكرة.

للتثبيت العادي على Windows، نزّل ملف `LinkMemory-Setup-*.exe` من صفحة Releases. الواجهة مبنية ومضمّنة في المثبّت؛ المستخدم لا يحتاج Node.js أو مجلد `node_modules` أو الطرفية. تنزيل Source code ZIP مخصص للمطورين، وخطواته تبني الواجهة وتتطلب Python وNode.js وnpm.

الترخيص المختار للمشروع هو Apache-2.0، مع بقاء تراخيص المكونات الخارجية مستقلة. الخطوط غير مضمّنة. التشغيل الافتراضي محلي على الجهاز، والتكاملات الخارجية لا تعمل حتى يضبطها المستخدم في ملف `.env` الخاص به.

قبل استيراد سجل قديم، اقرأ [دليل استيراد البيانات](IMPORTING_DATA.md). تعرض الأدوات معاينة أولًا؛ وبعد مراجعتها يلزم تمرير `--confirm-import` لإرسال النص المحدد إلى الـGateway. ملفات المصدر لا تُنقل ولا تُحذف. يدعم المشروع ملفات جلسات Codex CLI وClaude Code المحلية، لكنه لا يتصل بحسابات ChatGPT/Codex Cloud أو Claude.ai ولا يسحب سجلاتها مباشرة.

تنزيل الشيفرة لا يستورد بيانات أي شخص ولا يعني الموافقة على معالجتها. الموافقة الصريحة تكون عند تشغيل أداة الاستيراد مع `--confirm-import` بعد مراجعة الملفات والمعاينة. راجع سياسة الخصوصية وملفات التكامل قبل تفعيل مزوّد خارجي.
