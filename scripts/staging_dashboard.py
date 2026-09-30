"""Launch the existing dashboard without importing the sandbox's .env values."""

from __future__ import annotations

import runpy
import sys

from staging_gateway import ROOT, apply_staging_settings, block_project_env


def main() -> None:
    if sys.argv[1:] != ["--link-memory-profile=staging"]:
        raise SystemExit("The staging dashboard requires the staging profile marker.")
    block_project_env(ROOT / ".env")
    apply_staging_settings(ROOT)
    runpy.run_path(str(ROOT / "dashboard" / "serve.py"), run_name="__main__")


if __name__ == "__main__":
    main()
