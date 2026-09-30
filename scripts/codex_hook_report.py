"""Print a compact report for a Codex hook observation window."""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "codex-hook-events.jsonl"


def main() -> int:
    minutes = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    events = []
    if LOG_PATH.exists():
        for line in LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
                timestamp = datetime.fromisoformat(str(item.get("timestamp", "")).replace("Z", "+00:00"))
                if timestamp >= cutoff:
                    events.append(item)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
    submitted = [item for item in events if item.get("status") == "submitted"]
    print(json.dumps({
        "window_minutes": minutes,
        "hook_events": len(events),
        "by_status": dict(Counter(str(item.get("status", "unknown")) for item in events)),
        "turns_submitted": len(submitted),
        "messages_captured": sum(int(item.get("messages", 0)) for item in submitted),
        "characters_captured": sum(int(item.get("characters", 0)) for item in submitted),
        "events": events[-20:],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
