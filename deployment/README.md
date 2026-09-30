# Local deployment profiles

Link Memory can run either a primary local profile or an isolated staging profile on the same computer. Each profile uses separate local data and ports. The desktop application is designed for a single user on a local machine; this setup is not a public cloud deployment.

## Primary local profile

Start the default Gateway and dashboard:

```powershell
.\scripts\start.ps1
```

Open `http://127.0.0.1:18765/react/`. Local records are created under `data/`.

## Isolated staging profile

Start a second local profile with a separate database and dashboard:

```powershell
.\scripts\start.ps1 -Profile staging
```

Open `http://127.0.0.1:28765/react/`. This profile writes under `staging-data/`; it does not reuse the primary profile's local database. Stop it with:

```powershell
.\scripts\stop.ps1 -Profile staging
```

Use synthetic records for evaluation. Inspect `scripts/profile.ps1` before changing the profile paths, and keep all local data directories excluded from source control.

## Optional integrations

Optional model and memory providers are configured separately in a private `.env`. See [OPTIONAL_INTEGRATIONS.md](../OPTIONAL_INTEGRATIONS.md). The app launcher binds to loopback and does not start optional provider services unless explicitly configured.

## Hosted deployment

The repository does not provide a supported hosted SaaS deployment. Before exposing a server to a network, design and verify authentication, tenant isolation, authorization, TLS, secret storage, backups and restore, monitoring, retention/deletion, provider data handling, and operational incident response. The local profiles are not a substitute for those controls.
