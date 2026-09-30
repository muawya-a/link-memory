import { useEffect, useRef, useState } from "react";
import { Activity, CheckCircle2, Download, ListChecks, Pause, Play, RefreshCw, Settings2, ShieldCheck } from "lucide-react";
import { api, apiBase, post, setApiBase } from "../../api";
import { t, n, arr, rec, formatTime, Button, Card, Pill, Lang, R } from "../shared";

type ProviderKey =
  | "openrouter"
  | "openai"
  | "anthropic"
  | "google"
  | "deepseek"
  | "xai"
  | "local";
type ModelOption = { id: string; name: string; role?: string; free?: boolean };
const PROVIDERS: { id: ProviderKey; name: string; english: string }[] = [
  { id: "openrouter", name: "OpenRouter", english: "OpenRouter" },
  { id: "openai", name: "OpenAI", english: "OpenAI" },
  {
    id: "anthropic",
    name: "Claude · Anthropic",
    english: "Claude · Anthropic",
  },
  { id: "google", name: "Gemini · Google", english: "Gemini · Google" },
  { id: "deepseek", name: "DeepSeek", english: "DeepSeek" },
  { id: "xai", name: "Grok · xAI", english: "Grok · xAI" },
  { id: "local", name: "محلي · Ollama", english: "Local · Ollama" },
];


