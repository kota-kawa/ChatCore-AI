// 3つの主要機能（AIチャット・プロンプト共有・メモ管理）の紹介データ
// Data for the three core features (AI chat, prompt sharing, memo management)
const LP_FEATURES = [
  {
    id: "chat",
    icon: "bi-chat-dots",
    name: "AIチャット",
    title: "日本語で聞けば、すぐ答えが返る",
    description:
      "GroqやGeminiなど複数の生成AIモデルを切り替えながら、調査・要約・文章作成を進められます。会話はワンクリックで共有リンクにできます。",
    href: "/",
    linkLabel: "チャットを開く"
  },
  {
    id: "prompts",
    icon: "bi-people",
    name: "プロンプト共有",
    title: "うまくいった聞き方は、みんなの資産に",
    description:
      "手応えのあったプロンプトを投稿し、他のユーザーの実例を検索して再利用。入力例・出力例つきで、初めてでも同じ成果を再現できます。",
    href: "/prompt_share",
    linkLabel: "プロンプトを探す"
  },
  {
    id: "memo",
    icon: "bi-journal-text",
    name: "メモ管理",
    title: "会話の成果を、そのまま知識に",
    description:
      "AIの回答をMarkdownメモとして保存・整理。あとから検索して見返せるほか、共有リンクでチームにも渡せます。",
    href: "/memo",
    linkLabel: "メモを見る"
  }
] as const;

// 機能紹介セクション
// Feature introduction section
export function LpFeatures() {
  return (
    <section id="features" className="lp-section lp-features" aria-labelledby="lp-features-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">できること</p>
        <h2 id="lp-features-heading" className="lp-heading">
          ひとつのワークスペースに、
          <br className="lp-br-sp" />
          3つの道具。
        </h2>
        <div className="lp-features__grid">
          {LP_FEATURES.map((feature) => (
            <article key={feature.id} className="lp-feature-card">
              <span className="lp-feature-card__icon" aria-hidden="true">
                <i className={`bi ${feature.icon}`}></i>
              </span>
              <p className="lp-feature-card__name">{feature.name}</p>
              <h3 className="lp-feature-card__title">{feature.title}</h3>
              <p className="lp-feature-card__description">{feature.description}</p>
              <a href={feature.href} className="lp-feature-card__link">
                {feature.linkLabel}
                <i className="bi bi-arrow-right" aria-hidden="true"></i>
              </a>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
