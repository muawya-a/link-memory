# Changelog

## [0.1.1] - 2026-10-05

### Added

- One-click local MCP registration for Codex and Claude Code from Link Memory Settings when the selected CLI is installed.
- SHA-256 checksum asset for the Windows installer.

### Improved

- MCP registration is restricted to the local machine, preserves existing entries, and refuses to overwrite a different server using the `link-memory` name.
- Setup instructions distinguish the end-user Windows installer from the developer source-build route. The installer includes the prebuilt dashboard and bundled Python runtime; Node.js and `node_modules` are only needed at build time.

### Privacy and compatibility

- MCP registration does not install prompt hooks or import conversations. Memory capture remains an explicit tool action.
- This release remains an unsigned Windows x64 installer. Windows SmartScreen may display a warning.
