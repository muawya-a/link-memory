# Provider API discovery contract

The Settings page now exposes **Discover a compatible API**. A user supplies an API root such as `http://127.0.0.1:11434/v1` or an approved HTTPS origin and clicks **Inspect model catalog**. Discovery requests only `GET {root}/models` and reads model `id` values from the OpenAI-compatible `data` array. It does not send a prompt, memory, or inference request. The Gateway endpoint is `POST /v1/provider/discover`; it requires the same Gateway authorization as other write routes.

The Gateway helper is `gateway/provider_discovery.py`. It rejects URL credentials, query strings, fragments, and a base URL already ending in `/models`; it caps the response at 1 MB and returns only model IDs. Requests use the shared egress boundary, which disables ambient proxies and redirects. Non-loopback destinations still require explicit remote-egress enablement and an exact HTTPS origin allowlist. The address and API key are held only in page memory; the key, if provided, is sent to the selected Gateway and then to that destination in a bearer header for catalog discovery. The Gateway does not return or persist the key, and clears the page's key field after the request.

## What discovery can establish

- An OpenAI-compatible `data` catalog with no entries is reported as `empty_catalog`.
- One entry is reported as `single_model_catalog`; multiple entries as `model_catalog`.
- An incompatible response is rejected. A vendor name is never guessed from its hostname.
- One model in a catalog does **not** prove that the remote service is a single-model runtime. The classification describes the observed response only.
- At most 500 model IDs are returned; a `truncated` flag marks larger catalogs.

Discovery is not inference support. Before an API may process memory, the UI must separately show the exact destination, data leaving the device, expected cost/terms, and ask for explicit opt-in. Inference currently has separate adapters; this helper does not enable `/chat/completions`, store credentials, or route memory. Arbitrary REST and vendor-specific protocols need separately reviewed adapters and response parsers.

## Memory-layer setup boundary

The core local SQLite/FTS layer and deterministic classification remain available without a model API. Graphiti is optional, not an OpenAI service: it needs a graph database and compatible LLM and embedding endpoints. The current pinned Graphiti extra includes `openai` as a Python SDK transport dependency; that does not require an OpenAI-hosted key, but a future UI must let the user choose local or compatible endpoints and must keep secrets out of browser storage/logs.

There is not yet a safe one-click installer for all three optional memory providers. The fact-layer upstream is unresolved: the previously copied `providers/openmemory-src` was a different project, so it must not be fetched or installed by name alone. A one-click setup needs verified upstream URLs/revisions/licenses, platform-specific pinned dependency manifests, explicit per-provider consent, resource estimates, and an install/rollback flow. Graph database installation is also a distinct resource-heavy decision and should not silently be included in the base install.
