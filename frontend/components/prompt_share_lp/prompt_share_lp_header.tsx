import Link from "next/link";
import { useTranslation } from "../../contexts/locale_context";

// プロンプト共有紹介ページのヘッダー。ブランドマークはサービス本体と同じアイコンを使う
// Header for the prompt sharing landing page, using the same icon as the service itself
export function PromptShareLpHeader() {
  const { locale, t } = useTranslation();
  return (
    <header className="lp-header">
      <div className="lp-container lp-header__inner">
        <Link
          href="/prompt_share/lp"
          className="lp-header__brand"
          aria-label={locale === "en" ? "ChatCore-AI prompt library" : "ChatCore-AI プロンプト共有"}
        >
          <span className="lp-header__brand-mark" aria-hidden="true">
            {/* プロンプト共有ページ本体（prompt_share_page_layout）と同じアイコン
                The same icon the prompt sharing page itself uses */}
            <img src="/static/chatcore-share.png" alt="" />
          </span>
          <span className="lp-header__brand-name">{locale === "en" ? "Prompt Library" : "プロンプト共有"}</span>
        </Link>
        <nav className="lp-header__nav" aria-label={locale === "en" ? "Page navigation" : "ページ内リンク"}>
          <Link href="/prompt_share/lp#value">{locale === "en" ? "What you can do" : "できること"}</Link>
          <Link href="/prompt_share/lp#scope">{locale === "en" ? "What it covers" : "対応範囲"}</Link>
          <Link href="/prompt_share/lp#usage">{locale === "en" ? "How it works" : "使い方"}</Link>
          <Link href="/lp">{locale === "en" ? "About ChatCore-AI" : "ChatCore-AIとは"}</Link>
        </nav>
        <div className="lp-header__actions">
          <Link href="/prompt_share" className="lp-btn lp-btn--ghost">
            {locale === "en" ? "Browse prompts" : "プロンプトを見る"}
          </Link>
          <Link href="/register" className="lp-btn lp-btn--primary">
            {t("lp.start")}
          </Link>
        </div>
      </div>
    </header>
  );
}
