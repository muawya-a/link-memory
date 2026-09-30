import { useEffect, useState } from "react";
import { Download, Grid2X2, Languages, Moon, Network, Search, Settings2, Sun } from "lucide-react";
import { Button, Lang, Page, t } from "./features/shared";
import { Overview } from "./features/overview/Overview";
import { Recall } from "./features/recall/Recall";
import { Operations } from "./features/operations/Operations";
import { Layers } from "./features/layers/Layers";
import { Settings } from "./features/settings/Settings";

const nav = [
  ["overview", "النظرة العامة", "Overview", Grid2X2],
  ["recall", "البحث والاسترجاع", "Recall", Search],
  ["operations", "العمليات", "Operations", Download],
  ["layers", "طبقات الذاكرة", "Memory layers", Network],
  ["settings", "الإعدادات", "Settings", Settings2],
] as const;
const customerPages: Page[] = ["overview", "recall"];
const operatorPages: Page[] = ["operations", "layers", "settings"];
function Layout({ page, go, language, setLanguage, theme, setTheme, children }: any) {
  return (
    <div dir={language === "ar" ? "rtl" : "ltr"} className={`lp-app ${theme}`}>
      <a className="lp-skip-link" href="#main-content">
        {t(language, "تخطى إلى المحتوى الرئيسي", "Skip to main content")}
      </a>
      <aside className="lp-sidebar">
        <div className="lp-brand">
          <span className="lp-brand-mark">
            <i />
            <i />
            <i />
          </span>
          <div>
            <strong>Link Memory</strong>
            <small>
              {t(language, "مركز الذاكرة المحلي", "Local memory hub")}
            </small>
          </div>
        </div>
        <nav className="lp-nav">
          <div className="lp-nav-group">
            <span className="lp-nav-heading">{t(language, "مساحة العميل", "Customer space")}</span>
            {nav.filter(([id]) => customerPages.includes(id)).map(([id, ar, en, Icon]) => (
              <button
                key={id}
                aria-current={page === id ? "page" : undefined}
                className={page === id ? "active" : ""}
                onClick={() => go(id)}
              >
                <Icon size={18} />
                <span>{t(language, ar, en)}</span>
              </button>
            ))}
          </div>
          <div className="lp-nav-group lp-nav-group-operator">
            <span className="lp-nav-heading">{t(language, "أدوات مساحة العمل المحلية", "Local workspace tools")}</span>
            {nav.filter(([id]) => operatorPages.includes(id)).map(([id, ar, en, Icon]) => (
              <button
                key={id}
                aria-current={page === id ? "page" : undefined}
                className={page === id ? "active" : ""}
                onClick={() => go(id)}
              >
                <Icon size={18} />
                <span>{t(language, ar, en)}</span>
              </button>
            ))}
          </div>
        </nav>
        <div className="lp-sidebar-footer">
          <span className="lp-status-dot" />
          {t(language, "يعمل محليًا", "Running locally")}
        </div>
      </aside>
      <header className="lp-topbar">
        <div className="lp-top-actions">
          <button
            type="button"
            className="lp-button lp-secondary lp-theme-toggle"
            aria-label={theme === "dark"
              ? t(language, "تفعيل المظهر الفاتح", "Switch to light mode")
              : t(language, "تفعيل المظهر الداكن", "Switch to dark mode")}
            aria-pressed={theme === "dark"}
            title={theme === "dark"
              ? t(language, "المظهر الفاتح", "Light appearance")
              : t(language, "المظهر الداكن", "Dark appearance")}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Sun size={17} aria-hidden="true" /> : <Moon size={17} aria-hidden="true" />}
            <span>{theme === "dark"
              ? t(language, "فاتح", "Light")
              : t(language, "داكن", "Dark")}</span>
          </button>
          <Button
            variant="secondary"
            onClick={() => setLanguage(language === "ar" ? "en" : "ar")}
          >
            <Languages size={17} />
            {language === "ar" ? "English" : "العربية"}
          </Button>
        </div>
      </header>
      <main id="main-content" className="lp-main">
        {operatorPages.includes(page) && (
          <aside className="lp-local-tools-note" role="note">
            {t(
              language,
              "هذه أدوات تشغيل لمساحة العمل المحلية. لا يفرض هذا التنقل صلاحيات دخول أو حماية منفصلة.",
              "These are operational tools for the local workspace. This navigation does not enforce sign-in permissions or separate access protection.",
            )}
          </aside>
        )}
        {children}
      </main>
    </div>
  );
}
export function App() {
  const [page, setPage] = useState<Page>(() => {
    const x = location.hash.slice(1) as Page;
    return nav.some((v) => v[0] === x) ? x : "overview";
  });
  const [language, setLanguage] = useState<Lang>(
    () => (localStorage.getItem("link-memory-language") as Lang) || "ar",
  );
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (localStorage.getItem("link-memory-theme") as "light" | "dark") || "light",
  );
  useEffect(() => {
    localStorage.setItem("link-memory-language", language);
    document.documentElement.lang = language;
    document.documentElement.dir = language === "ar" ? "rtl" : "ltr";
  }, [language]);
  useEffect(() => {
    localStorage.setItem("link-memory-theme", theme);
    document.documentElement.style.colorScheme = theme;
  }, [theme]);
  useEffect(() => {
    const f = () => {
      const x = location.hash.slice(1) as Page;
      if (nav.some((v) => v[0] === x)) setPage(x);
    };
    addEventListener("hashchange", f);
    return () => removeEventListener("hashchange", f);
  }, []);
  const go = (p: Page) => {
    location.hash = p;
    setPage(p);
  };
  return (
    <Layout page={page} go={go} language={language} setLanguage={setLanguage} theme={theme} setTheme={setTheme}>
      {page === "overview" ? (
        <Overview language={language} go={go} />
      ) : page === "recall" ? (
        <Recall language={language} />
      ) : page === "operations" ? (
        <Operations language={language} />
      ) : page === "layers" ? (
        <Layers language={language} />
      ) : (
        <Settings language={language} />
      )}
    </Layout>
  );
}
