import { useState } from "react";
import { Activity, Copy, Search, Sparkles } from "lucide-react";
import { post } from "../../api";
import { t, n, arr, rec, Button, Card, Pill, Lang, R } from "../shared";

export function Recall({ language }: { language: Lang }) {
  const [q, setQ] = useState("");
  const [searchedQuestion, setSearchedQuestion] = useState("");
  const [items, setItems] = useState<R[]>([]);
  const [trace, setTrace] = useState<R>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [previewContext, setPreviewContext] = useState(false);
  const [copied, setCopied] = useState(false);
  const [sourceFilter, setSourceFilter] = useState("all");
  const [searchLimit, setSearchLimit] = useState(100);
  const [healthBusy, setHealthBusy] = useState(false);
  const [healthResult, setHealthResult] = useState<R>({});
  const [healthError, setHealthError] = useState("");
  const [showPossibleMatches, setShowPossibleMatches] = useState(false);
  const [answerData, setAnswerData] = useState<R | null>(null);
  const [answerBusy, setAnswerBusy] = useState(false);
  const [answerError, setAnswerError] = useState("");
  const [externalAnswerConsent, setExternalAnswerConsent] = useState(false);
  const providers = ["openmemory", "graphiti", "mempalace"];
  const entitiesFor = (item: R) => {
    const metadata = rec(item.metadata);
    const node = rec(metadata.node);
    const values = item.entities || metadata.entities || metadata.resolved_entities || node.resolved_entities;
    if (Array.isArray(values)) return values.map((value: any) => typeof value === "string" ? value : String(value.name || "")).filter((value) => value && !/^(?:entity|node):[\w-]+$/i.test(value));
    return [];
  };
  const customerMemoryText = (value: unknown) => String(value || "")
    .replace(/^\s*#+\s*codex(?:-history)?\b\s*/gim, "")
    .replace(/\bMemory ID\s*:\s*[a-f\d-]{16,}\b/gi, "")
    .replace(/\bKind\s*:\s*(?:fact|preference|decision|skill|date|relationship|source_text|episode)\b/gi, "")
    .replace(/^\s*(?:source_path|source_file|source path|source file)\s*:\s*[^\r\n]*$/gim, "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
  const memoryKindLabel = (value: unknown) => {
    const kind = String(value || "fact").toLowerCase();
    const labels: Record<string, [string, string]> = {
      fact: ["معلومة", "Fact"], preference: ["تفضيل", "Preference"], decision: ["قرار", "Decision"],
      skill: ["مهارة", "Skill"], relationship: ["علاقة", "Relationship"], date: ["موعد", "Date"],
      source_text: ["نص محفوظ", "Saved text"], episode: ["حدث", "Event"],
    };
    return labels[kind] ? t(language, labels[kind][0], labels[kind][1]) : t(language, "معلومة", "Information");
  };
  const memorySourceLabel = (value: unknown) => {
    const source = String(value || "").toLowerCase();
    const labels: Record<string, [string, string]> = {
      codex: ["Codex", "Codex"], "codex-history": ["Codex", "Codex"],
      "claude-code": ["Claude Code", "Claude Code"], "claude-history": ["Claude", "Claude"],
      "hermes-agent": ["Hermes", "Hermes"], hermes: ["Hermes", "Hermes"],
      "pc-file": ["ملف مستورد", "Imported file"], import: ["ملف مستورد", "Imported file"],
      openmemory: ["سجل الذاكرة", "Memory notes"], graphiti: ["العلاقات المحفوظة", "Saved connections"], mempalace: ["أرشيف المحادثات", "Conversation archive"],
      chatgpt: ["ChatGPT", "ChatGPT"], gemini: ["Gemini", "Gemini"], grok: ["Grok", "Grok"],
    };
    if (labels[source]) return t(language, labels[source][0], labels[source][1]);
    return source ? t(language, "مصدر آخر", "Other source") : t(language, "مصدر غير محدد", "Source not specified");
  };
  const memoryDateLabel = (value: unknown) => {
    if (value == null || value === "") return "";
    const raw = String(value);
    const numeric = /^\d{10,13}$/.test(raw) ? Number(raw) : NaN;
    const date = new Date(Number.isFinite(numeric) ? (raw.length <= 10 ? numeric * 1000 : numeric) : raw);
    if (!Number.isFinite(date.getTime())) return "";
    return new Intl.DateTimeFormat(language === "ar" ? "ar" : "en-GB", {
      calendar: "gregory", day: "numeric", month: "short", year: "numeric",
    }).format(date);
  };
  const layerState = (layer: R) => {
    if (!layer || Object.keys(layer).length === 0) return { label: t(language, "بيانات التتبّع غير متاحة", "Trace data unavailable"), tone: "muted" };
    if (layer.enabled === false) return { label: t(language, "غير مفعّل", "Disabled"), tone: "muted" };
    if (layer.ok === false) return { label: t(language, "تعذّر الاتصال", "Unavailable"), tone: "bad" };
    if (layer.partial) return { label: t(language, "نتائج جزئية", "Partial results"), tone: "muted" };
    if (Number(layer.results) > 0) return { label: t(language, "نجح · توجد نتائج", "Success · matches"), tone: "good" };
    return { label: t(language, "نجح · لا توجد مطابقة", "Success · no match"), tone: "neutral" };
  };
  async function run(e?: React.FormEvent) {
    e?.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    setError("");
    try {
      const r = await post<R>("/v1/interactive/context", {
        message: q,
        limit: searchLimit,
      });
      setItems(arr(r.search_results || r.context_packet || r.memories || r.results));
      setTrace(r);
      setSearchedQuestion(q.trim());
      setSourceFilter("all");
      setPreviewContext(false);
      setShowPossibleMatches(false);
      setAnswerData(null);
      setAnswerError("");
      setExternalAnswerConsent(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "search failed");
      setItems([]);
      setTrace({});
    } finally {
      setBusy(false);
    }
  }
  const runHealthCheck = async () => {
    const syntheticQuery = "Link Memory Gateway memory retrieval status";
    setHealthBusy(true);
    setHealthError("");
    const started = performance.now();
    try {
      const data = await post<R>("/v1/interactive/context", { message: syntheticQuery, limit: 8 });
      setHealthResult({ data, elapsedMs: Math.round(performance.now() - started) });
    } catch (err) {
      setHealthResult({ elapsedMs: Math.round(performance.now() - started) });
      setHealthError(err instanceof Error ? err.message : "health check failed");
    } finally {
      setHealthBusy(false);
    }
  };
  const generateAnswer = async () => {
    if (!searchedQuestion || q.trim() !== searchedQuestion) return;
    setAnswerBusy(true);
    setAnswerError("");
    setAnswerData(null);
    try {
      const answer = await post<R>("/v1/interactive/answer", {
        message: searchedQuestion,
        allow_external: externalAnswerConsent,
      });
      if (answer.status === "ok") setAnswerData(answer);
      else if (answer.status === "no_evidence") setAnswerError(t(language, "ما لقينا ذكريات واضحة تكفي لصياغة جواب. جرّب سؤالًا أدق أو استعرض النتائج المتاحة.", "There are not enough clear memories to draft an answer. Try a more specific question or review the available results."));
      else if (answer.status === "uncited_answer" || answer.status === "invalid_model_response") setAnswerError(t(language, "ما قدرنا نتحقق من ربط الجواب بالمصادر، لذلك ما عرضناه. راجع نقاط الذاكرة الأصلية أدناه.", "We could not verify that the draft cites its sources, so we did not show it. Review the original memory findings below."));
      else if (answer.status === "rate_limited") setAnswerError(t(language, "استخدمت صياغة الإجابات عدة مرات خلال دقيقة. انتظر قليلًا ثم أعد المحاولة.", "Answer drafting was used several times within one minute. Wait briefly and try again."));
      else if (answer.status === "unavailable") setAnswerError(t(language, "ما فيه نموذج إجابة متاح حسب إعداداتك الحالية. تقدر تراجع نقاط الذاكرة الأصلية أدناه.", "No answer model is available with the current settings. You can review the original memory findings below."));
      else setAnswerError(t(language, "تعذّرت صياغة الإجابة الآن. بقيت نتائج الذاكرة الأصلية كما هي.", "The answer could not be drafted right now. The original memory results are unchanged."));
    } catch {
      setAnswerError(t(language, "تعذّر الوصول إلى خدمة صياغة الإجابة. نتائج البحث الأصلية ما زالت متاحة.", "Could not reach the answer service. The original search results are still available."));
    } finally {
      setAnswerBusy(false);
    }
  };
  const recallQueries = rec(trace.recall?.queries);
  const providerTrace = providers.reduce((summary, name) => {
    const traces = Object.values(recallQueries)
      .map((entry) => rec(rec(entry).providers)[name])
      .filter((entry) => Object.keys(rec(entry)).length > 0)
      .map(rec);
    if (!traces.length) return summary;
    const retrieved = new Map<string, R>();
    for (const layer of traces) {
      for (const item of arr(layer.items)) {
        const key = String(item.id || String(item.text || "").replace(/\s+/g, " ").trim().toLocaleLowerCase());
        const prior = retrieved.get(key);
        retrieved.set(key, prior ? { ...prior, matched_queries: [...new Set([...arr(prior.matched_queries), ...arr(item.matched_queries)])] } : item);
      }
    }
    const succeeded = traces.some((layer) => layer.ok === true);
    const failed = traces.some((layer) => layer.enabled !== false && layer.ok === false);
    summary[name] = {
      ...traces[0],
      enabled: traces.some((layer) => layer.enabled !== false),
      ok: succeeded || (!failed && traces.every((layer) => layer.enabled === false)),
      partial: succeeded && failed,
      results: retrieved.size || Math.max(0, ...traces.map((layer) => Number(layer.results || 0))),
      latency_ms: Math.max(0, ...traces.map((layer) => Number(layer.latency_ms || 0))),
      items: [...retrieved.values()],
      error: traces.find((layer) => layer.ok === false)?.error,
    };
    return summary;
  }, {} as R);
  const respondingProviderCount = providers.filter((name) => providerTrace[name]?.enabled !== false && providerTrace[name]?.ok === true).length;
  const providerTraceCount = providers.filter((name) => Object.keys(rec(providerTrace[name])).length > 0).length;
  const hasPartialCoverage = providerTraceCount < providers.length || respondingProviderCount < providers.length;
  const healthQueries = rec(healthResult.data?.recall?.queries);
  const healthTrace = rec(healthQueries[String(healthResult.data?.query || "")] || Object.values(healthQueries)[0]);
  const healthProviders = rec(healthTrace.providers);
  const answerOptions = rec(trace.answer_options);
  const answerUsesRemote = answerOptions.remote === true;
  const answerIsAvailable = answerOptions.available === true;
  const hasAnswerEvidence = arr(trace.context_packet).length > 0;
  const healthLayerFailure = providers.some((name) => healthProviders[name]?.enabled && healthProviders[name]?.ok === false);
  const healthAllLayersOk = providers.every((name) => healthProviders[name]?.enabled && healthProviders[name]?.ok === true);
  const sources = [...new Set(items.map((item) => String(item.source || "").trim()).filter(Boolean))].sort();
  // The current local reranker emits an uncalibrated ranking score. Keep its
  // low-scoring candidates inspectable, but don't present them as answer facts.
  const relevanceFloor = -4.5;
  const hasRerankerScore = (item: R) => item.reranker_score !== null && item.reranker_score !== undefined && item.reranker_score !== "" && Number.isFinite(Number(item.reranker_score));
  const isPossibleMatch = (item: R) => item.match_quality === "possible" || (item.match_quality !== "strong" && hasRerankerScore(item) && Number(item.reranker_score) < relevanceFloor);
  const trustedItems = items.filter((item) => !isPossibleMatch(item));
  const possibleItems = items.filter(isPossibleMatch);
  const visibleItems = trustedItems.filter((item) => {
    const sourceMatches = sourceFilter === "all" || String(item.source || "") === sourceFilter;
    return sourceMatches;
  });
  const visiblePossibleItems = possibleItems.filter((item) => {
    const sourceMatches = sourceFilter === "all" || String(item.source || "") === sourceFilter;
    return sourceMatches;
  });
  const memoryTextKey = (item: R) => String(item.text || item.display_text || "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
  const visibleTextKeys = new Set(visibleItems.map(memoryTextKey));
  const unifiedAnswerItems = (sourceFilter === "all" && arr(trace.context_packet).length ? arr(trace.context_packet) : visibleItems)
    .filter((item) => !isPossibleMatch(item)).slice(0, 6);
  const answerLayers = (item: R) => arr(item.providers)
    .map((provider) => String(provider).toLowerCase())
    .filter((provider, index, all) => all.indexOf(provider) === index)
    .map((provider) => provider === "openmemory" ? t(language, "الحقائق والسياق", "Facts & context") : provider === "graphiti" ? t(language, "العلاقات والأحداث", "Relations & events") : provider === "mempalace" ? t(language, "النصوص المحفوظة", "Saved texts") : "")
    .filter(Boolean);
  return (
    <div className="lp-stack">
      <section className="lp-hero">
        <div>
          <span className="lp-eyebrow">INTERACTIVE RECALL</span>
          <h2>
            {t(language, "اسأل الذاكرة مباشرة", "Ask the memory directly")}
          </h2>
          <p>
            {t(
              language,
              "ابحث في المعلومات التي حفظتها، واعثر على التفاصيل والروابط المرتبطة بسؤالك.",
              "Search what you have saved and find details and connections related to your question.",
            )}
          </p>
        </div>
        <Button onClick={runHealthCheck} disabled={healthBusy}>
          <Activity size={17} />
          {healthBusy
            ? t(language, "يفحص الطبقات…", "Checking layers…")
            : t(language, "فحص شمولية الاسترجاع", "Check retrieval coverage")}
        </Button>
      </section>
      <Card>
        <form className="lp-search-row" onSubmit={run}>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t(
              language,
              "ماذا تريد أن تتذكر؟",
              "What do you want to remember?",
            )}
          />
          <Button type="submit" disabled={busy}>
            <Search size={17} />
            {busy
              ? t(language, "يبحث…", "Searching…")
              : t(language, "بحث تفاعلي", "Interactive search")}
          </Button>
        </form>
        {error && <p className="lp-alert lp-alert-bad">{error}</p>}
        <div className="lp-recall-filters lp-recall-filter-row">
          <div className="lp-recall-filter-heading">
            <strong>{t(language, "خصّص طريقة عرض النتائج", "Choose how results are shown")}</strong>
            <span>{t(language, "هذه الخيارات تغيّر العرض فقط، ولا تعدّل المعلومات المحفوظة.", "These options only change the view; they do not edit saved information.")}</span>
          </div>
          <label>
            <span className="lp-recall-filter-label">{t(language, "مصدر المعلومة", "Memory source")}</span>
            <small>{t(language, "من أي تطبيق أو ملف؟", "Which app or file did it come from?")}</small>
            <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)} disabled={!sources.length}>
              <option value="all">{t(language, "كل المصادر", "All sources")}</option>
              {sources.map((source) => <option key={source} value={source}>{memorySourceLabel(source)}</option>)}
            </select>
          </label>
          <label>
            <span className="lp-recall-filter-label">{t(language, "عدد النتائج", "Number of results")}</span>
            <small>{t(language, "كم نتيجة تريد استعراضها؟", "How many results would you like to see?")}</small>
            <select value={searchLimit} onChange={(e) => setSearchLimit(Number(e.target.value))}>
              {[20, 50, 100].map((limit) => <option key={limit} value={limit}>{n(limit, language)}</option>)}
            </select>
          </label>
        </div>
      </Card>
      {healthResult.data && (
        <Card>
          <div className="lp-card-head">
            <div>
              <span className="lp-eyebrow">LIVE RETRIEVAL CHECK</span>
              <h2>{t(language, "نتيجة الفحص الفعلي", "Live check results")}</h2>
            </div>
            <Pill tone={healthError || healthLayerFailure ? "bad" : healthAllLayersOk ? "good" : "muted"}>
              {healthError ? t(language, "تعذّر الطلب", "Request failed") : healthLayerFailure ? t(language, "طبقة واحدة أو أكثر تعثرت", "One or more layers failed") : healthAllLayersOk ? `${t(language, "اكتمل", "Complete")} · ${n(healthResult.elapsedMs, language)} ms` : t(language, "نتيجة جزئية", "Partial result")}
            </Pill>
          </div>
          {healthError && <p className="lp-alert lp-alert-bad">{healthError}</p>}
          {!Object.keys(healthProviders).length && <p className="lp-recall-note">{t(language, "تفاصيل حالة مجموعات الذاكرة غير متاحة الآن؛ ستظل نتائج الفحص التي وصلت ظاهرة.", "Memory-group status details are unavailable right now; any results that arrived remain visible.")}</p>}
          <div className="lp-recall-layer-grid" aria-live="polite">
            {providers.map((name) => {
              const layer = rec(healthProviders[name]);
              const state = layerState(layer);
              return <div className="lp-recall-layer-status" key={name}>
                <strong>{name === "openmemory" ? t(language, "الحقائق والسياق", "Facts & context") : name === "mempalace" ? t(language, "النصوص المحفوظة", "Saved texts") : t(language, "العلاقات والأحداث", "Relations & events")}</strong>
                <span className={`lp-recall-badge is-${state.tone}`}>{state.label}</span>
                <small>
                  {layer.enabled === false ? t(language, "لم يُرسل إليه طلب", "Not queried") : `${layer.latency_ms != null ? `${n(layer.latency_ms, language)} ms` : t(language, "الزمن غير متاح", "latency unavailable")} · ${n(layer.results, language)} ${t(language, "نتيجة", "results")}`}
                </small>
                {layer.enabled && layer.ok === false && <small className="lp-recall-error">{String(rec(healthTrace.errors)[name] || t(language, "انتهت المهلة أو تعذر الاتصال.", "Timed out or could not connect."))}</small>}
              </div>;
            })}
          </div>
          <p className="lp-recall-note">{t(language, "هذا فحص قراءة فقط: يرسل استعلامًا تجريبيًا عبر الـGateway ولا يضيف أو يحذف ذكريات.", "Read-only check: sends a synthetic query through the Gateway; it does not add or delete memories.")}</p>
        </Card>
      )}
      {healthError && !healthResult.data && <p className="lp-alert lp-alert-bad">{healthError}</p>}
      {searchedQuestion && q.trim() !== searchedQuestion && <p className="lp-recall-note" role="status">{t(language, "النتائج المعروضة تخص آخر بحث؛ اضغط «بحث تفاعلي» لتحديثها.", "The visible results are from your last search; run Interactive search to update them.")}</p>}
      {trace.recall && (
        <Card>
          <div className="lp-card-head">
            <div>
              <span className="lp-eyebrow">RESULTS</span>
              <h2>{t(language, "نتائج البحث", "Search results")}</h2>
            </div>
            <Pill>
              {n(visibleItems.length, language)} / {n(items.length, language)}{" "}
              {t(language, "مطابقة قوية", "strong matches")}
            </Pill>
          </div>
          <p className="lp-recall-note">
            {t(language, `أظهر البحث ${n(visibleItems.length, language)} تطابقًا قويًا من ${n(items.length, language)} مرشحًا. قد لا يسترجع البحث كل ما حُفظ عن الموضوع.`, `Search found ${n(visibleItems.length, language)} stronger matches among ${n(items.length, language)} candidates. It may not retrieve every saved detail about the topic.`)}
          </p>
          <div className={`lp-recall-coverage ${hasPartialCoverage ? "is-partial" : "is-all-available"}`} role="status" aria-live="polite">
            <strong>{hasPartialCoverage ? t(language, "قد تكون النتائج جزئية", "Results may be partial") : t(language, "استجابت مصادر الذاكرة", "Memory sources responded")}</strong>
            <span>{t(language, `استجاب ${n(respondingProviderCount, language)} من ${n(providers.length, language)} مصادر.`, `${n(respondingProviderCount, language)} of ${n(providers.length, language)} sources responded.`)} {t(language, "نعرض المطابقات التي عثرنا عليها، ولا نضمن أن البحث الدلالي استعاد كل معلومة محفوظة.", "We show the matches found; semantic search cannot guarantee that every saved detail was retrieved.")}</span>
          </div>
          {Number(trace.recall.unique_results || 0) > items.length && <p className="lp-recall-note">{t(language, `توجد نتائج إضافية لم تُعرض بعد. غيّر حد النتائج الحالي (${n(searchLimit, language)}) لعرض المزيد.`, `More results are available. Increase the current result limit (${n(searchLimit, language)}) to show more.`)}</p>}
          {!!unifiedAnswerItems.length && <section className="lp-recall-answer" aria-labelledby="lp-recall-answer-title">
            <div className="lp-recall-answer-head">
              <div><span className="lp-eyebrow">SAVED CONTEXT</span><h3 id="lp-recall-answer-title">{t(language, "نقاط الذاكرة المرتبطة", "Related memory findings")}</h3></div>
              <span className="lp-recall-answer-count">{n(unifiedAnswerItems.length, language)} {t(language, "نقاط", "points")}</span>
            </div>
            <p className="lp-recall-note">{t(language, "هذه نقاط محفوظة اختيرت لعلاقتها بسؤالك، وليست جوابًا مولّدًا. نعرضها كما وردت مع مصدرها، ونبقي المعلومات المختلفة منفصلة.", "These are saved statements selected for relevance, not an AI-generated answer. They stay in their original wording with their source; differing information remains separate.")}</p>
            <div className="lp-recall-answer-list">
              {unifiedAnswerItems.map((item, index) => <article className="lp-recall-answer-item" key={String(item.id || `answer-${index}`)}>
                <span className="lp-recall-answer-index">{n(index + 1, language)}</span>
                <div className="lp-recall-answer-content">
                  <p dir="auto">{customerMemoryText(item.display_text || item.text)}</p>
                  <div className="lp-recall-result-meta">
                    <span className="lp-recall-provenance">{memorySourceLabel(item.source)}{memoryDateLabel(item.date) ? ` · ${memoryDateLabel(item.date)}` : ""}</span>
                    {answerLayers(item).map((layer) => <span className="lp-recall-tag" key={layer}>{layer}</span>)}
                  </div>
                </div>
              </article>)}
            </div>
            <p className="lp-recall-answer-foot">{hasPartialCoverage
              ? t(language, "هذه خلاصة جزئية لأن بعض مصادر الذاكرة لم تستجب. افتح تفاصيل المصادر أدناه لمراجعة ما وصل منها.", "This is a partial view because some memory sources did not respond. Open the source details below to review the results that did arrive.")
              : t(language, "هذه خلاصة للنقاط التي عثر عليها البحث، وليست تأكيدًا بأن كل ما حُفظ عن الموضوع قد استُرجع.", "This summarizes the matches found; it does not guarantee that every saved detail about the topic was retrieved.")}</p>
          </section>}
          <section className="lp-recall-answer-draft" aria-labelledby="lp-recall-answer-draft-title">
            <div className="lp-recall-answer-head">
              <div>
                <span className="lp-eyebrow">GROUNDED ANSWER</span>
                <h3 id="lp-recall-answer-draft-title">{t(language, "صياغة جواب واحد من الذاكرة", "Draft one answer from memory")}</h3>
              </div>
              {answerData && <Pill tone="good">{t(language, "مرتبط بمصادر", "Source-linked")}</Pill>}
            </div>
            {!answerData && <>
              <p className="lp-recall-note">{t(language, "نوصي بجواب واحد واضح، مع إبقاء الأدلة الأصلية قابلة للمراجعة. إذا اختلفت الذكريات، نعرض الاختلاف بدل اختيار رواية من عندنا.", "A single clear answer is easiest to use, while keeping the original evidence available. If memories differ, the draft should show the difference instead of choosing a version for you.")}</p>
              {answerOptions.available && answerUsesRemote && <label className="lp-recall-consent">
                <input type="checkbox" checked={externalAnswerConsent} onChange={(event) => setExternalAnswerConsent(event.target.checked)} />
                <span>{t(language, `أوافق على إرسال سؤالي وما يصل إلى 8 ذكريات مرتبطة به إلى ${String(answerOptions.destination || "مزوّد خارجي")} لصياغة الجواب.`, `I agree to send my question and up to 8 related memories to ${String(answerOptions.destination || "an external provider")} to draft the answer.`)}{answerOptions.may_cost === true ? t(language, " قد تُطبق تكلفة حسب إعدادات المزوّد.", " Charges may apply under the provider settings.") : ""}</span>
              </label>}
              {answerOptions.available && !answerUsesRemote && <p className="lp-recall-privacy-note">{t(language, "سيُعالج السؤال والذكريات المختارة على هذا الجهاز عبر النموذج المحلي المضبوط. لا تُحفظ مسودة الجواب.", "The question and selected memories will be processed on this device using the configured local model. The draft is not saved.")}</p>}
              {!answerIsAvailable && <p className="lp-recall-note">{t(language, "صياغة الإجابة غير متاحة بإعداد النموذج الحالي؛ تقدر تستخدم نقاط الذاكرة ومصادرها أدناه.", "Answer drafting is unavailable with the current model settings; you can still use the memory findings and their sources below.")}</p>}
              {!hasAnswerEvidence && <p className="lp-recall-note">{t(language, "ما فيه ذكريات قوية مرتبطة بهذا السؤال تكفي لصياغة جواب. راجع المطابقات المحتملة أو جرّب صياغة أدق.", "There are no strong related memories to support a draft. Review possible matches or try a more specific question.")}</p>}
              {answerError && <p className="lp-alert lp-alert-bad" role="status">{answerError}</p>}
              <Button onClick={generateAnswer} disabled={!answerIsAvailable || !hasAnswerEvidence || answerBusy || q.trim() !== searchedQuestion || (answerUsesRemote && !externalAnswerConsent)}>
                <Sparkles size={16} />
                {answerBusy ? t(language, "يصيغ الجواب…", "Drafting answer…") : t(language, "صياغة جواب مع المصادر", "Draft answer with sources")}
              </Button>
            </>}
            {answerData && <>
              <p className="lp-recall-generated-answer" dir="auto">{String(answerData.answer || "")}</p>
              <p className="lp-recall-privacy-note">{t(language, "هذه مسودة آلية من الذكريات المسترجعة، وليست ضمانًا بصحة كل معلومة أو اكتمالها. راجع الأدلة الأصلية قبل الاعتماد عليها. لم تُحفظ المسودة.", "This is an AI-generated draft based on retrieved memories, not a guarantee that every claim is correct or complete. Review the original evidence before relying on it. The draft was not saved.")}</p>
              <div className="lp-recall-answer-evidence">
                <strong>{t(language, "الأدلة المستخدمة", "Evidence used")}</strong>
                {arr(answerData.references).filter((reference) => arr(answerData.citations).includes(reference.index)).map((reference) => <article className="lp-recall-answer-evidence-item" key={reference.index}>
                  <span className="lp-recall-answer-index">{n(reference.index, language)}</span>
                  <div><p dir="auto">{customerMemoryText(reference.text)}</p><small>{memorySourceLabel(reference.source)}{memoryDateLabel(reference.date) ? ` · ${memoryDateLabel(reference.date)}` : ""}</small></div>
                </article>)}
                {!arr(answerData.citations).length && <p className="lp-recall-note">{t(language, "ما أرجع النموذج بمصادر محددة لهذا النص؛ تعامل معه بحذر وراجع النقاط الأصلية.", "The model did not identify specific sources for this text; treat it cautiously and review the original findings.")}</p>}
              </div>
              <Button variant="secondary" onClick={() => { setAnswerData(null); setAnswerError(""); }}>{t(language, "إخفاء الجواب", "Hide answer")}</Button>
            </>}
          </section>
          {!!visiblePossibleItems.length && <section className="lp-recall-possible" aria-label={t(language, "مطابقات محتملة", "Possible matches")}>
            <Button variant="secondary" onClick={() => setShowPossibleMatches((value) => !value)} aria-expanded={showPossibleMatches}>
              {showPossibleMatches ? t(language, "إخفاء المطابقات المحتملة", "Hide possible matches") : t(language, `عرض ${n(visiblePossibleItems.length, language)} مطابقات محتملة`, `Review ${n(visiblePossibleItems.length, language)} possible matches`)}
            </Button>
            {showPossibleMatches && <>
              <p className="lp-recall-note">{t(language, "هذه النتائج أقل صلة بالسؤال وفق ترتيب البحث؛ أبقيناها للمراجعة ولم ندخلها في الخلاصة الموحدة.", "These candidates ranked as less relevant to the query, so they are available to inspect but excluded from the unified summary.")}</p>
              {visiblePossibleItems.map((item, index) => <article className="lp-recall-possible-item" key={String(item.id || `possible-${index}`)}>
                <p dir="auto">{customerMemoryText(item.display_text || item.text)}</p>
                <small>{memorySourceLabel(item.source)}{memoryDateLabel(item.date) ? ` · ${memoryDateLabel(item.date)}` : ""}</small>
              </article>)}
            </>}
          </section>}
          <div className="lp-provider-strip">
            {["openmemory", "graphiti", "mempalace"].map((name) => (
              <span
                key={name}
                className={providerTrace[name]?.ok ? "is-ok" : "is-bad"}
              >
                {name === "openmemory" ? t(language, "حقائق وسياق", "Facts & context") : name === "graphiti" ? t(language, "علاقات وأحداث", "Relations & events") : t(language, "نصوص محفوظة", "Saved texts")}:{" "}
                {providerTrace[name]?.ok
                  ? providerTrace[name]?.partial ? t(language, "جزئي", "partial") : t(language, "سليم", "ok")
                  : t(language, "فشل", "failed")}{" "}
                · {n(arr(providerTrace[name]?.items).filter((item) => visibleTextKeys.has(memoryTextKey(item))).length, language)}
              </span>
            ))}
          </div>
          <div className="lp-recall-layer-grid">
            {providers.map((name) => {
              const rawLayer = rec(providerTrace[name]);
              const layerItems = arr(rawLayer.items).filter((item) => visibleTextKeys.has(memoryTextKey(item)));
              const layer: R = { ...rawLayer, results: Array.isArray(rawLayer.items) ? layerItems.length : rawLayer.results };
              const state = layerState(layer);
              const layerName = name === "openmemory" ? t(language, "الحقائق والسياق", "Facts & context") : name === "mempalace" ? t(language, "النصوص المحفوظة", "Saved texts") : t(language, "العلاقات والأحداث", "Relations & events");
              const role = name === "openmemory" ? t(language, "معلومات موجزة عنك", "Concise information about you") : name === "graphiti" ? t(language, "روابط بين الأشخاص والمواضيع والأحداث", "Connections between people, topics, and events") : t(language, "المحادثات والملفات التي حُفظت", "Saved conversations and files");
              return <details className="lp-recall-layer" key={name}>
                <summary>
                  <span className="lp-recall-layer-title"><strong>{layerName}</strong><small>{role}</small></span>
                  <span className="lp-recall-layer-meta"><span className={`lp-recall-badge is-${state.tone}`}>{state.label}</span><small>{layer.enabled === false ? "—" : layer.latency_ms != null ? `${n(layer.latency_ms, language)} ms` : t(language, "الزمن غير متاح", "latency unavailable")}</small></span>
                </summary>
                {layer.enabled !== false && layer.ok === false && <p className="lp-recall-note">{t(language, "تعذّر الوصول إلى مجموعة المعلومات هذه الآن. أعد المحاولة لاحقًا؛ وبقية النتائج ما زالت متاحة.", "This information group could not be reached right now. Try again later; other results remain available.")}</p>}
                {layer.ok && !Array.isArray(layer.items) && <p className="lp-recall-note">{t(language, "تعذّر عرض تفاصيل هذه المجموعة الآن، لكن نتائج المجموعات الأخرى ما زالت متاحة.", "Details for this group are unavailable right now, but results from the other groups are still available.")}</p>}
                {layer.ok && Array.isArray(layer.items) && !layerItems.length && <p className="lp-recall-note">{t(language, "الاتصال ناجح، لكن لم تُرجع الطبقة نتيجة لهذا الاستعلام.", "Connected, but this layer returned no match for this query.")}</p>}
                {layerItems.map((item, index) => {
                  const entities = entitiesFor(item);
                  const provenance = `${memorySourceLabel(item.source)}${memoryDateLabel(item.date) ? ` · ${memoryDateLabel(item.date)}` : ""}`;
                  return <article className="lp-recall-layer-result" key={String(item.id || `${name}-${index}`)}>
                    <p>{customerMemoryText(item.display_text || item.text)}</p>
                    <div className="lp-recall-result-meta">
                      {provenance && <span className="lp-recall-provenance">{provenance}</span>}
                      {entities.map((entity) => <span className="lp-recall-entity" key={entity}>{entity}</span>)}
                    </div>
                  </article>;
                })}
              </details>;
            })}
          </div>
          {!Object.keys(providerTrace).length && <p className="lp-recall-note">{t(language, "تفاصيل مجموعات البحث غير متاحة الآن؛ ستظل النتائج التي عُثر عليها ظاهرة هنا.", "Search group details are unavailable right now; found results will still appear here.")}</p>}
        </Card>
      )}
      {trace.context !== undefined && (
        <Card>
          <div className="lp-card-head lp-recall-preview-head">
            <div>
              <span className="lp-eyebrow">ANSWER CONTEXT</span>
              <h2>{t(language, "ما سيصل إلى المساعد", "What the assistant receives")}</h2>
            </div>
            <div className="lp-recall-inline-actions">
              <Button variant="secondary" onClick={() => setPreviewContext((value) => !value)}>
                {previewContext ? t(language, "إخفاء المعاينة", "Hide preview") : t(language, "معاينة السياق المدمج", "Preview injected context")}
              </Button>
              {previewContext && <Button variant="secondary" onClick={() => {
                void navigator.clipboard?.writeText(String(trace.context || "")).then(() => {
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 1600);
                });
              }}>
                <Copy size={15} />{copied ? t(language, "نُسخ", "Copied") : t(language, "نسخ السياق", "Copy context")}
              </Button>}
            </div>
          </div>
          {previewContext && <>
            <pre className="lp-recall-context" dir="auto">{customerMemoryText(trace.context || t(language, "لا توجد ذكريات مسترجعة لهذا الاستعلام.", "No memories were retrieved for this query."))}</pre>
            <p className="lp-recall-note">{t(language, "هذه خلاصة المعلومات التي يعيدها Link Memory للمساعد. قد يضيف التطبيق الذي تستخدمه تعليماته الخاصة قبل إرسالها للنموذج.", "This is the information summary Link Memory returns to the assistant. The app you use may add its own instructions before sending it to the model.")}</p>
          </>}
        </Card>
      )}
      {!busy && searchedQuestion && q.trim() === searchedQuestion && !visibleItems.length && !error && (
        <Card>
          <p className="lp-empty">
            {t(
              language,
              items.length && !trustedItems.length ? "لم تظهر مطابقة قوية لهذا السؤال. يمكنك مراجعة المرشحات المحتملة أعلاه، أو تجربة صياغة أخرى." : items.length ? "لا توجد نتائج تطابق الفلاتر الحالية." : "لم أجد ذاكرة مرتبطة بهذا السؤال.",
              items.length && !trustedItems.length ? "No strong match was found. Review the possible matches above or try another phrasing." : items.length ? "No results match the current filters." : "No related memory was found.",
            )}
          </p>
        </Card>
      )}
          {visibleItems.map((x, i) => (
        <Card key={String(x.id || i)}>
          <div className="lp-card-head">
            <Pill>{memoryKindLabel(x.type)}</Pill>
            <small>
              {memorySourceLabel(x.source)}{" "}
              {memoryDateLabel(x.date) ? `· ${memoryDateLabel(x.date)}` : ""}
            </small>
          </div>
          <h3 dir="auto">{customerMemoryText(x.display_text || x.text)}</h3>
          {x.display_language && trace.query_language && x.display_language !== trace.query_language && <details className="lp-recall-note">
            <summary>{t(language, "تعذرت الصياغة بلغة البحث؛ هذا هو النص المحفوظ بلغته الأصلية.", "A query-language version is not available; showing the saved wording in its original language.")}</summary>
            <p dir="auto">{customerMemoryText(x.text)}</p>
          </details>}
        </Card>
      ))}
    </div>
  );
}
