export type Lang = "ar" | "en";
export type Page = "overview" | "recall" | "operations" | "layers" | "settings";
export type R = Record<string, any>;
export const t = (l: Lang, a: string, e: string) => (l === "ar" ? a : e);
export const n = (v: any, l: Lang) =>
  Number.isFinite(Number(v))
    ? new Intl.NumberFormat(l === "ar" ? "ar-SA" : "en-US").format(Number(v))
    : "—";
export const arr = (v: any): R[] => (Array.isArray(v) ? v : []);
export const rec = (v: any): R => (v && typeof v === "object" ? v : {});
export const formatTime = (value: unknown, language: Lang) => {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat(language === "ar" ? "ar-SA" : "en-US", {
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
};
export const statusText = (status: unknown, language: Lang) => {
  const value = String(status || "unknown").toLowerCase();
  if (language === "en") return value;
  const labels: Record<string, string> = {
    processed: "اكتمل", completed: "اكتمل", queued: "في الطابور", running: "يعمل",
    failed: "فشل", needs_review: "يحتاج مراجعة", discarded: "تم التجاوز",
    duplicate: "مكرر", conflict: "تعارض", paused: "متوقف مؤقتًا", unknown: "غير معروف",
  };
  return labels[value] || value;
};
export const activitySourceLabel = (value: unknown, language: Lang) => {
  const source = String(value || "").toLowerCase();
  if (source.startsWith("codex")) return "Codex";
  if (source.startsWith("chatgpt")) return "ChatGPT";
  if (source.startsWith("claude")) return "Claude";
  if (source.startsWith("gemini")) return "Gemini";
  if (source.startsWith("grok")) return "Grok";
  if (source.startsWith("hermes")) return "Hermes";
  if (["pc-file", "import"].includes(source)) return t(language, "ملف مستورد", "Imported file");
  return t(language, "مصدر آخر", "Other source");
};
export function Sparkline({ values, label }: { values: number[]; label: string }) {
  if (values.length < 2 || values.every((value) => value === 0)) return null;
  const max = Math.max(...values, 1);
  const points = values
    .map((value, index) => `${(index / (values.length - 1)) * 100},${27 - (value / max) * 23}`)
    .join(" ");
  return (
    <svg className="lp-sparkline" viewBox="0 0 100 30" role="img" aria-label={label}>
      <polyline points={points} fill="none" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function Button({
  children,
  onClick,
  disabled = false,
  variant = "primary",
  type = "button",
}: any) {
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={`lp-button lp-${variant}`}
    >
      {children}
    </button>
  );
}
export function Card({ children }: any) {
  return <section className="lp-card">{children}</section>;
}
export function Pill({ children, tone = "good" }: any) {
  return (
    <span className={`lp-pill lp-pill-${tone}`}>
      <span className="lp-status-dot" />
      {children}
    </span>
  );
}