export function Settings({ language }: { language: Lang }) {
  const [gateway, setGateway] = useState(apiBase());
  const [gatewayConnected, setGatewayConnected] = useState<boolean | null>(null);
  const [gatewayBusy, setGatewayBusy] = useState(false);
  const [gatewayNotice, setGatewayNotice] = useState("");
  const [models, setModels] = useState<R[]>([]);
  const [providerModels, setProviderModels] = useState<Record<string, ModelOption[]>>({});
  const [runtime, setRuntime] = useState<R>({});
  const [provider, setProvider] = useState<ProviderKey>(() => {
    const saved = localStorage.getItem("link-memory-model-provider") as ProviderKey | null;
    return saved && PROVIDERS.some((item) => item.id === saved) ? saved : "openrouter";
  });
  const [selected, setSelected] = useState("");
  const [key, setKey] = useState("");
  const [externalIngestConsent, setExternalIngestConsent] = useState(false);
  const [savedExternalIngestConsent, setSavedExternalIngestConsent] = useState(false);
  const [externalIngestConsentApiState, setExternalIngestConsentApiState] = useState<"loading" | "ready" | "unsupported" | "unavailable">("loading");
  const [externalIngestConsentBusy, setExternalIngestConsentBusy] = useState(false);
  const [externalIngestConsentNotice, setExternalIngestConsentNotice] = useState("");
  const [catalogNotice, setCatalogNotice] = useState("");
  const [paused, setPaused] = useState(false);
  const [notice, setNotice] = useState("");
  const [mcp, setMcp] = useState<R>({});
  const [mcpClient, setMcpClient] = useState<"codex" | "claude_code">("codex");
  const [mcpNotice, setMcpNotice] = useState("");
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [hooks, setHooks] = useState<R>({});
  const [hooksLoaded, setHooksLoaded] = useState(false);
  const [monitoringApiReady, setMonitoringApiReady] = useState(false);
  const [hookBusy, setHookBusy] = useState("");
  const [connectionTest, setConnectionTest] = useState<R>({});
  const [connectionBusy, setConnectionBusy] = useState(false);
  const consentStatusRequest = useRef(0);
  const checkGateway = async () => {
    setGatewayBusy(true);
    setGatewayConnected(null);
    setGatewayNotice("");
    try {
      await api("/health");
      setGatewayConnected(true);
      setGatewayNotice(t(language, "Gateway يستجيب. لم نتحقق من اتصال Codex أو Claude Code.", "The Gateway responded. Codex and Claude Code connections are not verified."));
    } catch (error) {
      setGatewayConnected(false);
      setGatewayNotice(error instanceof Error ? error.message : t(language, "تعذر الاتصال بـGateway.", "Could not connect to the Gateway."));
    } finally {
      setGatewayBusy(false);
    }
  };
  const refreshOpenrouterStatus = async ({ preserveDraft = true }: { preserveDraft?: boolean } = {}) => {
    const requestId = ++consentStatusRequest.current;
    const consentDraftWasDirty = externalIngestConsent !== savedExternalIngestConsent;
    setExternalIngestConsentApiState("loading");
    try {
      const status = rec(await api("/v1/openrouter/status"));
      if (requestId !== consentStatusRequest.current) return;
      const consentSupported = typeof status.external_ingest_consent === "boolean";
      setExternalIngestConsentApiState(consentSupported ? "ready" : "unsupported");
      const savedConsent = status.external_ingest_consent === true;
      if (!preserveDraft || !consentDraftWasDirty) setExternalIngestConsent(savedConsent);
      setSavedExternalIngestConsent(savedConsent);
      setSelected(String(status.model || ""));
      const savedProvider = localStorage.getItem("link-memory-model-provider") as ProviderKey | null;
      const backendIsOpenRouter = status.history_analysis_backend === "openrouter";
      setProvider(
        backendIsOpenRouter
          ? "openrouter"
          : savedProvider && PROVIDERS.some((item) => item.id === savedProvider)
            ? savedProvider
            : "local",
      );
      const savedModel = localStorage.getItem("link-memory-model-selection");
      if (savedModel && !backendIsOpenRouter) setSelected(savedModel);
    } catch {
      if (requestId !== consentStatusRequest.current) return;
      setExternalIngestConsentApiState("unavailable");
      if (!preserveDraft) {
        setExternalIngestConsent(false);
        setSavedExternalIngestConsent(false);
      }
    }
  };
  const saveGateway = async () => {
    const nextGateway = gateway.trim();
    const gatewayChanged = nextGateway.replace(/\/+$/, "") !== apiBase().trim().replace(/\/+$/, "");
    const consentDraftWasDirty = externalIngestConsent !== savedExternalIngestConsent;
    try {
      setApiBase(nextGateway);
    } catch {
      setGatewayConnected(false);
      setGatewayNotice(t(language, "عنوان الخدمة غير مسموح. استخدم هذا الموقع أو عنوانًا محليًا مثل localhost.", "Service address is not allowed. Use this site or a local address such as localhost."));
      return;
    }
    setExternalIngestConsentNotice(
      gatewayChanged && consentDraftWasDirty
        ? t(language, "تغيّر Gateway؛ لم ننقل خيار الموافقة غير المحفوظ. راجع الإعداد الجديد بعد التحقق منه.", "Gateway changed; the unsaved consent choice was not carried over. Review the new setting after it is verified.")
        : "",
    );
    await Promise.all([checkGateway(), refreshOpenrouterStatus({ preserveDraft: !gatewayChanged })]);
  };
  useEffect(() => {
    void checkGateway();
  }, []);
  useEffect(() => {
    void refreshOpenrouterStatus();
    return () => {
      consentStatusRequest.current += 1;
    };
  }, []);
  useEffect(() => {
    let active = true;
    void api("/v1/mcp/status")
      .then((status) => {
        if (active) setMcp(rec(status));
      })
      .catch(() => {
        if (active) setMcp({});
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    void Promise.allSettled([
      api("/v1/openrouter/models?refresh=0"),
      api("/v1/analysis/status"),
      api("/v1/models/status"),
      api("/v1/hooks").catch(() => ({})),
      api("/v1/monitoring").catch(() => ({})),
    ]).then(([catalogResult, analysisResult, runtimeResult, hooksResult, monitoringResult]) => {
      if (!active) return;
      if (catalogResult.status === "fulfilled") {
        setModels(arr(rec(catalogResult.value).models));
        setCatalogNotice("");
      } else {
        setModels([]);
        setCatalogNotice(t(language, "تعذر تحميل قائمة النماذج. أعد المحاولة؛ هذا لا يغيّر إعداد الموافقة.", "Could not load the model catalog. Retry when available; this does not change consent."));
      }
      if (analysisResult.status === "fulfilled") setPaused(Boolean(rec(analysisResult.value).paused));
      if (runtimeResult.status === "fulfilled") setRuntime(rec(runtimeResult.value));
      if (hooksResult.status === "fulfilled") {
        const hookState = rec(hooksResult.value).hooks || {};
        setHooks(hookState);
        setHooksLoaded(Object.keys(rec(hookState)).length > 0);
      }
      if (monitoringResult.status === "fulfilled") {
        setMonitoringApiReady(Array.isArray(rec(monitoringResult.value).series));
      }
    }).catch(() => {
      if (active) setNotice(t(language, "تعذر تحميل بعض الإعدادات. أعد فحص الاتصال بالخدمة.", "Some settings could not be loaded. Check the service connection and retry."));
    });
    return () => {
      active = false;
    };
  }, []);
  const saveExternalIngestConsent = async () => {
    setExternalIngestConsentBusy(true);
    setExternalIngestConsentNotice("");
    try {
      const saved = rec(await post("/v1/privacy/external-ingest-consent", {
        external_ingest_consent: externalIngestConsent,
      }));
      if (saved.external_ingest_consent !== externalIngestConsent) {
        throw new Error(t(language, "لم نتمكن من التحقق من حفظ إعداد الموافقة.", "Could not verify the saved consent setting."));
      }
      setSavedExternalIngestConsent(externalIngestConsent);
      setExternalIngestConsentNotice(t(language, "تم حفظ إعداد الموافقة والتحقق منه.", "Consent setting saved and verified."));
    } catch {
      setExternalIngestConsentNotice(t(language, "تعذر حفظ إعداد الموافقة والتحقق منه. أعد المحاولة؛ لن نعرضه كمحفوظ.", "Could not save and verify the consent setting. Retry; it will not be shown as saved."));
    } finally {
      setExternalIngestConsentBusy(false);
    }
  };
  const localModels: ModelOption[] = [
    {
      id: String(rec(runtime.embedding).model || "YOUR_LOCAL_EMBEDDING_MODEL"),
      name: String(rec(runtime.embedding).model || "غير مهيأ · Not configured"),
      role: "Embedding",
    },
    {
      id: String(rec(runtime.reranker).model || "YOUR_LOCAL_RERANKER_MODEL"),
      name: String(rec(runtime.reranker).model || "غير مهيأ · Not configured"),
      role: "Reranker",
    },
  ];
  const openRouterOptions: ModelOption[] = models.map((m) => ({
    id: String(m.id),
    name: String(m.name || m.id),
    free: Boolean(m.free),
  }));
  const activeOpenRouterModel = String(rec(runtime.openrouter).model || selected || "");
  if (activeOpenRouterModel && !openRouterOptions.some((item) => item.id === activeOpenRouterModel)) {
    openRouterOptions.unshift({
      id: activeOpenRouterModel,
      name: `${activeOpenRouterModel} · ${t(language, "مرتبط بالذاكرة", "Memory linked")}`,
      free: true,
    });
  }
  const modelOptions: ModelOption[] =
    provider === "openrouter"
      ? openRouterOptions
      : provider === "local"
        ? localModels
        : providerModels[provider] || [];
  const refreshProviderModels = async (providedKey = key) => {
    setCatalogBusy(true);
    try {
      if (provider === "openrouter") {
        const result = await api("/v1/openrouter/models?refresh=1");
        setModels(arr(rec(result).models));
        setNotice(t(language, "تم تحديث كتالوج OpenRouter من المصدر الرسمي.", "OpenRouter catalog refreshed from the official source."));
      } else if (provider === "local") {
        const result = await api("/v1/models/status");
        setRuntime(rec(result));
        setNotice(t(language, "تم تحديث الموديلات المحلية من الخدمة المحلية.", "Local models refreshed from the local service."));
      } else {
        if (!providedKey.trim()) {
          throw new Error(t(language, "أدخل مفتاح المزود مؤقتًا لتحديث قائمته.", "Enter the provider key temporarily to refresh its catalog."));
        }
        const result = await post("/v1/provider/catalog", { provider, api_key: providedKey.trim() });
        const fresh = arr(rec(result).models).map((item) => ({
          id: String(item.id || ""),
          name: String(item.name || item.id || ""),
        })).filter((item) => item.id);
        setProviderModels((current) => ({ ...current, [provider]: fresh }));
        setSelected((current) => fresh.some((item) => item.id === current) ? current : String(fresh[0]?.id || ""));
        setNotice(t(language, `تم التحقق من ${fresh.length} نموذجًا من المصدر الرسمي.`, `${fresh.length} models verified from the official provider catalog.`));
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : t(language, "تعذر تحديث قائمة النماذج.", "Could not refresh the model catalog.");
      if (provider === "openrouter") setCatalogNotice(message);
      else setNotice(message);
    } finally {
      setKey("");
      setCatalogBusy(false);
    }
  };
  const testProviderConnection = async () => {
    setConnectionBusy(true);
    setConnectionTest({ state: "checking" });
    try {
      if (provider !== "local" && provider !== "openrouter" && !key.trim()) throw new Error(t(language, "أدخل مفتاح المزود مؤقتًا للفحص.", "Enter the provider key temporarily to test it."));
      const result = rec(await post("/v1/provider/test", { provider, ...(key ? { api_key: key.trim() } : {}) }));
      const localServices = arr(result.services).map((item) => `${item.service}: ${item.ok ? "OK" : "offline"}`).join(" · ");
      const catalogDetails = provider === "openrouter"
        ? t(language, "كتالوج OpenRouter استجاب؛ لم يُرسل طلب توليد.", "OpenRouter catalog responded; no inference was sent.")
        : result.model_count ? `${n(result.model_count, language)} ${t(language, "نموذج", "models")}` : localServices;
      setConnectionTest({ state: result.ok ? "ok" : "failed", latency_ms: result.latency_ms, detail: catalogDetails || t(language, "تم فحص نقطة اتصال الكتالوج فقط؛ لم يُشغّل توليدًا.", "Model catalog endpoint checked; no inference was run.") });
    } catch (error) {
      setConnectionTest({ state: "failed", detail: error instanceof Error ? error.message : "Connection failed" });
    } finally {
      setConnectionBusy(false);
      setKey("");
    }
  };
  const toggleHook = async (name: string, enabled: boolean) => {
    setHookBusy(name);
    try {
      const result = rec(await post("/v1/hooks", { hook: name, enabled }));
      setHooks(rec(result.hooks));
      setHooksLoaded(true);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : t(language, "تعذر تحديث الهوك.", "Could not update hook."));
    } finally {
      setHookBusy("");
    }
  };
  const selectedProvider = PROVIDERS.find((item) => item.id === provider);
  const mcpStatus = rec(mcp);
  const mcpAvailable = typeof mcpStatus.mcp_available === "boolean"
    ? mcpStatus.mcp_available
    : null;
  const selectedMcpConfig = rec(rec(mcpStatus.client_configs)[mcpClient]);
  const mcpConfigReady = mcpAvailable === true && typeof selectedMcpConfig.content === "string" && Boolean(selectedMcpConfig.content.trim());
  const freshMcpConfig = async () => {
    const live = rec(await api("/v1/mcp/status"));
    if (live.mcp_available !== true) {
      throw new Error(t(language, "خادم MCP غير متاح الآن. حدّث Gateway ثم أعد المحاولة.", "The MCP server is unavailable. Update the Gateway, then try again."));
    }
    const configs = rec(live.client_configs);
    const config = rec(configs[mcpClient]);
    if (typeof config.content !== "string" || !config.content.trim()) {
      throw new Error(t(language, "إعداد هذا التطبيق غير متاح الآن. حدّث Gateway ثم أعد المحاولة.", "This app's configuration is unavailable. Update the Gateway, then try again."));
    }
    setMcp(live);
    return {
      content: config.content,
      filename: typeof config.filename === "string" && config.filename.trim()
        ? config.filename
        : mcpClient === "codex" ? "link-memory-mcp-snippet.toml" : "link-memory.mcp.json",
      format: mcpClient === "codex" ? "toml" : "json",
    };
  };
  const copyMcpConfig = async () => {
    try {
      const config = await freshMcpConfig();
      await navigator.clipboard.writeText(config.content);
      setMcpNotice(t(language, `تم نسخ إعداد ${mcpClient === "codex" ? "Codex" : "Claude Code"} بصيغة ${config.format.toUpperCase()}. هذا لا يعني أن التطبيق متصل.`, `${mcpClient === "codex" ? "Codex" : "Claude Code"} ${config.format.toUpperCase()} configuration copied. This does not mean the app is connected.`));
    } catch (error) {
      setMcpNotice(error instanceof Error ? error.message : t(language, "تعذر نسخ الإعداد.", "Could not copy the configuration."));
    }
  };
  const downloadMcpConfig = async () => {
    try {
      const config = await freshMcpConfig();
      const mimeType = config.format === "json" ? "application/json;charset=utf-8" : "text/plain;charset=utf-8";
      const href = URL.createObjectURL(new Blob([config.content], { type: mimeType }));
      const link = document.createElement("a");
      link.href = href;
      link.download = config.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(href), 0);
      setMcpNotice(t(language, `تم تنزيل ${config.filename}. هذا لا يعني أن التطبيق متصل.`, `Downloaded ${config.filename}. This does not mean the app is connected.`));
    } catch (error) {
      setMcpNotice(error instanceof Error ? error.message : t(language, "تعذر تنزيل الإعداد.", "Could not download the configuration."));
    }
  };
  return (
    <div className="lp-stack">
      <Card>
        <div className="lp-card-head">
          <div>
            <span className="lp-eyebrow">{t(language, "حالة الخدمة", "SERVICE STATUS")}</span>
            <h2>{t(language, "الاتصال بالخدمة", "Service connection")}</h2>
            <p className="lp-muted">{t(language, "حالة اتصال Link Memory بالخدمة اللازمة لتشغيل الذاكرة.", "Link Memory’s connection to the service that powers your memory.")}</p>
          </div>
          <Pill tone={gatewayConnected === true ? "good" : gatewayConnected === false ? "bad" : "warn"}>
            {gatewayBusy
              ? t(language, "يفحص…", "Checking…")
              : gatewayConnected === true
                ? t(language, "متصل", "Connected")
                : gatewayConnected === false
                  ? t(language, "غير متصل", "Offline")
                  : t(language, "لم يُفحص", "Not checked")}
          </Pill>
        </div>
        <details className="lp-settings-advanced">
          <summary>{t(language, "خيارات اتصال متقدمة", "Advanced connection options")}</summary>
          <p className="lp-muted">{t(language, "لا تغيّر العنوان إلا لخدمة تثق بها؛ تُرسل إليه الطلبات ومفتاح الجلسة.", "Only use an address you trust; requests and your session key are sent to it.")}</p>
          <div className="lp-gateway-settings">
            <label className="lp-form-label">
              {t(language, "عنوان الخدمة", "Service address")}
              <input
                type="url"
                dir="ltr"
                value={gateway}
                onChange={(event) => setGateway(event.target.value)}
                placeholder="http://127.0.0.1:18000"
                aria-label={t(language, "عنوان الخدمة", "Service address")}
              />
            </label>
            <Button onClick={() => void saveGateway()} disabled={gatewayBusy || !gateway.trim()}>
              {gatewayBusy
                ? t(language, "يفحص…", "Checking…")
                : t(language, "حفظ وفحص الاتصال", "Save and check connection")}
            </Button>
          </div>
        </details>
        {gatewayNotice && <p className="lp-muted" role="status" aria-live="polite">{gatewayNotice}</p>}
      </Card>
      <Card>
        <div className="lp-card-head">
          <div>
            <span className="lp-eyebrow">LLMS</span>
            <h2>{t(language, "مزودو النماذج", "Model providers")}</h2>
          </div>
          <Settings2 size={20} />
        </div>
        <div className="lp-provider-grid" aria-label={t(language, "إعداد المزود والنموذج والمفتاح", "Provider, model and key setup")}>
          <div className="lp-provider-field">
            <span className="lp-provider-step">01</span>
            <label className="lp-form-label">
            {t(language, "الشركة", "Provider")}
            <select
              value={provider}
              onChange={(e) => {
                const next = e.target.value as ProviderKey;
                setProvider(next);
                setConnectionTest({});
                setKey("");
                setCatalogNotice("");
                const first =
                  next === "openrouter"
                    ? String(models[0]?.id || "")
                    : next === "local"
                      ? localModels[0]?.id || ""
                      : (providerModels[next]?.[0]?.id || "");
                setSelected(first);
              }}
            >
              {PROVIDERS.map((item) => (
                <option key={item.id} value={item.id}>
                  {t(language, item.name, item.english)}
                </option>
              ))}
            </select>
            </label>
          </div>
          <div className="lp-provider-field">
            <span className="lp-provider-step">02</span>
            <label className="lp-form-label">
            {t(language, "النموذج", "Model")}
            <select
              value={selected}
              disabled={provider !== "local" && provider !== "openrouter" && !modelOptions.length}
              onChange={(e) => setSelected(e.target.value)}
            >
              <option value="">
                {modelOptions.length
                  ? t(language, "اختر نموذجًا", "Choose a model")
                  : t(language, "أدخل المفتاح ثم حدّث القائمة", "Enter the key, then refresh")}
              </option>
              {modelOptions.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                  {m.role ? ` · ${m.role}` : m.free ? " · free" : ""}
                </option>
              ))}
            </select>
            </label>
          </div>
          <div className="lp-provider-field">
            <span className="lp-provider-step">03</span>
            <label className="lp-form-label">
            {t(language, "API Key", "API Key")}
            <input
              type="password"
              disabled={provider === "local"}
              value={key}
              onChange={(e) => {
                setKey(e.target.value);
              }}
              onBlur={(e) => {
                if (provider !== "openrouter" && provider !== "local" && e.currentTarget.value.trim()) {
                  void refreshProviderModels(e.currentTarget.value);
                }
              }}
              placeholder={
                provider === "local"
                  ? t(language, "لا يحتاج مفتاحًا", "No key needed")
                  : "••••••••••••"
              }
              autoComplete="new-password"
            />
            </label>
          </div>
        </div>
        {catalogNotice && <p className="lp-muted" role="status" aria-live="polite">{catalogNotice}</p>}
        <div className="lp-provider-status" role="status">
          <Pill tone={connectionTest.state === "ok" ? "good" : connectionTest.state === "failed" ? "bad" : "warn"}>
            {connectionTest.state === "ok"
              ? t(language, "اجتاز فحص الاتصال", "Connection test passed")
              : connectionTest.state === "failed"
                ? t(language, "فشل فحص الاتصال", "Connection test failed")
                : t(language, "لم يُفحص الاتصال بعد", "Connection not tested")}
          </Pill>
          <span className="lp-muted">
            {selectedProvider
              ? t(language, selectedProvider.name, selectedProvider.english)
              : ""}
          </span>
        </div>
        {provider !== "openrouter" && provider !== "local" && (
          <p className="lp-muted lp-provider-note">
            {t(
              language,
              "عند الفحص أو تحديث القائمة يُرسل المفتاح مؤقتًا إلى Gateway لطلب كتالوج المزود فقط، ولا يُحفظ ولا يُستخدم لتوليد إجابة.",
              "When testing or refreshing models, the key is sent temporarily to the Gateway for the provider catalog only; it is not stored or used for generation.",
            )}
          </p>
        )}
        <div className="lp-local-tools-note lp-provider-consent">
            <label>
              <input
                type="checkbox"
                checked={externalIngestConsent}
                disabled={externalIngestConsentApiState !== "ready"}
                onChange={(event) => setExternalIngestConsent(event.currentTarget.checked)}
              />
              <span>
                <strong>{t(language, "أوافق على تحليل الالتقاط المباشر عبر OpenRouter", "Allow direct capture analysis through OpenRouter")}</strong>
                <small>{t(language, "هذا الخيار يتحكم بتحليل الالتقاط المباشر عبر OpenRouter فقط. لا يوقف الإرسال إلى خدمات التخزين أو التضمين أو إعادة الترتيب المفعّلة؛ راجع إعداداتها قبل إرسال بيانات خاصة.", "This setting controls only direct capture analysis through OpenRouter. It does not stop enabled storage, embedding, or reranking services from receiving data; review their settings before sending sensitive content.")}</small>
              </span>
            </label>
            {externalIngestConsentApiState !== "ready" && (
              <p className="lp-muted" role="status">
                {externalIngestConsentApiState === "loading"
                  ? t(language, "جارٍ التحقق من حالة الموافقة…", "Checking consent status…")
                  : externalIngestConsentApiState === "unsupported"
                    ? t(language, "تعذر التحقق من إعداد الموافقة في هذه النسخة من Gateway؛ لن نغيّره حتى يتاح التحقق منه.", "This Gateway could not verify the consent setting; changes are disabled until it can be verified.")
                    : t(language, "تعذر التحقق من حالة الموافقة. أعد فحص الاتصال قبل تغييرها.", "Could not verify consent status. Check the service connection before changing it.")}
              </p>
            )}
            <Button
              variant="secondary"
              disabled={externalIngestConsentApiState !== "ready" || externalIngestConsentBusy || externalIngestConsent === savedExternalIngestConsent}
              onClick={() => void saveExternalIngestConsent()}
            >
              <CheckCircle2 size={17} />
              {externalIngestConsentBusy
                ? t(language, "يحفظ…", "Saving…")
                : t(language, "حفظ الموافقة", "Save consent")}
            </Button>
            {externalIngestConsentNotice && <p className="lp-muted" role="status" aria-live="polite">{externalIngestConsentNotice}</p>}
        </div>
        <div className="lp-actions lp-provider-actions">
          <Button variant="secondary" disabled={!monitoringApiReady || connectionBusy || (provider !== "local" && provider !== "openrouter" && !key.trim())} onClick={() => void testProviderConnection()}>
            <Activity size={17} className={connectionBusy ? "lp-spin" : ""} />
            {connectionBusy ? t(language, "يفحص الاتصال…", "Testing…") : monitoringApiReady ? t(language, "فحص الاتصال", "Test connection") : t(language, "يتطلب تحديث Gateway", "Gateway update required")}
          </Button>
          <Button
            variant="secondary"
            disabled={catalogBusy}
            onClick={refreshProviderModels}
          >
            <RefreshCw size={17} className={catalogBusy ? "lp-spin" : ""} />
            {catalogBusy
              ? t(language, "جاري التحقق", "Checking")
              : t(language, "تحديث الموديلات", "Refresh models")}
          </Button>
          <Button
            disabled={provider === "openrouter" && externalIngestConsentApiState !== "ready"}
            onClick={async () => {
              try {
              if (provider === "openrouter") {
                await post("/v1/openrouter/config", {
                  model: selected,
                  free_only: true,
                  history_analysis_backend: "openrouter",
                  ...(key ? { api_key: key } : {}),
                });
                setNotice(
                  t(
                    language,
                    "تم حفظ OpenRouter وإخفاء المفتاح.",
                    "OpenRouter saved and key hidden.",
                  ),
                );
                localStorage.setItem("link-memory-model-provider", provider);
                localStorage.setItem("link-memory-model-selection", selected);
              } else if (provider === "local") {
                setNotice(
                  t(
                    language,
                    "المحلي جاهز: Embedding وReranker يعملان، ولا يوجد نموذج محادثة محلي مفعل.",
                    "Local roles ready: Embedding and Reranker are available; no local chat model is enabled.",
                  ),
                );
                localStorage.setItem("link-memory-model-provider", provider);
                localStorage.setItem("link-memory-model-selection", selected);
              } else {
                setNotice(
                  t(
                    language,
                    "تم حفظ الاختيار للواجهة وإخفاء المفتاح؛ ربط هذا المزود بالـGateway لم يُفعّل بعد.",
                    "Selection saved for the UI and key hidden; Gateway routing for this provider is not enabled yet.",
                  ),
                );
                localStorage.setItem("link-memory-model-provider", provider);
                localStorage.setItem("link-memory-model-selection", selected);
              }
              setKey("");
              } catch (error) {
                setNotice(error instanceof Error ? error.message : t(language, "تعذر حفظ الإعداد.", "Could not save settings."));
              }
            }}
          >
            <CheckCircle2 size={17} />
            {t(language, "حفظ الإعداد", "Save settings")}
          </Button>
          <Button
            variant="secondary"
            onClick={async () => {
              const v = !paused;
              await post("/v1/analysis/pause", { paused: v });
              setPaused(v);
            }}
          >
            {paused ? <Play size={17} /> : <Pause size={17} />}
            {paused
              ? t(language, "استئناف", "Resume")
              : t(language, "إيقاف مؤقت", "Pause")}
          </Button>
        </div>
        {Object.keys(connectionTest).length > 0 && (
          <div className={`lp-connection-result ${connectionTest.state === "failed" ? "is-error" : ""}`} role="status" aria-live="polite">
            <Pill tone={connectionTest.state === "ok" ? "good" : connectionTest.state === "failed" ? "bad" : "warn"}>
              {connectionTest.state === "ok" ? t(language, "نجح الاتصال", "Connected") : connectionTest.state === "failed" ? t(language, "فشل الاتصال", "Connection failed") : t(language, "يفحص…", "Checking…")}
            </Pill>
            {connectionTest.latency_ms != null && <span>{n(Math.round(Number(connectionTest.latency_ms)), language)} ms</span>}
            {connectionTest.detail && <small>{String(connectionTest.detail)}</small>}
          </div>
        )}
        {notice && (
          <p className="lp-muted" role="status" aria-live="polite">
            {notice}
          </p>
        )}
      </Card>
      <Card>
        <div className="lp-card-head">
          <div>
            <span className="lp-eyebrow">MCP</span>
            <h2>{t(language, "ربط الذاكرة", "Memory connection")}</h2>
          </div>
          <ShieldCheck size={20} />
        </div>
        <div className="lp-provider-status" role="status">
          <Pill tone={mcpConfigReady ? "good" : "warn"}>
            {mcpConfigReady
              ? t(language, "جاهز للنسخ", "Ready to copy")
              : mcpAvailable === false
                ? t(language, "غير متاح", "Unavailable")
                : typeof mcpStatus.name === "string"
                  ? t(language, "حدّث Gateway", "Update Gateway")
                  : t(language, "جارٍ التحقق", "Checking")}
          </Pill>
          <span className="lp-muted">
            {n(arr(rec(mcp).tools).length, language)} {t(language, "أدوات", "tools")}
          </span>
        </div>
        <label className="lp-form-label">
          {t(language, "التطبيق المطلوب ربطه", "App to configure")}
          <select
            value={mcpClient}
            onChange={(event) => {
              setMcpClient(event.target.value as "codex" | "claude_code");
              setMcpNotice("");
            }}
          >
            <option value="codex">Codex · TOML</option>
            <option value="claude_code">Claude Code · JSON</option>
          </select>
        </label>
        <p className="lp-muted">
          {mcpConfigReady && mcpClient === "codex"
            ? t(language, "أضف هذا المقطع إلى إعداد Codex (config.toml) دون استبدال بقية الملف، أو نزّل المقطع. لم نتحقق من اتصال Codex.", "Add this snippet to Codex settings (config.toml) without replacing the rest of the file, or download it. Codex connectivity has not been verified.")
            : mcpConfigReady
              ? t(language, "ادمج الإعداد داخل .mcp.json في جذر المشروع، أو نزّل link-memory.mcp.json وانقل محتواه. لم نتحقق من اتصال Claude Code.", "Merge this entry into the project-root .mcp.json, or download link-memory.mcp.json and copy its contents. Claude Code connectivity has not been verified.")
              : t(language, "إعداد العميل غير متاح من نسخة Gateway الحالية. حدّث Gateway لتفعيل النسخ والتنزيل.", "Client configuration is unavailable from this Gateway version. Update Gateway to enable copying and download.")}
        </p>
        <div className="lp-actions">
          <Button disabled={!mcpConfigReady} onClick={() => void copyMcpConfig()}>
            <ShieldCheck size={17} />
            {t(language, "نسخ إعداد التطبيق", "Copy app configuration")}
          </Button>
          <Button disabled={!mcpConfigReady} variant="secondary" onClick={() => void downloadMcpConfig()}>
            <Download size={17} />
            {t(language, `تنزيل ${mcpClient === "codex" ? "مقطع TOML" : "link-memory.mcp.json"}`, `Download ${mcpClient === "codex" ? "TOML snippet" : "link-memory.mcp.json"}`)}
          </Button>
        </div>
        {mcpNotice && (
          <p className="lp-muted" role="status" aria-live="polite">
            {mcpNotice}
          </p>
        )}
      </Card>
      <Card>
        <div className="lp-card-head">
          <div>
            <h2>{t(language, "مصادر الالتقاط", "Capture sources")}</h2>
            <p className="lp-muted">{t(language, "تحكم بالتطبيقات التي يمكنها إرسال معلومات جديدة إلى الذاكرة.", "Choose which apps may send new information to memory.")}</p>
          </div>
          <ListChecks size={20} />
        </div>
        <p className="lp-help-inline">{t(language, "هذا الإعداد يحدد هل يقبل Gateway محاولات الالتقاط من المصدر. لا يعني أن التطبيق متصل أو أن hook مسجّل أو يعمل؛ العداد يعرض المحاولات التي وصلت إلى Gateway فقط.", "This setting controls whether the Gateway accepts capture attempts from this source. It does not confirm that the app is connected or a hook is installed or running; the count shows attempts that reached the Gateway only.")}</p>
        <div className="lp-hook-list">
          {[
            ["codex", t(language, "Codex", "Codex")],
            ["claude_code", t(language, "Claude Code", "Claude Code")],
            ["hermes_agent", t(language, "Hermes Agent", "Hermes Agent")],
          ].map(([id, label]) => {
            const item = rec(hooks[id]);
            const enabled = item.enabled !== false;
            return (
              <div className="lp-hook-row" key={id}>
                <div>
                  <strong>{label}</strong>
                  <small>{hooksLoaded ? `${enabled ? t(language, "السماح بالاستقبال مفعّل", "Gateway intake allowed") : t(language, "السماح بالاستقبال متوقف", "Gateway intake disabled")} · ${n(item.events, language)} ${t(language, "محاولات وصلت إلى Gateway", "capture attempts received by Gateway")}${item.last_seen ? ` · ${t(language, "آخر محاولة", "Last attempt")} ${formatTime(item.last_seen, language)}` : ` · ${t(language, "لم تصل محاولة بعد", "No attempt received yet")}`}` : t(language, "حالة الإعداد غير متاحة بعد؛ لا يمكن التحقق من السماح بالاستقبال.", "Settings status is not available yet; Gateway intake cannot be verified.")}</small>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={hooksLoaded ? enabled : false}
                  aria-label={`${t(language, "السماح بالالتقاط من", "Allow captures from")} ${label}`}
                  disabled={!hooksLoaded || hookBusy === id}
                  className={`lp-switch ${hooksLoaded && enabled ? "is-on" : ""}`}
                  onClick={() => void toggleHook(String(id), !enabled)}
                >
                  <span />
                </button>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
