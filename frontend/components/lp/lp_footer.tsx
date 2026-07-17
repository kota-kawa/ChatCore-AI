// 最終CTAセクション（深緑の締めのブロック）
// Final CTA section (deep-green closing block)
export function LpFinalCta() {
  return (
    <section className="lp-final-cta">
      <div className="lp-container lp-final-cta__inner">
        <h2 className="lp-final-cta__title">
          今日の調べものから、
          <br className="lp-br-sp" />
          始めてみませんか。
        </h2>
        <p className="lp-final-cta__note">登録は数分で完了します。いつでも無料で使えます。</p>
        <a href="/register" className="lp-btn lp-btn--inverse lp-btn--large">
          無料で始める
        </a>
      </div>
    </section>
  );
}

// フッター（既存ページへのリンクとコピーライト）
// Footer (links to existing pages and copyright)
export function LpFooter() {
  return (
    <footer className="lp-footer">
      <div className="lp-container lp-footer__inner">
        <p className="lp-footer__brand">ChatCore-AI</p>
        <nav className="lp-footer__nav" aria-label="サイト内リンク">
          <a href="/">AIチャット</a>
          <a href="/prompt_share">プロンプト共有</a>
          <a href="/memo">メモ</a>
          <a href="/help">ヘルプ</a>
          <a href="/terms">利用規約</a>
          <a href="/privacy">プライバシーポリシー</a>
          <a href="/login">ログイン</a>
          <a href="/register">新規登録</a>
        </nav>
        <p className="lp-footer__copyright">© {new Date().getFullYear()} Chat Core</p>
      </div>
    </footer>
  );
}
