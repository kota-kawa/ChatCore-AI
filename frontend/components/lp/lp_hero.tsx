// ヒーローの会話デモ（装飾用・支援技術には本文コピーで内容を伝える）
// Hero conversation demo (decorative; the copy conveys the content to assistive tech)
function LpHeroDemo() {
  return (
    <div className="lp-demo" aria-hidden="true">
      <div className="lp-demo__window">
        <div className="lp-demo__titlebar">
          <span className="lp-demo__dot"></span>
          <span className="lp-demo__dot"></span>
          <span className="lp-demo__dot"></span>
          <span className="lp-demo__title">ChatCore-AI</span>
        </div>
        <div className="lp-demo__body">
          <div className="lp-demo__msg lp-demo__msg--user">
            競合3社の料金ページを比較して、要点を3行でまとめて
          </div>
          <div className="lp-demo__msg lp-demo__msg--ai">
            <p>比較の要点は次の3つです。</p>
            <ul>
              <li>A社は月額固定、B社・C社は従量課金が基本</li>
              <li>無料枠があるのはB社のみ（月1,000回まで）</li>
              <li>年契約の割引率はC社が最も大きい（20%）</li>
            </ul>
          </div>
          <div className="lp-demo__actions">
            <span className="lp-demo__chip lp-demo__chip--memo">
              <i className="bi bi-journal-check"></i> メモに保存しました
            </span>
            <span className="lp-demo__chip lp-demo__chip--share">
              <i className="bi bi-people"></i> プロンプトを共有
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ヒーローセクション（キャッチコピー・CTA・会話デモ）
// Hero section (headline copy, CTA, conversation demo)
export function LpHero() {
  return (
    <section className="lp-hero">
      <span className="lp-hero__kicker" aria-hidden="true">
        対話を、資産に。
      </span>
      <div className="lp-container lp-hero__inner">
        <div className="lp-hero__copy">
          <p className="lp-eyebrow">AIチャット × プロンプト共有 × メモ管理</p>
          <h1 className="lp-hero__title">
            AIとの対話を、
            <br />
            成果として残す。
          </h1>
          <p className="lp-hero__lead">
            ChatCore-AIは、AIチャット・プロンプト共有・メモ管理をひとつにまとめた、無料で使える日本語AIワークスペースです。調べる・書く・整理する日々の作業が、この画面ひとつで完結します。
          </p>
          <div className="lp-hero__cta">
            <a href="/register" className="lp-btn lp-btn--primary lp-btn--large">
              無料で始める
            </a>
            <a href="/" className="lp-btn lp-btn--ghost lp-btn--large">
              チャットを試してみる
            </a>
          </div>
          <ul className="lp-hero__trust">
            <li>登録無料</li>
            <li>クレジットカード不要</li>
            <li>ブラウザだけで使える</li>
          </ul>
        </div>
        <LpHeroDemo />
      </div>
    </section>
  );
}
