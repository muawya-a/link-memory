# Windows installer build

The installer bundles a prebuilt dashboard and the official Python embeddable runtime. End users do not need Node.js, Python, a terminal, or PowerShell commands. The installer is per-user and creates Start menu shortcuts; the desktop shortcut is optional. The bundled runtime remains under the Python Software Foundation license, with its `LICENSE.txt` shipped beside the runtime.

## Build

Run the `Windows installer preview` workflow from the repository's Actions page. It builds the React dashboard, downloads the 64-bit Python 3.13.16 embeddable runtime from python.org and verifies its SHA-256 checksum, checks Python's standard-library SQLite support and license notice, stages only project files, compiles the Inno Setup installer, and uploads `LinkMemory-Setup-0.1.0.exe` as a 14-day workflow artifact.

This workflow does not publish a GitHub Release. A maintainer must review the artifact on a clean Windows 10/11 profile, confirm upgrade and uninstall behavior, check that user data remains in place, and then decide whether to publish it as a Release.

## Current boundaries

- The base app uses the bundled Python runtime and local SQLite. Node.js is used only on the build runner to create the dashboard.
- Optional provider services and their Python packages are not installed by this installer. Users must opt into and configure optional integrations separately.
- The installer is not code-signed. Windows may show a publisher or SmartScreen warning until the release is signed with a verified publisher certificate.
- Runtime data is created under `%LOCALAPPDATA%\Link Memory\data`, outside the program installation folder. Upgrades and uninstall are intended to preserve it.
- The workflow creates a build artifact only; it does not create or publish a release, package, or update channel.

## Maintainer verification checklist

1. Install on a clean Windows 10/11 account that has neither Python nor Node.js installed.
2. Confirm installation needs no administrator prompt and launches the local dashboard.
3. Add a test memory, restart Link Memory, and confirm the memory persists under the installed `data/` directory.
4. Confirm the default configuration binds local services to loopback and makes no provider request.
5. Confirm Start menu launch, Stop shortcut, upgrade over an earlier install, and uninstall behavior.
6. Confirm uninstall stops only Link Memory processes and preserves user data.
