"""Explicit, no-inference discovery for OpenAI-compatible model APIs.

Discovery only performs GET ``/models``. It never sends memory content, invokes
``/chat/completions``, persists credentials, or decides that an endpoint is safe
for inference. Callers must separately obtain consent before using a provider.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

try:
    from .outbound_http import urlopen_no_proxy_redirects
except ImportError:  # imported as a direct Gateway module by the Windows app
    from outbound_http import urlopen_no_proxy_redirects


MAX_CATALOG_BYTES = 1_000_000
MAX_MODELS = 500


def _models_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url or len(base_url) > 2048 or base_url != base_url.strip():
        raise ValueError("provider_base_url_invalid")
    try:
        parsed = urllib.parse.urlsplit(base_url)
        _ = parsed.port
    except ValueError:
        raise ValueError("provider_base_url_invalid") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(ord(char) < 32 or char.isspace() for char in base_url)
    ):
        raise ValueError("provider_base_url_invalid")
    path = parsed.path.rstrip("/")
    # Accept either an OpenAI-compatible root or one already ending in /v1.
    if path.endswith("/models"):
        raise ValueError("provider_base_url_must_be_api_root")
    path = f"{path}/models" if path else "/v1/models"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _catalog_items(payload: Any) -> tuple[list[dict[str, str]], bool] | None:
    """Parse only the documented OpenAI-compatible ``data[].id`` shape."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return None
    models: list[dict[str, str]] = []
    for item in payload["data"][:MAX_MODELS]:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        # Return only identifiers; provider payload metadata may contain fields
        # that are not needed for discovery or safe to surface in the UI.
        models.append({"id": model_id.strip()[:200]})
    return models, len(payload["data"]) > MAX_MODELS


def classify_catalog(payload: Any) -> dict[str, Any]:
    """Return a bounded description; never infer vendor identity from a URL."""
    parsed = _catalog_items(payload)
    if parsed is None:
        return {"compatible": False, "kind": "unknown", "models": []}
    models, truncated = parsed
    count = len(models)
    if count == 0:
        kind = "empty_catalog"
    elif count == 1:
        kind = "single_model_catalog"
    else:
        kind = "model_catalog"
    return {"compatible": True, "kind": kind, "models": models, "model_count": count, "truncated": truncated}


def discover_openai_compatible_models(base_url: str, api_key: str = "") -> dict[str, Any]:
    """Fetch an explicitly requested compatible catalog without inference.

    Remote destinations still require the Gateway's exact-origin HTTPS egress
    allowlist and global remote-egress opt-in. Redirects and ambient proxies are
    disabled by ``urlopen_no_proxy_redirects``. The key is request-scoped only.
    """
    url = _models_url(base_url)
    if api_key is not None and not isinstance(api_key, str):
        raise ValueError("provider_api_key_invalid")
    api_key = str(api_key or "").strip()
    if len(api_key) > 300 or any(ord(char) < 32 for char in api_key):
        raise ValueError("provider_api_key_invalid")
    headers = {"Accept": "application/json", "User-Agent": "Link-Memory/0.1"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urlopen_no_proxy_redirects(request, timeout=8) as response:
            raw = response.read(MAX_CATALOG_BYTES + 1)
        if len(raw) > MAX_CATALOG_BYTES:
            raise ValueError("provider_catalog_too_large")
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        raise ValueError(f"provider_catalog_http_{exc.code}") from None
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("provider_catalog_unavailable") from None
    result = classify_catalog(payload)
    if not result["compatible"]:
        raise ValueError("provider_catalog_not_openai_compatible")
    result["endpoint_kind"] = "openai_compatible_models"
    return result
