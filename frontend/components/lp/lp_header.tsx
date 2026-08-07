import Link from "next/link";
import { useTranslation } from "../../contexts/locale_context";

// ランディングページのヘッダー（ロゴ・セクション内リンク・CTA）
// Landing page header (logo, in-page section links, CTA)
export function LpHeader() {
  const { locale, t } = useTranslation();
  return (
    <header className="lp-header">
      <div className="lp-container lp-header__inner">
        <Link href="/lp" className="lp-header__brand" aria-label={locale === "en" ? "ChatCore-AI landing page" : "ChatCore-AI ランディングページ"}>
          <span className="lp-header__brand-mark" aria-hidden="true">
            <img src="/static/favicon.png" alt="" />
          </span>
          <span className="lp-header__brand-name">ChatCore-AI</span>
        </Link>
        {/* /lp以外のページ（/help・/privacy・/terms）からも共有するため絶対パスのアンカーにする
            Use absolute-path anchors so pages other than /lp (/help, /privacy, /terms) can share this header */}
        <nav className="lp-header__nav" aria-label={locale === "en" ? "Page navigation" : "ページ内リンク"}>
          <Link href="/lp#features">{locale === "en" ? "Features" : "できること"}</Link>
          <Link href="/lp#flow">{locale === "en" ? "How it works" : "使い方"}</Link>
          <Link href="/help">{t("nav.help")}</Link>
        </nav>
        <div className="lp-header__actions">
          <Link href="/login" className="lp-btn lp-btn--ghost">
            {t("nav.login")}
          </Link>
          <Link href="/register" className="lp-btn lp-btn--primary">
            {t("lp.start")}
          </Link>
        </div>
      </div>
    </header>
  );
}
