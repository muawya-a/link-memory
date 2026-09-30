# Security policy

Link Memory is an early local preview. No production release or supported production version is currently declared; security fixes are handled on a best-effort basis.

## Reporting a vulnerability

Do not put vulnerability details, exploit steps, memory contents, credentials, or personal data in a public issue.

Use GitHub's [private vulnerability reporting form](https://github.com/muawya-a/link-memory/security/advisories/new) to report a suspected vulnerability. Do not include technical details in a public issue. The repository owner has not published a separate security contact address.

## Safe use

Before importing sensitive information, review the source code, network bind addresses, firewall rules, local data directory, and any external provider that you explicitly enable. Keep provider credentials out of source control and redact them from diagnostic reports.

## Current optional dependency finding

The MemPalace Windows lock currently includes `chromadb==1.5.9`. A dependency audit reports multiple upstream advisories for this version, including a critical code-injection advisory with no patched version listed. This is a dependency finding, not proof that the vulnerable server endpoints are exposed by Link Memory's local profile. The Gateway's MemPalace adapter is loopback-only, but that does not patch ChromaDB; do not expose a separate ChromaDB server to untrusted networks. Re-audit before enabling remote deployment or after an upstream fix is released. See the [ChromaDB advisory](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c).
