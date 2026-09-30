# Sandbox dashboard server

The dashboard is served locally at `http://127.0.0.1:18765/react/` after building the React app from `dashboard-react`. The server refuses to serve a missing build. Gateway traffic is configured separately on sandbox port `18000`.

The delivered sandbox does not include a dashboard build as a required source artifact. Build it locally after installing the dependencies described by `dashboard-react/package-lock.json`.
