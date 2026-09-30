import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Download, FileSearch, ListChecks, RefreshCw } from "lucide-react";
import { api, post } from "../../api";
import { t, n, arr, rec, formatTime, statusText, Button, Card, Pill, Lang, R } from "../shared";

export function Operations({ language }: { language: Lang }) {
  const [d, setD] = useState<R>({});
  const [notice, setNotice] = useState("");
  const [health, setHealth] = useState<R>({});
  const [busy, setBusy] = useState(false);
  const [showAllAnalysisJobs, setShowAllAnalysisJobs] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [importProgress, setImportProgress] = useState<number | null>(null);
  const [importStage, setImportStage] = useState<"" | "reading" | "sending" | "done">("");
  const importInput = useRef<HTMLInputElement>(null);
  const reload = useCallback(async () => {
    const [a, b, c, r, k, monitoring, analysis] = await Promise.all([
      api("/v1/captures?limit=50"),
      api("/v1/review"),
      api("/v1/conflicts?status=open"),
      api("/v1/retry"),
      api("/v1/backups"),
      api("/v1/monitoring").catch(() => ({})),
      api("/v1/analysis/status"),
    ]);
    setD({
      a: arr(rec(a).captures),
      b: arr(rec(b).review),
      c: arr(rec(c).conflicts),
      r: rec(r),
      k: arr(rec(k).backups),
      monitoring: rec(monitoring),
      analysis: rec(analysis),
    });
  }, []);
  useEffect(() => {
    void reload().catch((error) =>
      setNotice(error instanceof Error ? error.message : "تعذر تحميل العمليات"),
    );
  }, [reload]);
  useEffect(() => {
    let active = true;
    let inFlight = false;
    const timer = window.setInterval(() => {
      if (!active || inFlight) return;
      inFlight = true;
      void reload().catch(() => undefined).finally(() => { inFlight = false; });
    }, 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [reload]);
  const importFiles = async (files: File[]) => {
    if (!files.length) return;
    setBusy(true);
    setNotice("");
    setImportProgress(0);
    setImportStage("reading");
    try {
      const totalBytes = Math.max(1, files.reduce((sum, file) => sum + file.size, 0));
      const readBytes = new Map<string, number>();
      const encoded = await Promise.all(
        files.map(
          (file) =>
            new Promise<R>((resolve, reject) => {
              const reader = new FileReader();
              const fileKey = `${file.name}:${file.size}`;
              reader.onprogress = (event) => {
                if (!event.lengthComputable) return;
                readBytes.set(fileKey, event.loaded);
                const loaded = Array.from(readBytes.values()).reduce((sum, value) => sum + value, 0);
                setImportProgress(Math.min(100, Math.round((loaded / totalBytes) * 100)));
              };
              reader.onload = () =>
                resolve({
                  name: file.name,
                  type: file.type,
                  data: String(reader.result || ""),
                });
              reader.onerror = () => reject(new Error(file.name));
              reader.readAsDataURL(file);
            }),
        ),
      );
      setImportProgress(100);
      setImportStage("sending");
      const result = await post<R>("/v1/import", {
        files: encoded,
        source: "pc-file",
        delete_after_success: false,
      });
      const processed = Number(result.processed || 0);
      const queued = arr(result.results).filter((item) => item.status === "queued").length;
      const chunks = arr(result.results).reduce((sum, item) => sum + Number(item.chunks_total || item.analysis_chunks || 0), 0);
      setImportStage("done");
      setNotice(`${t(language, "انتهى الاستيراد", "Import finished")}: ${n(result.files_read ?? result.total ?? files.length, language)} ${t(language, "ملف مقروء", "files read")} · ${n(processed, language)} ${t(language, "مهمة مستلمة", "tasks accepted")} · ${n(queued, language)} ${t(language, "في الطابور", "queued")}${chunks ? ` · ${n(chunks, language)} ${t(language, "مقطع تحليل", "analysis chunks")}` : ""}.`);
      setSelectedFiles([]);
      if (importInput.current) importInput.current.value = "";
      await reload();
    } catch (error) {
      setImportStage("");
      setImportProgress(null);
      setNotice(
        `${t(language, "فشل الاستيراد", "Import failed")}: ${error instanceof Error ? error.message : "unknown error"}`,
      );
    } finally {
      setBusy(false);
    }
  };
  const runHealth = async () => {
    setBusy(true);
    try {
      const result = await post<R>("/v1/health/check", {});
      setHealth(result);
      setNotice(
        t(
          language,
          "اكتمل الفحص؛ النتائج ظاهرة أدناه.",
          "Health check complete; results are shown below.",
        ),
      );
    } catch (error) {
      setNotice(
        `${t(language, "فشل فحص الصحة", "Health check failed")}: ${error instanceof Error ? error.message : "unknown error"}`,
      );
    } finally {
      setBusy(false);
    }
  };
  const analysisJobs = arr(d.monitoring?.jobs);
  const prioritizedAnalysisJobs = [...analysisJobs].sort((a, b) => {
    const priority = (job: R) => ["failed", "needs_review"].includes(String(job.status).toLowerCase()) ? 0 : String(job.status).toLowerCase() === "running" ? 1 : String(job.status).toLowerCase() === "queued" ? 2 : 3;
    return priority(a) - priority(b) || String(b.created_at || "").localeCompare(String(a.created_at || ""));
  });
  const visibleAnalysisJobs = showAllAnalysisJobs ? prioritizedAnalysisJobs : prioritizedAnalysisJobs.slice(0, 5);
  const analysisSummary = {
    running: analysisJobs.filter((job) => String(job.status).toLowerCase() === "running").length,
    queued: analysisJobs.filter((job) => String(job.status).toLowerCase() === "queued").length,
    needsAttention: analysisJobs.filter((job) => ["failed", "needs_review"].includes(String(job.status).toLowerCase())).length,
    completed: analysisJobs.filter((job) => String(job.status).toLowerCase() === "completed").length,
  };
  return (
    <div className="lp-stack">
      <section className="lp-hero">
        <div>
          <span className="lp-eyebrow">OPERATIONS</span>
          <h2>{t(language, "العمليات", "Operations")}</h2>
          <p>
            {t(
              language,
              "الاستيراد، المراجعة، الطابور، الصحة والنسخ الاحتياطية.",
              "Import, review, retry, health, and backups.",
            )}
          </p>
        </div>
        <Button variant="secondary" onClick={() => void reload()}>
          <RefreshCw size={17} />
          {t(language, "تحديث", "Refresh")}
        </Button>
      </section>
      <section className="lp-bento-grid">
        {[
          [t(language, "سجل الالتقاط", "Capture log"), d.a?.length],
          [t(language, "المراجعة", "Review"), d.b?.length],
          [t(language, "التعارضات", "Conflicts"), d.c?.length],
          [t(language, "إعادة المحاولة", "Retry queue"), d.r?.ready],
          [t(language, "النسخ الاحتياطية", "Backups"), d.k?.length],
        ].map(([x, v]) => (
          <Card key={String(x)}>
            <span className="lp-eyebrow">{x}</span>
            <h2>{n(v, language)}</h2>
          </Card>
        ))}
      </section>
      <Card>
        <div className="lp-card-head">
          <div>
            <span className="lp-eyebrow">HEALTH</span>
            <h2>{t(language, "فحص الصحة", "Health check")}</h2>
          </div>
          <Activity size={20} />
        </div>
        <Button disabled={busy} onClick={() => void runHealth()}>
          <Activity size={17} />
          {t(language, "تشغيل الفحص", "Run health check")}
        </Button>
        {notice && (
          <p className="lp-muted" role="status">
            {notice}
          </p>
        )}
        {arr(health.services).length > 0 && (
          <div className="lp-health-results" aria-live="polite">
            {arr(health.services).map((service, index) => (
              <div key={index}>
                <strong>{String(service.service)}</strong>
                <Pill tone={service.state === "disabled" ? "muted" : service.ok ? "good" : "bad"}>
                  {service.state === "disabled" || service.state === "standby"
                    ? service.state === "standby" ? t(language, "استعداد", "Standby") : t(language, "غير مفعّل", "Disabled")
                    : service.ok
                      ? t(language, "يعمل", "Working")
                      : t(language, "فشل", "Failed")}
                </Pill>
                <small>
                  {service.latency_ms !== undefined
                    ? `${n(service.latency_ms, language)} ms · ${String(service.state || "")}`
                    : String(service.detail || "")}
                </small>
                {(() => {
                  try {
                    const detail = typeof service.detail === "string" ? JSON.parse(service.detail) : service.detail;
                    return detail?.error ? <small className="lp-recall-error">{String(detail.error)}</small> : null;
                  } catch { return null; }
                })()}
              </div>
            ))}
          </div>
        )}
      </Card>
      <Card>
        <div className="lp-card-head">
          <div>
            <span className="lp-eyebrow">IMPORT</span>
            <h2>{t(language, "استيراد ملف", "Import file")}</h2>
          </div>
          <FileSearch size={20} />
        </div>
        <p className="lp-muted">
          {t(
            language,
            "يدعم JSON وPDF وWord والنصوص من الكمبيوتر.",
            "Supports JSON, PDF, Word, and text from the PC.",
          )}
        </p>
        <input
          ref={importInput}
          className="lp-visually-hidden"
          disabled={busy}
          id="memory-file-import"
          aria-hidden="true"
          tabIndex={-1}
          type="file"
          multiple
          accept=".json,.pdf,.docx,.txt,.md"
          onChange={(event) => {
            const files = Array.from(event.target.files || []);
            setSelectedFiles(files);
            setNotice(
              files.length
                ? `${t(language, "تم اختيار", "Selected")}: ${n(files.length, language)} ${t(language, "ملف. اضغط استيراد الملفات للمتابعة.", "file(s). Press Import files to continue.")}`
                : "",
            );
          }}
        />
        <div className="lp-import-actions">
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => importInput.current?.click()}
          >
            <FileSearch size={17} />
            {t(language, "اختيار ملفات", "Choose files")}
          </Button>
          <Button
            disabled={busy || selectedFiles.length === 0}
            onClick={() => void importFiles(selectedFiles)}
          >
            <Download size={17} />
            {busy
              ? t(language, "جارٍ الاستيراد…", "Importing…")
              : t(language, "استيراد الملفات", "Import files")}
          </Button>
        </div>
        {importStage && (
          <div className="lp-import-progress" role="status" aria-live="polite">
            <div className="lp-card-head">
              <strong>{importStage === "reading" ? t(language, "قراءة الملفات محليًا", "Reading files locally") : importStage === "sending" ? t(language, "إرسال الطلب إلى Gateway", "Sending request to Gateway") : t(language, "اكتمل الاستيراد", "Import complete")}</strong>
              {importStage === "reading" && <span>{n(importProgress || 0, language)}%</span>}
            </div>
            <div className={`lp-progress-track ${importStage === "sending" ? "is-indeterminate" : ""}`}>
              <span style={{ width: importStage === "sending" ? "38%" : `${importProgress || 0}%` }} />
            </div>
            <small>{importStage === "sending" ? t(language, "واجهة Gateway الحالية لا ترسل تقدم المعالجة أو عدد الأجزاء أثناء الطلب؛ لا نعرض نسبة مختلقة.", "The current Gateway API does not stream processing progress or chunk counts; no estimated percentage is shown.") : importStage === "done" ? t(language, "تم عرض عدد الملفات والمهام الفعلي في إشعار النتيجة.", "Actual file and task counts are shown in the result notice.") : t(language, "هذه نسبة قراءة الملف في المتصفح فقط، وليست نسبة معالجة الخادم.", "This is browser file-read progress only, not server processing progress.")}</small>
          </div>
        )}
        {selectedFiles.length > 0 && (
          <ul className="lp-import-selected" aria-label={t(language, "الملفات المختارة", "Selected files")}>
            {selectedFiles.map((file) => (
              <li key={`${file.name}-${file.size}`}>{file.name}</li>
            ))}
          </ul>
        )}
      </Card>
      <Card>
        <div className="lp-card-head lp-processing-head">
          <div><span className="lp-eyebrow">{t(language, "متابعة الحفظ", "MEMORY STATUS")}</span><h2>{t(language, "حالة معلوماتك", "Your information status")}</h2></div>
          <span className="lp-processing-icon"><ListChecks size={19} /></span>
        </div>
        <p className="lp-processing-intro">{t(language, "تابع ما وصل، وما يجري تجهيزه، وما حُفظ أو يحتاج انتباهك. تتحدث الحالات تلقائيًا.", "See what arrived, what is being prepared, and what was saved or needs your attention. Status updates automatically.")}</p>
        {analysisJobs.length > 0 && <>
          <div className="lp-processing-summary" aria-label={t(language, "ملخص المهام المعروضة", "Summary of displayed tasks")}>
            <div className="lp-processing-stat is-active">
              <strong>{n(analysisSummary.running, language)}</strong>
              <span>{t(language, "قيد المعالجة", "In progress")}</span>
              <small className="lp-processing-waiting">{n(analysisSummary.queued, language)} {t(language, "بانتظار البدء", "waiting to start")}</small>
            </div>
            <div className="lp-processing-stat is-attention">
              <strong>{n(analysisSummary.needsAttention, language)}</strong>
              <span>{t(language, "تحتاج انتباهك", "Needs your attention")}</span>
            </div>
            <div className="lp-processing-stat is-complete">
              <strong>{n(analysisSummary.completed, language)}</strong>
              <span>{t(language, "اكتملت", "Completed")}</span>
            </div>
          </div>
            <small className="lp-processing-scope">{t(language, "تتحدث هذه الأعداد تلقائيًا، وتظهر العناصر التي تحتاج انتباهك أولًا.", "Counts update automatically; items needing your attention appear first.")}</small>
        </>}
        <div className="lp-job-list">
            {analysisJobs.length ? visibleAnalysisJobs.map((job) => {
              const status = String(job.status || "unknown");
              const stage = String(job.stage || (status === "running" ? "analyzing" : status));
              const stageOrder: Record<string, number> = { queued: 0, filtering: 1, analyzing: 2, embedding: 3, distributing: 4, completed: 5 };
              const activeStage = stageOrder[stage] ?? -1;
              const saved = Number(job.saved_count || 0) > 0;
              const normalizedStatus = status.toLowerCase();
              const sourceValue = String(job.source || "").toLowerCase();
              const sourceLabel: Record<string, string> = {
                codex: t(language, "Codex", "Codex"), chatgpt: t(language, "ChatGPT", "ChatGPT"),
                claude: t(language, "Claude", "Claude"), gemini: t(language, "Gemini", "Gemini"),
                grok: t(language, "Grok", "Grok"), hermes: t(language, "Hermes", "Hermes"),
                "pc-file": t(language, "ملف من جهازك", "File from your device"),
              };
              const source = sourceLabel[sourceValue] || t(language, "مصدر آخر", "Other source");
              const statusMessage = normalizedStatus === "running"
                ? t(language, "نعالج المحتوى الآن.", "Your content is being processed.")
                : normalizedStatus === "queued"
                  ? t(language, "ستبدأ المعالجة تلقائيًا عند توفر دورها.", "Processing will start automatically when its turn arrives.")
                  : normalizedStatus === "needs_review"
                    ? t(language, "تحتاج هذه المعلومة إلى مراجعتك قبل اعتمادها.", "This information needs your review before it can be confirmed.")
                    : normalizedStatus === "failed"
                      ? t(language, "تعذرت المعالجة. يمكنك إعادة المحاولة.", "Processing did not finish. You can try again.")
                      : normalizedStatus === "completed" && !saved
                        ? t(language, "اكتملت المراجعة ولم تُضف معلومة جديدة هذه المرة.", "Review is complete; no new information was added this time.")
                        : normalizedStatus === "completed"
                          ? t(language, "اكتملت المعالجة وحُفظت المعلومات المناسبة.", "Processing is complete and relevant information was saved.")
                          : t(language, "حالة هذه المهمة غير متاحة حاليًا.", "The current status is unavailable.");
              return (
                <div className="lp-job-row" key={String(job.id)}>
                  <div className="lp-job-title">
                    <div className="lp-job-source"><span className="lp-job-source-mark"><ListChecks size={15} /></span><div><strong>{source}</strong><small>{formatTime(job.created_at, language)}</small></div></div>
                    <Pill tone={normalizedStatus === "completed" ? "good" : normalizedStatus === "failed" ? "bad" : normalizedStatus === "needs_review" ? "warn" : "muted"}>{statusText(status, language)}</Pill>
                  </div>
                  <p className={`lp-job-message is-${normalizedStatus}`}>{statusMessage}</p>
                  <details className="lp-job-details">
                    <summary>{t(language, "عرض تفاصيل ما تم", "See what happened")}</summary>
                    <div className="lp-job-steps" aria-label={t(language, "مراحل معالجة المعلومة", "Information processing steps")}>
                    {[
                      ["received", t(language, "وصلت", "Received"), 0],
                      ["filtering", t(language, "تجهيز", "Preparing"), 1],
                      ["analyzing", t(language, "استخراج المفيد", "Finding what matters"), 2],
                      ["embedding", t(language, "حفظ وربط", "Saving and linking"), 3],
                      ["distributing", saved ? t(language, "اكتملت", "Complete") : t(language, "لا جديد للحفظ", "Nothing new to save"), 4],
                    ].map(([key, label, order]) => (
                      <span key={String(key)} className={activeStage > Number(order) || status === "completed" ? "is-complete" : activeStage === Number(order) && status === "running" ? "is-active" : ""}>
                        {String(label)}
                      </span>
                    ))}
                    </div>
                  </details>
                  {status === "failed" && Number(job.attempts) < Number(d.analysis?.retry_policy?.max_attempts || 3) && (
                    <Button variant="secondary" disabled={busy} onClick={async () => {
                      setBusy(true);
                      try {
                        await post("/v1/analysis/retry", { job_id: job.id });
                        await reload();
                        setNotice(t(language, "أُعيدت المهمة إلى الطابور.", "Job returned to the queue."));
                      } catch (error) {
                        setNotice(error instanceof Error ? error.message : t(language, "تعذرت إعادة المحاولة.", "Could not retry the job."));
                      } finally { setBusy(false); }
                    }}>
                      <RefreshCw size={15} /> {t(language, "إعادة المحاولة الآن", "Retry now")}
                    </Button>
                  )}
                </div>
            );
          }) : <div className="lp-processing-empty">
            <span className="lp-processing-icon"><ListChecks size={18} /></span>
            <div>
              <strong>{Array.isArray(d.monitoring?.series) ? t(language, "لا يوجد شيء جديد قيد المعالجة", "Nothing new is being processed") : t(language, "متابعة المعالجة غير متاحة حاليًا", "Processing updates are not available yet")}</strong>
              <p>{Array.isArray(d.monitoring?.series) ? t(language, "ستظهر هنا الرسائل والملفات الجديدة عند التقاطها، مع توضيح ما حُفظ وما يحتاج انتباهك.", "New messages and files will appear here when received, with a clear note about what was saved or needs your attention.") : t(language, "حدّث التطبيق لإظهار حالة الرسائل والملفات بعد وصولها.", "Update the app to see the status of messages and files after they arrive.")}</p>
            </div>
          </div>}
        </div>
        {analysisJobs.length > 5 && <Button variant="secondary" onClick={() => setShowAllAnalysisJobs((value) => !value)}>
          {showAllAnalysisJobs
            ? t(language, "عرض الأحدث فقط", "Show recent only")
            : t(language, `عرض كل العناصر (${n(analysisJobs.length, language)})`, `Show all items (${n(analysisJobs.length, language)})`)}
        </Button>}
      </Card>
      <Card>
        <div className="lp-card-head"><div><span className="lp-eyebrow">PROVIDER DELIVERY</span><h2>{t(language, "إعادة إرسال الطبقات الفاشلة", "Retry failed layer deliveries")}</h2></div><RefreshCw size={20} /></div>
        <div className="lp-job-list">
          {arr(d.r?.links).length ? arr(d.r.links).slice(0, 8).map((link) => (
            <div className="lp-provider-retry-row" key={`${link.provider}:${link.memory_id}`}>
              <div><strong>{link.provider === "openmemory" ? "OpenMemory" : link.provider === "graphiti" ? "Graphiti" : link.provider === "mempalace" ? "MemPalace" : t(language, "طبقة الذاكرة", "Memory layer")}</strong><small>{t(language, "تعذر الحفظ في هذه الطبقة؛ يمكنك إعادة المحاولة.", "Saving to this layer did not finish; you can retry.")}</small></div>
              <Button variant="secondary" disabled={busy} onClick={async () => {
                setBusy(true);
                try { await post("/v1/retry", { provider: link.provider, memory_id: link.memory_id }); await reload(); setNotice(t(language, "أُرسلت إعادة المحاولة إلى الطابور.", "Retry submitted to the queue.")); }
                catch (error) { setNotice(error instanceof Error ? error.message : "Retry failed"); }
                finally { setBusy(false); }
              }}>{t(language, "إعادة الإرسال", "Retry delivery")}</Button>
            </div>
          )) : <p className="lp-muted">{t(language, "لا توجد روابط فاشلة قابلة لإعادة الإرسال حاليًا.", "No failed layer deliveries are currently retryable.")}</p>}
        </div>
      </Card>
    </div>
  );
}
