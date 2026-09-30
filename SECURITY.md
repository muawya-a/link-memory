# Security policy

Link Memory is an early local preview. No production release or supported production version is currently declared; security fixes are handled on a best-effort basis.

## Reporting a vulnerability

Do not put vulnerability details, exploit steps, memory contents, credentials, or personal data in a public issue.

Use GitHub's [private vulnerability reporting form](https://github.com/muawya-a/link-memory/security/advisories/new) to report a suspected vulnerability. Do not include technical details in a public issue. The repository owner has not published a separate security contact address.

## Safe use

Before importing sensitive information, review the source code, network bind addresses, firewall rules, local data directory, and any external provider that you explicitly enable. Keep provider credentials out of source control and redact them from diagnostic reports.

## Current optional dependency finding

The optional Windows MemPalace lock includes `chromadb==1.5.9`, required by `mempalace==3.10.0` (`chromadb>=1.5.4,<2`). The current upstream advisories mark versions through 1.5.9 affected and list no patched release: [CVE-2026-45829](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c), [CVE-2026-45830](https://github.com/advisories/GHSA-2wm9-hf6c-p5cr), [CVE-2026-45831](https://github.com/advisories/GHSA-xph7-9rjv-w5fr), and [CVE-2026-45833](https://github.com/advisories/GHSA-36p7-vc44-83pf). The lock audit currently reports five findings across these four unique advisories. Do not downgrade ChromaDB as a workaround: it would violate MemPalace's declared dependency and would not clear the advisories.

The Link Memory launcher starts the Gateway and dashboard; it does not start ChromaDB's HTTP server or MemPalace's MCP server. The optional adapter code uses MemPalace's in-process storage/search APIs and checks that its own HTTP listener binds only to loopback. These controls reduce network exposure on Link Memory's documented local path; they do **not** patch ChromaDB or make the dependency vulnerability fixed. Do not start or expose a separate ChromaDB service on an untrusted network. Keep MemPalace optional, and re-audit when ChromaDB publishes a patched release compatible with MemPalace.
