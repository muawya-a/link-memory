"""End-to-end smoke test for the live Link Memory React dashboard.

Run with: uvx --with playwright python tests/ui/test_webapp.py
Set LINK_MEMORY_UI_BASE_URL to a separate local Vite URL to avoid the shared preview.
The test uses an installed Chrome browser in headless mode and never writes data.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import tomllib
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright


sys.stdout.reconfigure(encoding="utf-8")
BASE_URL = os.environ.get("LINK_MEMORY_UI_BASE_URL", "http://127.0.0.1:18765/react/").rstrip("/") + "/"
ROUTES = {
    "overview": "كل ما يحدث في الذاكرة، أمامك.",
    "recall": "اسأل الذاكرة مباشرة",
    "operations": "العمليات",
    "layers": "طبقات الذاكرة",
    "settings": "مزودو النماذج",
}
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1000},
    "compact_desktop": {"width": 1024, "height": 768},
}


def visible_button(page: Page, name: str):
    matches = page.get_by_role("button", name=name, exact=True)
    for index in range(matches.count()):
        candidate = matches.nth(index)
        if candidate.is_visible():
            return candidate
    raise AssertionError(f"No visible button named {name!r}")


def assert_accessible_controls(page: Page) -> None:
    unnamed = page.locator("button").evaluate_all(
        """elements => elements.filter(element => {
          const text = (element.textContent || '').trim();
          return !text && !element.getAttribute('aria-label') && !element.getAttribute('title');
        }).length"""
    )
    assert unnamed == 0, f"Found {unnamed} unnamed buttons"
    unlabeled = page.locator("input, textarea, select").evaluate_all(
        """elements => elements.filter(element => {
          if (element.type === 'hidden' || element.getAttribute('aria-hidden') === 'true') return false;
          const labels = element.labels ? element.labels.length : 0;
          return !labels && !element.getAttribute('aria-label') &&
            !element.getAttribute('placeholder') && !element.getAttribute('title');
        }).map(element => element.outerHTML)"""
    )
    assert not unlabeled, f"Found unlabeled form controls: {unlabeled}"


def json_response(payload: dict[str, object]):
    body = json.dumps(payload, ensure_ascii=False)

    def handle(route) -> None:
        route.fulfill(status=200, content_type="application/json", body=body)

    return handle


def mcp_status_fixture(include_availability: bool = True) -> dict[str, object]:
    project_root = Path(__file__).resolve().parents[2]
    command = sys.executable
    args = [str(project_root / "gateway" / "mcp_server.py")]
    cwd = str(project_root)
    env = {"PYTHONIOENCODING": "utf-8"}
    codex_config = "\n".join(
        [
            "[mcp_servers.link-memory-memory]",
            f"command = {json.dumps(command)}",
            f"args = {json.dumps(args)}",
            f"cwd = {json.dumps(cwd)}",
            'env = { PYTHONIOENCODING = "utf-8" }',
            "",
        ]
    )
    claude_config = json.dumps(
        {"mcpServers": {"link-memory-memory": {"command": command, "args": args, "env": env}}},
        ensure_ascii=False,
        indent=2,
    )
    status = {
        "ok": True,
        "mcp_available": True,
        "name": "link-memory-memory",
        "tools": ["memory_context", "memory_capture"],
        "client_configs": {
            "codex": {"format": "toml", "filename": "link-memory-mcp-snippet.toml", "content": codex_config},
            "claude_code": {"format": "json", "filename": "link-memory.mcp.json", "content": claude_config},
        },
    }
    if not include_availability:
        status.pop("mcp_available")
    return status


def assert_customer_routes_hide_provider_names(base_url: str) -> dict[str, str]:
    """Check customer-facing routes against synthetic healthy and partial states."""
    providers = ("OpenMemory", "Graphiti", "MemPalace")
    state = {"availability": "healthy"}
    unexpected_api: list[str] = []
    results: dict[str, str] = {}

    def mock_local_api(route) -> None:
        path = route.request.url.split("127.0.0.1:18766", 1)[-1].split("?", 1)[0]
        available = state["availability"] == "healthy"
        provider_status = {
            "openmemory": {"available": available, "data": {"store": {"working_memory": 2}}},
            "graphiti": {"available": available},
            "mempalace": {"available": available},
        }
        health_providers = (
            {}
            if state["availability"] == "unknown"
            else {name: {"available": available} for name in ("openmemory", "graphiti", "mempalace")}
        )
        fixtures: dict[str, object] = {
            "/health": {
                "ok": True,
                "counts": {"memories": 5, "conversations": 2, "messages": 8, "embeddings": 4, "open_conflicts": 0},
                "providers": health_providers,
            },
            "/v1/metrics": {"metrics": {"captures": 4, "saved": 5}},
            "/v1/models/status": {},
            "/v1/monitoring": {"series": []},
            "/v1/status": {"counts": {"memories": 5}},
            "/v1/memory-layers": {
                "ok": available,
                "layers": {
                    "openmemory": {"name": "OpenMemory"},
                    "graphiti": {"name": "Graphiti"},
                    "mempalace": {"name": "MemPalace"},
                },
                "status": provider_status,
            },
        }
        if path in fixtures:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(fixtures[path], ensure_ascii=False),
            )
        elif path.startswith("/v1/") or path == "/health":
            unexpected_api.append(f"{route.request.method} {path}")
            route.fulfill(status=500, content_type="application/json", body='{"error":"unmocked test API"}')
        else:
            route.continue_()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.add_init_script(
            "localStorage.setItem('link-memory-api', 'http://127.0.0.1:18766');"
        )
        page.route("http://127.0.0.1:18766/**", mock_local_api)
        for availability in ("healthy", "partial"):
            state["availability"] = availability
            for route_name, heading in (
                ("overview", ROUTES["overview"]),
                ("layers", ROUTES["layers"]),
            ):
                page.goto(f"{base_url}#{route_name}", wait_until="networkidle", timeout=60_000)
                expect(page.locator("main")).to_be_visible()
                expect(page.get_by_role("heading", name=heading, exact=True).first).to_be_visible()
                rendered_text = page.locator("body").inner_text().casefold()
                leaked = [name for name in providers if name.casefold() in rendered_text]
                assert not leaked, f"{availability} {route_name} leaked provider names: {leaked}"
                results[f"{availability}_{route_name}"] = "passed"

        state["availability"] = "unknown"
        page.goto(f"{base_url}#overview", wait_until="networkidle", timeout=60_000)
        expect(page.locator("main")).to_be_visible()
        expect(page.get_by_role("heading", name=ROUTES["overview"], exact=True).first).to_be_visible()
        status = page.locator(".lp-hero .lp-pill").inner_text().strip()
        assert status != "النظام متصل", f"Unknown provider status was reported as connected: {status!r}"
        assert status == "حالة بعض قدرات الذاكرة غير مؤكدة", f"Unexpected generic unknown status: {status!r}"
        rendered_text = page.locator("body").inner_text().casefold()
        leaked = [name for name in providers if name.casefold() in rendered_text]
        assert not leaked, f"unknown overview leaked provider names: {leaked}"
        results["unknown_overview"] = "passed"

        browser.close()

    assert not unexpected_api, f"Unexpected API requests escaped the fixtures: {unexpected_api}"
    return results


def assert_api_origin_guard(base_url: str) -> dict[str, str]:
    """Verify poisoned API origins and redirects cannot receive the session key."""
    attacker_requests: list[str] = []
    receiver_requests: list[str] = []
    local_requests: list[dict[str, str]] = []
    redirect_health = {"enabled": False}

    def mock_local_api(route) -> None:
        request = route.request
        local_requests.append({
            "url": request.url,
            "authorization": request.headers.get("authorization", ""),
        })
        if redirect_health["enabled"] and request.url.endswith("/health"):
            route.fulfill(
                status=307,
                headers={"Location": "https://receiver.example/collect"},
                body="",
            )
            return
        route.fulfill(status=200, content_type="application/json", body='{"ok":true}')

    def record_attacker(route) -> None:
        attacker_requests.append(route.request.url)
        route.abort()

    def record_receiver(route) -> None:
        receiver_requests.append(route.request.url)
        route.abort()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(6_000)
        page.add_init_script(
            "localStorage.setItem('link-memory-api', 'https://attacker.example');"
            "sessionStorage.setItem('link-memory-api-key', 'synthetic-session-canary');"
        )
        page.route("https://attacker.example/**", record_attacker)
        page.route("https://receiver.example/**", record_receiver)
        page.route("http://127.0.0.1:18766/**", mock_local_api)
        page.goto(f"{base_url}#settings", wait_until="networkidle", timeout=60_000)
        expect(page.locator("main")).to_be_visible()
        page.wait_for_timeout(250)
        assert not attacker_requests, f"Untrusted origin received API requests: {attacker_requests}"

        page.get_by_text("خيارات اتصال متقدمة", exact=True).click()
        page.get_by_label("عنوان الخدمة").fill("http://127.0.0.1:18766")
        page.get_by_role("button", name="حفظ وفحص الاتصال", exact=True).click()
        expect(page.get_by_text("Gateway يستجيب. لم نتحقق من اتصال Codex أو Claude Code.", exact=True)).to_be_visible(timeout=10_000)
        assert local_requests, "Trusted local Gateway received no request"
        assert all(item["authorization"] == "Bearer synthetic-session-canary" for item in local_requests), local_requests

        redirect_health["enabled"] = True
        page.get_by_role("button", name="حفظ وفحص الاتصال", exact=True).click()
        page.wait_for_timeout(250)
        assert not receiver_requests, f"Redirect receiver received a request: {receiver_requests}"
        browser.close()

    return {
        "untrusted_origin_blocked": "passed",
        "local_gateway_allowed": "passed",
        "redirect_not_followed": "passed",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--settings-consent-only",
        action="store_true",
        help="Exercise settings and consent with synthetic API responses only.",
    )
    parser.add_argument(
        "--customer-provider-name-regression",
        action="store_true",
        help="Check customer-facing Overview and Layers for internal provider names using synthetic API responses.",
    )
    parser.add_argument(
        "--api-origin-security-only",
        action="store_true",
        help="Verify the browser refuses untrusted API origins and does not follow redirects.",
    )
    args = parser.parse_args()
    if args.api_origin_security_only:
        results = assert_api_origin_guard(BASE_URL)
        print(json.dumps({"ok": True, "api_origin_security": results}, ensure_ascii=False, indent=2))
        return
    if args.customer_provider_name_regression:
        results = assert_customer_routes_hide_provider_names(BASE_URL)
        print(json.dumps({"ok": True, "customer_provider_name_regression": results}, ensure_ascii=False, indent=2))
        return
    settings_consent_only = args.settings_consent_only
    report: dict[str, object] = {"routes": {}, "actions": {}, "errors": []}
    with tempfile.TemporaryDirectory(prefix="link-memory-webapp-") as temp_dir:
        screenshots = Path(temp_dir)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            for viewport_name, viewport in VIEWPORTS.items():
                page = browser.new_page(viewport=viewport)
                console_errors: list[str] = []
                page_errors: list[str] = []
                failed_requests: list[str] = []
                bad_responses: list[str] = []
                intentional_catalog_failure = {"active": False}
                page.add_init_script(
                    """Object.defineProperty(navigator, 'clipboard', {
                      configurable: true,
                      value: {
                        writeText: async text => { window.__linkPremiumCopiedText = text; },
                        readText: async () => window.__linkPremiumCopiedText || ''
                      }
                    });"""
                )
                if settings_consent_only:
                    page.route(
                        "**/health",
                        lambda route: route.fulfill(
                            status=200,
                            content_type="application/json",
                            body=json.dumps({"ok": True}),
                        ),
                    )
                    for path, payload in (
                        ("**/v1/analysis/status", {"paused": False}),
                        ("**/v1/models/status", {}),
                        ("**/v1/monitoring", {"series": []}),
                    ):
                        page.route(path, json_response(payload))
                page.route(
                    "**/v1/mcp/status",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(mcp_status_fixture(), ensure_ascii=False),
                    ),
                )
                page.route(
                    "**/v1/hooks",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps({"hooks": {
                            "codex": {"enabled": True, "events": 0, "last_seen": None},
                            "claude_code": {"enabled": True, "events": 0, "last_seen": None},
                            "hermes_agent": {"enabled": True, "events": 0, "last_seen": None},
                        }}),
                    ),
                )
                page.route(
                    "**/v1/openrouter/models*",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps({"models": []}),
                    ),
                )
                consent_saves: list[dict[str, object]] = []
                provider_config_saves: list[dict[str, object]] = []
                page.route(
                    "**/v1/openrouter/status",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps({
                            "configured": True,
                            "key_configured": True,
                            "model": "test/free",
                            "history_analysis_backend": "openrouter",
                            "external_ingest_consent": False,
                            "free_only": True,
                        }),
                    ),
                )
                page.route(
                    "**/v1/privacy/external-ingest-consent",
                    lambda route: (
                        consent_saves.append(json.loads(route.request.post_data or "{}")),
                        route.fulfill(
                            status=200,
                            content_type="application/json",
                            body=json.dumps({
                                "external_ingest_consent": json.loads(route.request.post_data or "{}").get("external_ingest_consent") is True,
                            }),
                        ),
                    ),
                )
                page.route(
                    "**/v1/openrouter/config",
                    lambda route: (
                        provider_config_saves.append(json.loads(route.request.post_data or "{}")),
                        route.fulfill(
                            status=200,
                            content_type="application/json",
                            body=json.dumps({"configured": True}),
                        ),
                    ),
                )
                page.on(
                    "console",
                    lambda message, errors=console_errors: errors.append(f"{message.text} @ {message.location}")
                    if message.type == "error" and not (
                        intentional_catalog_failure["active"]
                        and "503" in message.text
                        and "/v1/openrouter/models" in str(message.location.get("url", ""))
                    )
                    else None,
                )
                page.on("pageerror", lambda error, errors=page_errors: errors.append(str(error)))
                page.on(
                    "requestfailed",
                    lambda request, errors=failed_requests: errors.append(
                        f"{request.method} {request.url}: {request.failure}"
                    ),
                )
                page.on(
                    "response",
                    lambda response, errors=bad_responses: errors.append(
                        f"{response.status} {response.url}"
                    )
                    if response.status >= 400 and not (
                        intentional_catalog_failure["active"]
                        and response.status == 503
                        and "/v1/openrouter/models" in response.url
                    )
                    else None,
                )

                viewport_report = {}
                route_cases = {"settings": ROUTES["settings"]} if settings_consent_only else ROUTES
                for route, expected_heading in route_cases.items():
                    page.goto(f"{BASE_URL}#{route}", wait_until="networkidle", timeout=60_000)
                    expect(page.locator("main")).to_be_visible()
                    expect(
                        page.get_by_role("heading", name=expected_heading, exact=True).first
                    ).to_be_visible()
                    assert page.locator("html").get_attribute("lang") == "ar"
                    assert page.locator("html").get_attribute("dir") == "rtl"
                    assert page.evaluate("document.documentElement.scrollWidth") <= viewport["width"] + 1
                    font_family = page.locator("body").evaluate(
                        "element => getComputedStyle(element).fontFamily"
                    )
                    # The public candidate does not bundle the separately licensed
                    # IBM Plex font files. Keep the supported Arabic/system fallback
                    # stack available instead of requiring that font at runtime.
                    assert "Noto Sans Arabic" in font_family, f"Missing Arabic fallback: {font_family}"
                    assert "Segoe UI" in font_family, f"Missing system fallback: {font_family}"
                    assert_accessible_controls(page)
                    page.screenshot(
                        path=str(screenshots / f"{viewport_name}-{route}.png"),
                        full_page=True,
                    )
                    viewport_report[route] = {
                        "heading": expected_heading,
                        "width": page.evaluate("document.documentElement.scrollWidth"),
                        "font": font_family,
                    }
                report["routes"][viewport_name] = viewport_report

                if viewport_name == "desktop" and settings_consent_only:
                    expect(page.locator(".lp-sidebar")).to_be_visible()
                    consent_label_ar = "أوافق على تحليل الالتقاط المباشر عبر OpenRouter"
                    consent_label_en = "Allow direct capture analysis through OpenRouter"
                    consent_checkbox = page.get_by_role("checkbox", name=consent_label_ar)
                    expect(consent_checkbox).to_be_visible()
                    expect(consent_checkbox).not_to_be_checked()
                    expect(page.get_by_text(
                        "هذا الخيار يتحكم بتحليل الالتقاط المباشر عبر OpenRouter فقط. لا يوقف الإرسال إلى خدمات التخزين أو التضمين أو إعادة الترتيب المفعّلة؛ راجع إعداداتها قبل إرسال بيانات خاصة.",
                        exact=True,
                    )).to_be_visible()
                    visible_button(page, "English").click()
                    expect(page.locator("html")).to_have_attribute("lang", "en")
                    expect(page.locator("html")).to_have_attribute("dir", "ltr")
                    consent_checkbox_en = page.get_by_role("checkbox", name=consent_label_en)
                    expect(consent_checkbox_en).to_be_visible()
                    expect(page.get_by_text(
                        "This setting controls only direct capture analysis through OpenRouter. It does not stop enabled storage, embedding, or reranking services from receiving data; review their settings before sending sensitive content.",
                        exact=True,
                    )).to_be_visible()
                    visible_button(page, "العربية").click()
                    expect(page.locator("html")).to_have_attribute("lang", "ar")
                    consent_checkbox = page.get_by_role("checkbox", name=consent_label_ar)
                    consent_checkbox.check()
                    page.get_by_text("خيارات اتصال متقدمة", exact=True).click()
                    expect(page.get_by_text(
                        "لا تغيّر العنوان إلا لخدمة تثق بها؛ تُرسل إليه الطلبات ومفتاح الجلسة.",
                        exact=True,
                    )).to_be_visible()
                    visible_button(page, "حفظ وفحص الاتصال").click()
                    expect(consent_checkbox).to_be_checked()
                    expect(visible_button(page, "حفظ الموافقة")).to_be_enabled()
                    report["actions"]["same_gateway_refresh_preserves_consent_draft"] = "passed"
                    visible_button(page, "حفظ الموافقة").click()
                    expect(page.get_by_text("تم حفظ إعداد الموافقة والتحقق منه.", exact=True)).to_be_visible()
                    assert consent_saves and consent_saves[-1]["external_ingest_consent"] is True
                    assert provider_config_saves == [], "consent must save without configuring a model provider"
                    report["actions"]["external_capture_consent_ar_en"] = "passed"
                    api_key = page.get_by_label("API Key")
                    api_key.fill("synthetic-openrouter-key")
                    visible_button(page, "حفظ الإعداد").click()
                    expect(page.get_by_text("تم حفظ OpenRouter وإخفاء المفتاح.", exact=True)).to_be_visible()
                    assert provider_config_saves and "external_ingest_consent" not in provider_config_saves[-1]
                    assert api_key.evaluate("element => element.value") == "", "saved provider key must be cleared from the field"
                    report["actions"]["provider_save_copy_and_key_clear"] = "passed"
                    consent_checkbox.uncheck()
                    page.unroute("**/v1/openrouter/status")

                    def status_by_gateway(route):
                        if route.request.url.startswith("http://127.0.0.1:18001"):
                            payload = {"configured": True, "model": "legacy/model", "history_analysis_backend": "openrouter"}
                        else:
                            payload = {"configured": True, "model": "test/free", "history_analysis_backend": "openrouter", "external_ingest_consent": True}
                        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

                    page.route("**/v1/openrouter/status", status_by_gateway)
                    page.get_by_label("عنوان الخدمة").fill("http://127.0.0.1:18001")
                    visible_button(page, "حفظ وفحص الاتصال").click()
                    expect(consent_checkbox).to_be_disabled()
                    expect(consent_checkbox).not_to_be_checked()
                    expect(page.get_by_text(
                        "تغيّر Gateway؛ لم ننقل خيار الموافقة غير المحفوظ. راجع الإعداد الجديد بعد التحقق منه.",
                        exact=True,
                    )).to_be_visible()
                    expect(page.get_by_text(
                        "تعذر التحقق من إعداد الموافقة في هذه النسخة من Gateway؛ لن نغيّره حتى يتاح التحقق منه.",
                        exact=True,
                    )).to_be_visible()
                    assert len(consent_saves) == 1, "changing Gateway must not save an old consent draft"
                    report["actions"]["gateway_switch_discards_consent_draft"] = "passed"
                if viewport_name == "desktop" and not settings_consent_only:
                    expect(page.locator(".lp-sidebar")).to_be_visible()
                    assert page.locator(".lp-bottom-nav").count() == 0
                    page.goto(f"{BASE_URL}#overview", wait_until="networkidle", timeout=60_000)
                    visible_button(page, "البحث والاسترجاع").click()
                    expect(page).to_have_url(f"{BASE_URL}#recall")
                    visible_button(page, "English").click()
                    expect(page.locator("html")).to_have_attribute("lang", "en")
                    expect(page.locator("html")).to_have_attribute("dir", "ltr")
                    expect(page.get_by_role("heading", name="Ask the memory directly")).to_be_visible()
                    visible_button(page, "العربية").click()
                    expect(page.locator("html")).to_have_attribute("lang", "ar")

                    search = page.get_by_placeholder("ماذا تريد أن تتذكر؟")
                    search.fill("تفضيلات الإجابات")
                    search_button = visible_button(page, "بحث تفاعلي")
                    search_button.click()
                    expect(search_button).to_be_enabled(timeout=60_000)
                    expect(page.get_by_role("heading", name="نتائج البحث", exact=True)).to_be_visible(timeout=60_000)
                    assert page.locator(".lp-alert-bad").count() == 0
                    report["actions"]["interactive_recall"] = "passed"

                    page.goto(f"{BASE_URL}#operations", wait_until="networkidle", timeout=60_000)
                    health_button = visible_button(page, "تشغيل الفحص")
                    health_button.click()
                    expect(
                        page.get_by_text("اكتمل الفحص؛ النتائج ظاهرة أدناه.", exact=True)
                    ).to_be_visible(timeout=90_000)
                    expect(page.locator(".lp-health-results")).to_be_visible()
                    assert page.locator(".lp-health-results").inner_text().strip()
                    report["actions"]["health_check_rendered"] = "passed"

                    page.goto(f"{BASE_URL}#settings", wait_until="networkidle", timeout=60_000)
                    expect(page.get_by_text(
                        "هذا الإعداد يحدد هل يقبل Gateway محاولات الالتقاط من المصدر. لا يعني أن التطبيق متصل أو أن hook مسجّل أو يعمل؛ العداد يعرض المحاولات التي وصلت إلى Gateway فقط.",
                        exact=True,
                    )).to_be_visible()
                    expect(page.get_by_text("السماح بالاستقبال مفعّل", exact=False).first).to_be_visible()
                    visible_button(page, "English").click()
                    expect(page.get_by_text(
                        "This setting controls whether the Gateway accepts capture attempts from this source. It does not confirm that the app is connected or a hook is installed or running; the count shows attempts that reached the Gateway only.",
                        exact=True,
                    )).to_be_visible()
                    expect(page.get_by_text("Gateway intake allowed", exact=False).first).to_be_visible()
                    visible_button(page, "العربية").click()
                    consent_checkbox = page.get_by_role("checkbox", name="أوافق على تحليل الالتقاط المباشر عبر OpenRouter")
                    expect(consent_checkbox).to_be_visible()
                    expect(consent_checkbox).not_to_be_checked()
                    consent_checkbox.check()
                    visible_button(page, "حفظ الموافقة").click()
                    expect(page.get_by_text("تم حفظ إعداد الموافقة والتحقق منه.", exact=True)).to_be_visible()
                    assert consent_saves and consent_saves[-1]["external_ingest_consent"] is True
                    assert provider_config_saves == [], "consent must save without configuring a model provider"
                    report["actions"]["external_capture_consent"] = "passed"
                    visible_button(page, "حفظ الإعداد").click()
                    expect(page.get_by_text("تم حفظ OpenRouter وإخفاء المفتاح.", exact=True)).to_be_visible()
                    assert provider_config_saves and "external_ingest_consent" not in provider_config_saves[-1]
                    report["actions"]["provider_settings_separate_from_consent"] = "passed"
                    client_select = page.get_by_label("التطبيق المطلوب ربطه")
                    client_select.select_option("codex")
                    visible_button(page, "نسخ إعداد التطبيق").click()
                    expect(page.get_by_text("تم نسخ إعداد Codex بصيغة TOML. هذا لا يعني أن التطبيق متصل.", exact=True)).to_be_visible()
                    copied = page.evaluate("window.__linkPremiumCopiedText")
                    parsed = tomllib.loads(copied)
                    entry = parsed["mcp_servers"]["link-memory-memory"]
                    assert entry["command"].lower().endswith("python.exe")
                    assert entry["args"][0].lower().endswith("mcp_server.py")
                    with page.expect_download() as download_info:
                        visible_button(page, "تنزيل مقطع TOML").click()
                    download = download_info.value
                    assert download.suggested_filename == "link-memory-mcp-snippet.toml"
                    downloaded = Path(download.path()).read_text(encoding="utf-8")
                    assert tomllib.loads(downloaded) == parsed
                    report["actions"]["codex_mcp_copy_and_download"] = "passed"

                    client_select.select_option("claude_code")
                    visible_button(page, "نسخ إعداد التطبيق").click()
                    expect(page.get_by_text("تم نسخ إعداد Claude Code بصيغة JSON. هذا لا يعني أن التطبيق متصل.", exact=True)).to_be_visible()
                    copied = page.evaluate("window.__linkPremiumCopiedText")
                    parsed = json.loads(copied)
                    entry = parsed["mcpServers"]["link-memory-memory"]
                    assert entry["command"].lower().endswith("python.exe")
                    assert entry["args"][0].lower().endswith("mcp_server.py")
                    assert "cwd" not in entry
                    with page.expect_download() as download_info:
                        visible_button(page, "تنزيل link-memory.mcp.json").click()
                    download = download_info.value
                    assert download.suggested_filename == "link-memory.mcp.json", download.suggested_filename
                    downloaded = Path(download.path()).read_text(encoding="utf-8")
                    assert json.loads(downloaded) == parsed
                    report["actions"]["claude_code_mcp_copy_and_download"] = "passed"

                    page.unroute("**/v1/mcp/status")
                    page.route(
                        "**/v1/mcp/status",
                        lambda route: route.fulfill(
                            status=200,
                            content_type="application/json",
                            body=json.dumps(mcp_status_fixture(include_availability=False), ensure_ascii=False),
                        ),
                    )
                    page.reload(wait_until="networkidle")
                    expect(page.get_by_text("حدّث Gateway", exact=True)).to_be_visible()
                    assert visible_button(page, "نسخ إعداد التطبيق").is_disabled()
                    report["actions"]["legacy_gateway_fails_closed"] = "passed"

                    page.unroute("**/v1/openrouter/status")
                    page.route(
                        "**/v1/openrouter/status",
                        lambda route: route.fulfill(
                            status=200,
                            content_type="application/json",
                            body=json.dumps({"configured": False, "model": "", "history_analysis_backend": "ollama"}),
                        ),
                    )
                    page.reload(wait_until="networkidle")
                    unknown_consent = page.get_by_role("checkbox", name="أوافق على تحليل الالتقاط المباشر عبر OpenRouter")
                    expect(unknown_consent).to_be_disabled()
                    expect(page.get_by_text("تعذر التحقق من إعداد الموافقة في هذه النسخة من Gateway؛ لن نغيّره حتى يتاح التحقق منه.", exact=True)).to_be_visible()
                    report["actions"]["legacy_consent_fails_closed"] = "passed"

                    page.unroute("**/v1/openrouter/status")
                    page.route(
                        "**/v1/openrouter/status",
                        lambda route: route.fulfill(
                            status=200,
                            content_type="application/json",
                            body=json.dumps({"configured": False, "model": "", "history_analysis_backend": "ollama", "external_ingest_consent": False}),
                        ),
                    )
                    page.unroute("**/v1/openrouter/models*")
                    page.route(
                        "**/v1/openrouter/models*",
                        lambda route: route.fulfill(
                            status=503,
                            content_type="application/json",
                            body=json.dumps({"error": "catalog unavailable"}),
                        ),
                    )
                    intentional_catalog_failure["active"] = True
                    page.reload(wait_until="networkidle")
                    failed_catalog_consent = page.get_by_role("checkbox", name="أوافق على تحليل الالتقاط المباشر عبر OpenRouter")
                    expect(failed_catalog_consent).to_be_enabled()
                    expect(failed_catalog_consent).not_to_be_checked()
                    expect(page.get_by_text("تعذر تحميل قائمة النماذج. أعد المحاولة؛ هذا لا يغيّر إعداد الموافقة.", exact=True)).to_be_visible()
                    failed_catalog_consent.check()
                    visible_button(page, "حفظ الموافقة").click()
                    expect(page.get_by_text("تم حفظ إعداد الموافقة والتحقق منه.", exact=True)).to_be_visible()
                    assert consent_saves[-1]["external_ingest_consent"] is True
                    report["actions"]["consent_independent_of_catalog_failure"] = "passed"
                    bad_responses[:] = [entry for entry in bad_responses if "/v1/openrouter/models" not in entry]

                    saved_counts = (len(consent_saves), len(provider_config_saves))
                    page.unroute("**/v1/openrouter/status")

                    def status_by_gateway(route):
                        if route.request.url.startswith("http://127.0.0.1:18001"):
                            payload = {"configured": True, "model": "legacy/model", "history_analysis_backend": "openrouter"}
                        else:
                            payload = {"configured": True, "model": "test/free", "history_analysis_backend": "openrouter", "external_ingest_consent": False}
                        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

                    page.route("**/v1/openrouter/status", status_by_gateway)
                    page.route(
                        "**/health",
                        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True})),
                    )
                    page.reload(wait_until="networkidle")
                    switched_gateway_consent = page.get_by_role("checkbox", name="أوافق على تحليل الالتقاط المباشر عبر OpenRouter")
                    expect(switched_gateway_consent).to_be_enabled()
                    switched_gateway_consent.check()
                    advanced = page.get_by_text("خيارات اتصال متقدمة", exact=True)
                    advanced.click()
                    page.get_by_label("عنوان الخدمة").fill("http://127.0.0.1:18001")
                    visible_button(page, "حفظ وفحص الاتصال").click()
                    expect(page.get_by_role("checkbox", name="أوافق على تحليل الالتقاط المباشر عبر OpenRouter")).to_be_disabled()
                    expect(switched_gateway_consent).not_to_be_checked()
                    expect(page.get_by_text("تغيّر Gateway؛ لم ننقل خيار الموافقة غير المحفوظ. راجع الإعداد الجديد بعد التحقق منه.", exact=True)).to_be_visible()
                    expect(page.get_by_text("تعذر التحقق من إعداد الموافقة في هذه النسخة من Gateway؛ لن نغيّره حتى يتاح التحقق منه.", exact=True)).to_be_visible()
                    assert visible_button(page, "حفظ الإعداد").is_disabled(), "OpenRouter configuration must fail closed on an incompatible Gateway"
                    assert (len(consent_saves), len(provider_config_saves)) == saved_counts, "switching Gateway must not submit provider or consent changes"
                    report["actions"]["gateway_switch_revalidates_consent_capability"] = "passed"

                page.close()
                report["errors"].extend(console_errors + page_errors + failed_requests + bad_responses)

            browser.close()

    assert not report["errors"], json.dumps(report["errors"], ensure_ascii=False, indent=2)
    report["ok"] = True
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
