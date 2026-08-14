import Link from "next/link";
import { useTranslation } from "../../contexts/locale_context";

// メモ紹介ページのヘッダー。ブランドマークだけはメモ画面と同じアイコン画像を使う
// （MemoSidebar が使っている /static/chatcore-memo.png と同一）
// Header for the memo landing page. The brand mark is the only image on the page and
// reuses the memo screen's own icon (/static/chatcore-memo.png, as in MemoSidebar).
export function MemoLpHeader() {
  const { locale, t } = useTranslation();
  const isEn = locale === "en";
  return (
    <header className="lp-header">
      <div className="lp-container lp-header__inner">
        <Link
          href="/memo/lp"
          className="lp-header__brand"
          aria-label={isEn ? "ChatCore-AI memos" : "ChatCore-AI メモ"}
        >
          <span className="lp-header__brand-mark" aria-hidden="true">
            <img src="/static/chatcore-memo.png" alt="" />
          </span>
          <span className="lp-header__brand-name">{isEn ? "ChatCore Memo" : "メモ"}</span>
        </Link>
        <nav className="lp-header__nav" aria-label={isEn ? "Page navigation" : "ページ内リンク"}>
          <Link href="/memo/lp#value">{isEn ? "What you can do" : "できること"}</Link>
          <Link href="/memo/lp#scope">{isEn ? "What it covers" : "対応範囲"}</Link>
          <Link href="/memo/lp#usage">{isEn ? "How it works" : "使い方"}</Link>
          <Link href="/lp">{isEn ? "About ChatCore-AI" : "ChatCore-AIとは"}</Link>
        </nav>
        <div className="lp-header__actions">
          <Link href="/memo" className="lp-btn lp-btn--ghost">
            {isEn ? "Open memos" : "メモを開く"}
          </Link>
          <Link href="/register" className="lp-btn lp-btn--primary">
            {t("lp.start")}
          </Link>
        </div>
      </div>
    </header>
  );
}
