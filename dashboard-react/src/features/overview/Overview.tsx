import { useCallback, useEffect, useState } from "react";
import { Activity, Download, HardDrive, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { api } from "../../api";
import { t, n, arr, rec, formatTime, statusText, activitySourceLabel, Sparkline, Button, Card, Pill, Lang, Page, R } from "../shared";

export function Overview({ language, go }: { language: Lang; go: (p: Page) => void }) {
  const [d, setD] = useState<R>({});
  const [err, setErr] = useState("");
  const load = useCallback(async () => {
    try {
      const [h, m, models, monitoring] = await Promise.all([
        api("/health"),
        api("/v1/metrics"),
        api("/v1/models/status"),
        api("/v1/monitoring").catch(async () => {
          const captures = await api("/v1/captures?limit=12").catch(() => ({}));
          return { events: arr(rec(captures).captures), series: [] };
        }),
      ]);
      setD({ h, m: rec(m).metrics || m, models, monitoring });
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "error");
    }
  }, []);
  useEffect(() => {
    let active = true;
    let inFlight = false;
    const refresh = async () => {
      if (inFlight || !active) return;
      inFlight = true;
      try {
        await load();
      } finally {
        inFlight = false;
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [load]);
  const h = rec(d.h),
    c = rec(h.counts),
    providerHealth = rec(h.providers),
    memoryLayerKeys = ["openmemory", "graphiti", "mempalace"],
    unavailableLayers = memoryLayerKeys.filter((name) => providerHealth[name]?.available === false),
    unverifiedLayers = memoryLayerKeys.filter((name) => typeof providerHealth[name]?.available !== "boolean"),
    m = rec(d.m),
    monitoring = rec(d.monitoring),
    series = arr(monitoring.series),
    metrics: { label: string; value: unknown; description: string; spark?: number[] }[] = [
      {
        label: t(language, "الذكريات", "Memories"),
        value: c.memories,
        description: t(language, "حقائق وتفضيلات نشطة محفوظة في النظام.", "Active facts and preferences stored in the memory system."),
        spark: series.map((point) => Number(point.memories || 0)),
      },
      {
        label: t(language, "المحادثات", "Conversations"),
        value: c.conversations,
        description: t(language, "محادثات مميزة ظهرت في سجل الالتقاط.", "Distinct conversations found in the capture log."),
        spark: series.map((point) => Number(point.conversations || 0)),
      },
      {
        label: t(language, "الرسائل", "Messages"),
        value: c.messages,
        description: t(language, "إجمالي الرسائل المسجلة عبر عمليات الالتقاط.", "Total messages recorded by capture events."),
      },
      {
        label: t(language, "المعلومات المستخرجة", "Extracted information"),
        value: rec(m.captures).saved,
        description: t(language, "مجموع ما حفظته المعالجة؛ رقم تراكمي وليس حدّ سعة.", "Items saved by processing; a cumulative count, not a capacity limit."),
        spark: series.map((point) => Number(point.memories || 0)),
      },
      {
        label: t(language, "مقاطع جاهزة للبحث", "Searchable passages"),
        value: c.embeddings,
        description: t(language, "مقاطع نصية جُهزت لتسهيل العثور على المعلومات المرتبطة.", "Text passages prepared to help find related information."),
      },
      {
        label: t(language, "التعارضات", "Conflicts"),
        value: c.open_conflicts,
        description: t(language, "تعارضات مفتوحة تنتظر المراجعة والحل.", "Open conflicts waiting for review and resolution."),
      },
      {
        label: t(language, "تنبيهات الالتقاط · 24 ساعة", "Capture alerts · 24h"),
        value: series.length ? series.reduce((sum, point) => sum + Number(point.alerts || 0), 0) : undefined,
        description: t(language, "رسائل فشلت أو استُبعدت أو تحتاج إلى مراجعتك.", "Messages that failed, were skipped, or need your review."),
        spark: series.map((point) => Number(point.alerts || 0)),
      },
    ];
  return (
    <div className="lp-stack">
      <section className="lp-hero lp-recall-hero">
        <div>
          <Pill tone={err || unavailableLayers.length ? "bad" : unverifiedLayers.length ? "warn" : "good"}>
            {err
              ? t(language, "تعذر قراءة حالة الخدمة", "Could not read service status")
              : unavailableLayers.length
                ? t(language, "بعض قدرات الذاكرة غير متاحة", "Some memory capabilities are unavailable")
                : unverifiedLayers.length
                  ? t(language, "حالة بعض قدرات الذاكرة غير مؤكدة", "Some memory capability states are unverified")
                  : t(language, "النظام متصل", "System connected")}
          </Pill>
          <h2>
            {t(
              language,
              "كل ما يحدث في الذاكرة، أمامك.",
              "Everything in memory, in one place.",
            )}
          </h2>
          <p>
            {t(
              language,
              "أرقام محدثة من الذاكرة، دون تقديرات.",
              "Updated memory counts, with no estimates.",
            )}
          </p>
        </div>
        <Button variant="secondary" onClick={() => void load()}>
          <RefreshCw size={17} />
          {t(language, "تحديث", "Refresh")}
        </Button>
      </section>
      <section className="lp-bento-grid">
        {metrics.map(({ label, value, description, spark }) => (
          <Card key={label}>
            <span className="lp-eyebrow">{label}</span>
            <h2>{n(value, language)}</h2>
            <p className="lp-metric-help">{description}</p>
            {spark && <Sparkline values={spark} label={t(language, "نشاط كل ساعة خلال آخر 24 ساعة", "Hourly activity over the last 24 hours")} />}
          </Card>
        ))}
      </section>
      <section className="lp-monitor-grid">
        <Card>
          <div className="lp-card-head">
            <div>
              <span className="lp-eyebrow">{t(language, "السرعة والمساحة", "SPEED & STORAGE")}</span>
              <h2>{t(language, "سرعة الخدمة وحجم بياناتها", "Service speed and data size")}</h2>
            </div>
            <HardDrive size={20} />
          </div>
          <div className="lp-monitor-stats">
            <div>
              <span>{t(language, "أعلى زمن فحص اتصال · 24 ساعة", "Slowest connection check · 24h")}</span>
              <strong>{monitoring.performance?.peak_health_check_latency_ms == null ? "—" : `${n(monitoring.performance.peak_health_check_latency_ms, language)} ms`}</strong>
            </div>
            <div>
              <span>{t(language, "حجم بيانات الخدمة المحلية", "Local service data size")}</span>
              <strong>{monitoring.performance?.gateway_sqlite_bytes == null ? "—" : `${(Number(monitoring.performance.gateway_sqlite_bytes) / (1024 * 1024)).toFixed(2)} MB`}</strong>
            </div>
          </div>
          <p className="lp-monitor-footnote">{t(language, "هذا الرقم يخص قاعدة الخدمة المحلية فقط، ولا يشمل بيانات الطبقات الأخرى.", "This figure covers the local service database only, not data held by the other memory layers.")}</p>
          {arr(monitoring.performance?.gateway_sqlite_storage_segments).length > 0 && (
            <details className="lp-layer-usage lp-overview-storage-details">
              <summary>{t(language, "تفاصيل مساحة التخزين", "Storage details")}</summary>
              <div className="lp-storage-breakdown" aria-label={t(language, "توزيع بيانات الخدمة المحلية", "Local service data breakdown")}>
                <div className="lp-storage-track" role="img" aria-label={t(language, "توزيع الحجم المرصود لملفات الخدمة المحلية", "Observed local service file-size breakdown")}>
                  {arr(monitoring.performance.gateway_sqlite_storage_segments).map((segment) => (
                    <span key={String(segment.name)} style={{ width: `${Math.max(0, Math.min(100, Number(segment.share_percent) || 0))}%` }} title={t(language, `${n(segment.bytes, language)} بايت`, `${n(segment.bytes, language)} bytes`)} />
                  ))}
                </div>
                <div className="lp-storage-legend">
                  {arr(monitoring.performance.gateway_sqlite_storage_segments).map((segment) => {
                    const fileName = String(segment.name);
                    const label = fileName.endsWith("-wal") ? t(language, "سجل التغييرات", "Change log") : fileName.endsWith("-shm") ? t(language, "ذاكرة مشتركة", "Shared memory") : t(language, "قاعدة البيانات", "Database");
                    return <span key={fileName}>{label} · {n(segment.bytes, language)} {t(language, "بايت", "bytes")}</span>;
                  })}
                </div>
                <small>{t(language, "تفصيل داخلي لملفات الخدمة؛ لا يمثل حدًا للسعة.", "Internal service-file breakdown; this is not a storage limit.")}</small>
              </div>
            </details>
          )}
          <p className="lp-muted">
            {monitoring.performance?.latency_sample_count
              ? `${t(language, "مبني على", "Based on")} ${n(monitoring.performance.latency_sample_count, language)} ${t(language, "فحوص اتصال فعلية؛ لا يمثل زمن كل العمليات.", "real connection checks; this is not the latency of every operation.")}`
              : series.length
                ? t(language, "لا توجد فحوص اتصال مسجلة خلال آخر 24 ساعة.", "No connection checks were recorded in the last 24 hours.")
                : t(language, "قياس سرعة الاتصال غير متاح حاليًا.", "Connection-speed measurement is not available yet.")}
          </p>
        </Card>
        <Card>
          <div className="lp-card-head">
            <div>
              <span className="lp-eyebrow">{t(language, "تحديث تلقائي كل 15 ثانية", "AUTO-REFRESH · 15 SECONDS")}</span>
              <h2>{t(language, "آخر ما حدث", "Recent activity")}</h2>
            </div>
            <Activity size={20} />
          </div>
          <div className="lp-activity-feed" aria-live="polite">
          {arr(monitoring.events).length ? arr(monitoring.events).map((event) => (
              <div className="lp-activity-row" key={String(event.id)}>
                <span className="lp-activity-mark" />
                <div>
                  <strong>{event.source ? activitySourceLabel(event.source, language) : t(language, "مصدر غير معروف", "Unknown source")}</strong>
                  <small>{statusText(event.status, language)} · {n(event.saved_count, language)} {t(language, "محفوظ", "saved")}</small>
                </div>
                <time>{formatTime(event.created_at, language)}</time>
              </div>
          )) : <p className="lp-muted">{series.length ? t(language, "لا توجد أحداث التقاط مسجلة بعد.", "No capture events recorded yet.") : t(language, "تعذّر تحميل سجل النشاط الآن. أعد المحاولة بعد قليل.", "Activity history could not be loaded right now. Try again shortly.")}</p>}
          </div>
        </Card>
      </section>
      <Card>
        <div className="lp-card-head">
          <div>
          <span className="lp-eyebrow">{t(language, "قدرات الذاكرة", "MEMORY CAPABILITIES")}</span>
          <h2>{t(language, "ما الذي يعمل الآن؟", "What’s working now?")}</h2>
        </div>
        <ShieldCheck size={20} />
      </div>
      <div className="lp-service-list" aria-label={t(language, "حالة الخدمات", "Service states")}>
        {[
          [t(language, "حفظ الحقائق والتفضيلات", "Save facts and preferences"), Boolean(providerHealth.openmemory?.available), providerHealth.openmemory?.state || "unavailable"],
          [t(language, "ربط الأحداث والتواريخ", "Connect events and dates"), Boolean(providerHealth.graphiti?.available), providerHealth.graphiti?.state || "unavailable"],
          [t(language, "الرجوع إلى المحادثات", "Find original conversations"), Boolean(providerHealth.mempalace?.available), providerHealth.mempalace?.state || "unavailable"],
          [t(language, "البحث بحسب المعنى", "Search by meaning"), ["ready", "working"].includes(String(rec(d.models).embedding?.state)), rec(d.models).embedding?.state || "unavailable"],
          [t(language, "تحسين ترتيب النتائج", "Improve result order"), ["ready", "working"].includes(String(rec(d.models).reranker?.state)), rec(d.models).reranker?.state || "unavailable"],
          [t(language, "توجيه طلبات المساعد", "Route assistant requests"), rec(d.models).openrouter?.state === "primary", rec(d.models).openrouter?.state || "standby"],
        ].map(([name, ok, state]) => (
            <div key={String(name)}>
              <span>{String(name)}</span>
              <Pill tone={state === "disabled" || state === "standby" ? "muted" : ["starting", "warming"].includes(String(state)) ? "warn" : ok ? "good" : "bad"}>
                {state === "standby" ? t(language, "غير مستخدم الآن", "Not in use right now") : state === "disabled" ? t(language, "غير مفعّل", "Off") : ["starting", "warming"].includes(String(state)) ? t(language, "جارٍ التجهيز", "Starting up") : ok ? t(language, "يعمل", "Working") : t(language, "غير متاح", "Unavailable")}
              </Pill>
            </div>
          ))}
        </div>
      </Card>
      <div className="lp-actions">
        <Button onClick={() => go("recall")}>
          <Search size={17} />
          {t(language, "بحث في الذاكرة", "Search memory")}
        </Button>
        <Button variant="secondary" onClick={() => go("operations")}>
          <Download size={17} />
          {t(language, "فتح العمليات", "Open operations")}
        </Button>
      </div>
    </div>
  );
}
