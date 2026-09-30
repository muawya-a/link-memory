"""Dependency-free local static server for the Memory Gateway dashboard."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import json
from pathlib import Path
import os
import time


def load_local_env() -> None:
    """Use the same project LAN settings as the Gateway process."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_local_env()
HOST = os.getenv("MEMORY_DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.getenv("MEMORY_DASHBOARD_PORT", "18765"))

if __name__ == "__main__":
    directory = Path(__file__).resolve().parent
    built_dashboard = directory / "react" / "index.html"
    if not built_dashboard.is_file():
        raise SystemExit("Dashboard build is missing. Build dashboard-react first; no stale dashboard is served.")
    built_assets = list((directory / "react" / "assets").glob("*.js"))
    if not built_assets or any(b"127.0.0.1:8000" in asset.read_bytes() for asset in built_assets):
        raise SystemExit("Dashboard build is stale or incomplete. Rebuild from dashboard-react before starting the sandbox.")
    class DashboardHandler(SimpleHTTPRequestHandler):
        """Serve one shared dashboard source without stale browser assets."""

        def end_headers(self):
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            super().end_headers()

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path in {"", "/"}:
                self.send_response(302)
                self.send_header("Location", "/react/" + (f"?{query}" if query else ""))
                self.end_headers()
                return
            if path == "/__link-memory-version":
                assets = [directory / "react" / "index.html", *((directory / "react" / "assets").glob("*"))]
                version = max((asset.stat().st_mtime_ns for asset in assets if asset.exists()), default=0)
                payload = json.dumps({"version": version, "server_time": time.time()}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            super().do_GET()

    handler = lambda *args, **kwargs: DashboardHandler(*args, directory=str(directory), **kwargs)
    print(f"Dashboard listening on http://{HOST}:{PORT}/")
    ThreadingHTTPServer((HOST, PORT), handler).serve_forever()
