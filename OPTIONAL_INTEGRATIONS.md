# Optional integrations

The project retains optional adapter code for local or separately hosted model and memory services. The base Gateway is the low-resource path: it stores to local SQLite/FTS and uses the built-in rule-based classifier without downloading a model. Local semantic models and memory providers are optional because they increase disk, RAM, and startup costs. The default Windows launcher does not inherit provider secrets from the parent shell. It reads optional values only from a private `.env` in this checkout. Copy `.env.example` to `.env`, configure only the services you have installed, and keep `.env` out of Git.

All adapter flags are `false` by default. The Gateway also denies remote egress unless `MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED=true` and an exact allowlist is configured. Loopback-only services are suitable for a local preview; exposing them to a LAN or internet requires a separate security review.

| Capability | Settings | Extra setup |
| --- | --- | --- |
| Ollama analysis/embeddings | `OLLAMA_ENABLED`, `OLLAMA_URL`, model fields | Install and run Ollama locally; install matching Python extras if required |
| Reranking | `RERANKER_ENABLED`, `RERANKER_URL` | Install the pinned optional ML packages and run the reranker service |
| OpenMemory-compatible adapter | `OPENMEMORY_ENABLED`, `OPENMEMORY_URL` | The existing Gateway contract expects `/v1/ingest` and `/v1/recall`. The previously copied `providers/openmemory-src` tree was LongMemory, not OpenMemory, and is excluded pending provenance and license evidence. Do not point this setting at a different OpenMemory project unless its API contract is verified. |
| Graphiti | `GRAPHITI_ENABLED`, `GRAPHITI_URL`, Neo4j fields | Install `requirements-graphiti-win-py312.lock.txt`, configure a graph database and an LLM/embedder, then allow only exact service origins |
| MemPalace | `MEMPALACE_ENABLED`, `MEMPALACE_URL` | The adapter imports the official PyPI `mempalace` package. Version `3.10.0` is pinned in `requirements-mempalace.txt`; compatibility still needs an end-to-end test before calling this integration supported. |
| OpenRouter model routing | `OPENROUTER_URL`, `OPENROUTER_API_KEY` | Optional third-party API; review its data terms, costs, and egress allowlist |

## Python extras and licensing notes

- The default application uses its base `requirements.txt` and does not require AI model downloads or provider SDKs.
- Optional Python dependencies are split by feature in `requirements-graphiti.txt`, `requirements-mempalace.txt`, `requirements-reranker.txt`, and `requirements-pdf.txt`; each has a hashed Windows x64/CPython 3.12 lock. Use the matching lock with `pip install --require-hashes -r <lockfile>`. The developer tests have their own lock. The reranker lock uses CPU PyTorch. Other platforms/Python versions need their own generated and tested lockfiles.
- The local reranker is optional and heavy: its pinned PyTorch/Sentence Transformers packages can consume substantial download and disk space. Keep it off on low-resource machines unless the user chooses it.
- PyMuPDF is not in the default requirements. It is available under AGPL-3.0 or commercial terms; the project must select and satisfy the applicable terms before shipping or enabling PDF extraction in a commercial service.
- MemPalace is published under MIT according to its official PyPI metadata and source project. Its direct version is now pinned; integration behavior remains unverified until a clean install and round-trip test pass.
- LongMemory is not bundled because the source checkout lacks enough provenance to establish the exact revision and notices. Obtain it from its upstream, independently review its license and dependencies, and configure the compatible service URL.

## Local classification and model choice

- Basic fact/type classification uses deterministic local rules; it does not require an LLM or API key and does not claim semantic understanding.
- For better extraction, the user may opt into a locally installed model/runtime or configure an external API such as OpenRouter. Remote model use is not enabled by default and must remain visible in the privacy settings.
- Graphiti is an optional relation/event layer, not a low-resource default. It requires a graph database and an embedding/LLM configuration; choose local endpoints if all processing must stay on the device.
- MemPalace is the optional transcript/archive layer. The Gateway's existing OpenMemory-compatible fact-layer endpoint is a separate adapter contract; “OpenMemory” currently refers to multiple unrelated repositories, so do not substitute a project based on its name alone.

These integrations are preserved as source capabilities, but they have not all been verified end-to-end in this public draft. Do not read the presence of a settings toggle as evidence that a remote service is installed or that its privacy, licensing, and failure behavior has passed validation.
