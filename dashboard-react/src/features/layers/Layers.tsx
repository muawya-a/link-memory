import { useCallback, useEffect, useState } from "react";
import { Network, RefreshCw } from "lucide-react";
import { api } from "../../api";
import { t, n, rec, Button, Card, Pill, Lang, R } from "../shared";

export function Layers({ language }: { language: Lang }) {
  const [data, setData] = useState<R>({});
  const [savedMemoryCount, setSavedMemoryCount] = useState<number | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [layerData, statusData] = await Promise.all([
        api(`/v1/memory-layers?ts=${Date.now()}`),
        api("/v1/status").catch(() => ({})),
      ]);
      setData(rec(layerData));
      const count = rec(rec(statusData).counts).memories;
      setSavedMemoryCount(Number.isFinite(Number(count)) ? Number(count) : null);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "error");
    }
  }, []);
  useEffect(() => {
    let active = true;
    let inFlight = false;
    const refresh = async () => {
      if (!active || inFlight) return;
      inFlight = true;
      try { await load(); } finally { inFlight = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 20000);
    return () => { active = false; window.clearInterval(timer); };
  }, [load]);
  const layers = Object.entries(rec(data.layers));
  const layerStatuses = rec(data.status);
  const hasLayerStatus = Object.keys(layerStatuses).length > 0;
  const localFacts = rec(rec(data.layers).openmemory);
  const localMemoryCount = Number.isFinite(Number(localFacts.local_count)) ? Number(localFacts.local_count) : null;
  const layerGuide: Record<string, { title: string; description: string; usefulFor: string }> = {
    openmemory: {
      title: t(language, "حقائق Link Memory المحلية", "Link Memory local facts"),
      description: t(language, "يحفظ Gateway الحقائق والتفضيلات والقرارات محليًا في قاعدة Link Memory. الموصل الخارجي للحقائق اختياري وغير مضمّن افتراضيًا.", "The Gateway stores facts, preferences, and decisions locally in Link Memory. The external facts adapter is optional and not bundled by default."),
      usefulFor: t(language, "عندما تسأل عن معلومة شخصية أو تفضيل سبق أن ذكرته.", "When you ask about a personal fact or preference you mentioned before."),
    },
    graphiti: {
      title: t(language, "الروابط والتسلسل الزمني", "Connections & timeline"),
      description: t(language, "يربط الأشخاص والمواضيع والأحداث عبر الزمن، لتتضح العلاقات وما تغيّر ومتى.", "Connects people, topics, and events over time, making relationships and changes easier to follow."),
      usefulFor: t(language, "عندما تسأل عن علاقة بين موضوعين أو عن ترتيب الأحداث وتواريخها.", "When you ask how two topics connect or when events happened."),
    },
    mempalace: {
      title: t(language, "المحادثات والنصوص الأصلية", "Original conversations & text"),
      description: t(language, "يرجع إلى المحادثة أو النص الأصلي للتحقق من العبارة والتفاصيل والسياق.", "Returns to the original conversation or text to verify wording, details, and context."),
      usefulFor: t(language, "عندما تحتاج العبارة الأصلية أو سياقًا أوسع من الخلاصة.", "When you need the original wording or context beyond a short summary."),
    },
  };
  return (
    <div className="lp-stack">
      <section className="lp-hero">
        <div>
          <Pill tone={error || (hasLayerStatus && !data.ok) ? "bad" : data.ok ? "good" : "muted"}>
            {error
              ? t(language, "تعذر تحديث الحالة", "Could not refresh status")
              : data.ok
                ? t(language, "طبقات الذاكرة الثلاث متاحة", "All three memory layers available")
                : hasLayerStatus
                  ? t(language, "بعض طبقات الذاكرة غير متاحة", "Some memory layers are unavailable")
                  : t(language, "جارٍ فحص طبقات الذاكرة", "Checking memory layers")}
          </Pill>
          <h2>{t(language, "طبقات الذاكرة", "Memory layers")}</h2>
          <p>
            {t(
            language,
              "تُحفظ المعلومة المقبولة أولًا، ثم تُنظّم ضمن طبقات الذاكرة المتاحة. لكل طبقة دور مختلف، ويجمع Link Memory نتائج البحث منها.",
              "Accepted information is saved in Link Memory first, then organized across the available memory layers. Each has a different role, and Link Memory brings their search results together.",
            )}
          </p>
        </div>
        <Button variant="secondary" onClick={() => void load()}>
          <RefreshCw size={17} />
          {t(language, "تحديث", "Refresh")}
        </Button>
      </section>
      <Card>
        <div className="lp-card-head">
          <div>
            <span className="lp-eyebrow">HOW IT WORKS</span>
            <h2>{t(language, "كيف تعمل معًا؟", "How they work together")}</h2>
          </div>
          <Network size={20} />
        </div>
        <p>
          {t(
            language,
            "لكل نوع من الذاكرة دور مختلف: حفظ الحقائق وسياق العمل، وربط العلاقات والأحداث عبر الزمن، والرجوع إلى النصوص الأصلية. ينسّق Link Memory الحفظ ويجمع نتائج البحث من الأنواع المتاحة. إذا تعذّر أحدها، نوضح أن النتائج جزئية.",
            "Each memory type has a distinct role: preserving facts and working context, connecting relationships and events over time, and returning to original text. Link Memory coordinates saving and combines results from the available types. If one is unavailable, results are marked partial.",
          )}
        </p>
        <div className="lp-layer-flow" aria-label={t(language, "رحلة المعلومة في الذاكرة", "How information moves through memory")}>
          {[
            [t(language, "١", "1"), t(language, "تصل المعلومة", "Information arrives"), t(language, "من مصدر التقاط مفعّل أو ملف استوردته", "From an enabled capture source or a file you imported")],
            [t(language, "٢", "2"), t(language, "تُحفظ ثم تُنظّم", "Saved, then organized"), t(language, "حقائق، علاقات زمنية، ونص أصلي", "Facts, time-based connections, and original text")],
            [t(language, "٣", "3"), t(language, "تُسترجع معًا", "Searched together"), t(language, "تظهر النتائج مع مصدر كل معلومة", "Results show where each memory came from")],
          ].map(([step, title, detail]) => (
            <div className="lp-layer-flow-step" key={step}>
              <span>{step}</span><div><strong>{title}</strong><small>{detail}</small></div>
            </div>
          ))}
        </div>
      </Card>
      <section className="lp-retention-grid" aria-label={t(language, "أنواع الذاكرة", "Memory durations")}>
        <Card>
          <div className="lp-card-head">
            <div><span className="lp-eyebrow">LOCAL · GATEWAY FACTS</span><h2>{t(language, "قاعدة الحقائق المحلية", "Local facts store")}</h2></div>
            <Pill tone={layerStatuses.openmemory?.available ? "good" : "muted"}>{layerStatuses.openmemory?.available ? t(language, "متاحة", "Available") : t(language, "غير متاحة", "Unavailable")}</Pill>
          </div>
          <p>{t(language, "هذه هي قاعدة الحقائق الأساسية، وتعمل محليًا حتى لو لم يُثبّت الموصل الخارجي الاختياري.", "This is the canonical facts store and runs locally even when the optional external adapter is not installed.")}</p>
          <div className="lp-retention-metric"><span>{t(language, "ذكريات محلية نشطة", "Active local memories")}</span><strong>{localMemoryCount == null ? "—" : n(localMemoryCount, language)}</strong></div>
          <p className="lp-monitor-footnote">{t(language, "لا يعني هذا العدد وجود نسخة في أي خدمة خارجية.", "This count does not imply a copy exists in an external service.")}</p>
        </Card>
        <Card>
          <div className="lp-card-head">
            <div><span className="lp-eyebrow">LONG-TERM · SAVED MEMORY</span><h2>{t(language, "المعلومات المحفوظة للرجوع إليها", "Saved for future reference")}</h2></div>
            <Pill tone={data.ok ? "good" : "muted"}>{data.ok ? t(language, "الطبقات متصلة", "Layers connected") : t(language, "حالة جزئية", "Partial status")}</Pill>
          </div>
          <p>{t(language, "المعلومات طويلة الأمد هي ما حُفظ لتعود إليه في محادثات وأسئلة لاحقة. يحتفظ النظام بنسخة أساسية واحدة ثم يوزّعها على مصادر الذاكرة المتاحة؛ لذلك قد تظهر نسخ منها في أكثر من مصدر.", "Long-term memory is information saved for later conversations and questions. The system keeps one canonical record and sends it to available memory sources, so copies may exist in more than one source.")}</p>
          <div className="lp-retention-metric"><span>{t(language, "ذكريات محفوظة فريدة", "Unique saved memories")}</span><strong>{savedMemoryCount == null ? "—" : n(savedMemoryCount, language)}</strong></div>
          <p className="lp-monitor-footnote">{t(language, "هذا العدد من سجل Link Memory ولا يجمع النسخ الموجودة في المصادر المختلفة. لا توجد مدة حذف تلقائي معلنة.", "This count comes from Link Memory and does not add copies across sources. No automatic deletion period is reported.")}</p>
        </Card>
      </section>
      <section className="lp-bento-grid">
        {layers.map(([id, value]) => {
          const layer = rec(value);
          const state = rec(data.status)[id];
          const guide = layerGuide[id] || { title: t(language, "دور في الذاكرة", "Memory role"), description: "", usefulFor: "" };
          const counts = rec(layer.link_counts);
          const sent = Number(counts.sent || 0);
          const failed = Number(counts.failed || 0);
          const queued = Number(counts.queued || 0);
          const total = sent + failed + queued;
          const retrieval = rec(layer.retrieval_stats);
          const hitRate = retrieval.hit_rate_percent;
          return (
            <Card key={id}>
              <div className="lp-card-head">
                <div>
                  <span className="lp-eyebrow">{t(language, "نوع الذاكرة", "MEMORY TYPE")}</span>
                  <h2>{guide.title}</h2>
                </div>
                <Pill tone={state.available ? "good" : "bad"}>
                  {state.available
                    ? t(language, "يعمل", "Working")
                    : t(language, "متوقف", "Unavailable")}
                </Pill>
              </div>
              <p>{guide.description}</p>
              <p className="lp-layer-purpose"><strong>{t(language, "تفيدك عندما", "Useful when")}</strong>{guide.usefulFor}</p>
              <details className="lp-layer-usage">
                <summary>{t(language, "تفاصيل النشاط", "Activity details")}</summary>
                <div className="lp-layer-stat-row">
                  <div><span>{t(language, id === "openmemory" ? "حفظ في الموصل الخارجي الاختياري" : "سجلات حفظ ناجحة", id === "openmemory" ? "Saves to optional external adapter" : "Successful saves")}</span><strong>{n(sent, language)}</strong></div>
                  <div><span>{t(language, id === "openmemory" ? "عمليات الموصل المعلّقة" : "بانتظار الإكمال", id === "openmemory" ? "External adapter operations pending" : "Still in progress")}</span><strong>{n(failed + queued, language)}</strong></div>
                  <div title={t(language, "نسبة عمليات البحث الناجحة التي أعادت نتيجة من هذه الطبقة", "Share of successful searches that returned a result from this layer")}><span>{t(language, "بحث وجد معلومة", "Searches with a match")}</span><strong>{hitRate == null ? "—" : `${n(hitRate, language)}%`}</strong><small>{n(retrieval.hit_searches, language)} / {n(retrieval.successful_searches, language)} {t(language, "بحثًا", "searches")}</small></div>
                </div>
                <p className="lp-monitor-footnote">{id === "openmemory" ? t(language, "هذه الأرقام تخص الموصل الخارجي فقط؛ قاعدة الحقائق المحلية تعمل بصورة مستقلة.", "These numbers describe only the external adapter; the local facts store works independently.") : total === 0 ? t(language, "لا توجد سجلات حفظ لهذه الطبقة بعد.", "There are no save records for this layer yet.") : t(language, "الأرقام تخص هذه الطبقة؛ قد تُحفظ المعلومة نفسها في أكثر من طبقة، فلا تجمع الأعداد بوصفها معلومات منفردة.", "These figures belong to this layer; the same memory may be saved in more than one layer, so do not add them as unique memories.")}</p>
              </details>
            </Card>
          );
        })}
      </section>

    </div>
  );
}
