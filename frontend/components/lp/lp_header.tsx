// ランディングページのヘッダー（ロゴ・セクション内リンク・CTA）
// Landing page header (logo, in-page section links, CTA)
export function LpHeader() {
  return (
    <header className="lp-header">
      <div className="lp-container lp-header__inner">
        <a href="/lp" className="lp-header__brand" aria-label="ChatCore-AI ランディングページ">
          <span className="lp-header__brand-mark" aria-hidden="true">
            <i className="bi bi-chat-square-text-fill"></i>
          </span>
          <span className="lp-header__brand-name">ChatCore-AI</span>
        </a>
        {/* /lp以外のページ（/help・/privacy・/terms）からも共有するため絶対パスのアンカーにする
            Use absolute-path anchors so pages other than /lp (/help, /privacy, /terms) can share this header */}
        <nav className="lp-header__nav" aria-label="ページ内リンク">
          <a href="/lp#features">できること</a>
          <a href="/lp#flow">使い方</a>
          <a href="/help">ヘルプ</a>
        </nav>
        <div className="lp-header__actions">
          <a href="/login" className="lp-btn lp-btn--ghost">
            ログイン
          </a>
          <a href="/register" className="lp-btn lp-btn--primary">
            無料で始める
          </a>
        </div>
      </div>
    </header>
  );
}
