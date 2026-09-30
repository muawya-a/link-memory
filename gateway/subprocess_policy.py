"""Minimal environment for local optional-provider subprocesses."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


_SAFE_PLATFORM_ENV = (
    "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "HOME",
)


def build_mempalace_child_env(
    parent: Mapping[str, str], palace_path: Path, source_path: Path
) -> dict[str, str]:
    """Pass only platform paths and explicit local storage settings to MemPalace."""
    child = {key: parent[key] for key in _SAFE_PLATFORM_ENV if parent.get(key)}
    child.update({
        "MEMPALACE_PALACE_PATH": str(palace_path),
        "MEMPALACE_SOURCE_PATH": str(source_path),
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYTHONNOUSERSITE": "1",
    })
    return child
