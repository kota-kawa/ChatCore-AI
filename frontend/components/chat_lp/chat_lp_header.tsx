import Link from "next/link";
import { useTranslation } from "../../contexts/locale_context";

// AIチャット紹介ページのヘッダー。ブランドマークはチャット画面と同じアイコンを使う
// Header for the AI chat landing page; the brand mark reuses the chat screen's own icon
export function ChatLpHeader() {
  const { locale, t } = useTranslation();
  return (
    <header className="lp-header">
      <div className="lp-container lp-header__inner">
        <Link
          href="/chat/lp"
          className="lp-header__brand"
          aria-label={locale === "en" ? "ChatCore-AI chat" : "ChatCore-AI AIチャット"}
        >
          <span className="lp-header__brand-mark" aria-hidden="true">
            <img src="/static/favicon.png" alt="" />
          </span>
          <span className="lp-header__brand-name">{locale === "en" ? "AI Chat" : "AIチャット"}</span>
        </Link>
        <nav className="lp-header__nav" aria-label={locale === "en" ? "Page navigation" : "ページ内リンク"}>
          <Link href="/chat/lp#value">{locale === "en" ? "What you can do" : "できること"}</Link>
          <Link href="/chat/lp#scope">{locale === "en" ? "What it covers" : "対応範囲"}</Link>
          <Link href="/chat/lp#usage">{locale === "en" ? "How it works" : "使い方"}</Link>
          <Link href="/lp">{locale === "en" ? "About ChatCore-AI" : "ChatCore-AIとは"}</Link>
        </nav>
        <div className="lp-header__actions">
          <Link href="/" className="lp-btn lp-btn--ghost">
            {locale === "en" ? "Open the chat" : "チャットを開く"}
          </Link>
          <Link href="/register" className="lp-btn lp-btn--primary">
            {t("lp.start")}
          </Link>
        </div>
      </div>
    </header>
  );
}
