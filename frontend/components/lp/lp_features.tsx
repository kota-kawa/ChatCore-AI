// 3つの主要機能（AIチャット・プロンプト共有・メモ管理）の紹介データ
// Data for the three core features (AI chat, prompt sharing, memo management)
const LP_FEATURES = [
  {
    id: "chat",
    icon: "bi-chat-dots",
    name: "AIチャット",
    title: "日本語で聞けば、すぐ答えが返る",
    description:
      "GroqやClaudeなど複数の生成AIモデルを切り替えながら、調査・要約・文章作成を進められます。会話はワンクリックで共有リンクにできます。",
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
const LP_FEATURES_EN = [
  { id: "chat", icon: "bi-chat-dots", name: "AI Chat", title: "Ask naturally and get answers fast", description: "Switch between models such as Groq and Claude for research, summaries, and writing. Share a conversation with one click.", href: "/", linkLabel: "Open chat" },
  { id: "prompts", icon: "bi-people", name: "Prompt Library", title: "Reuse the prompts that work", description: "Publish effective prompts and learn from examples shared by others, complete with sample inputs and outputs.", href: "/prompt_share", linkLabel: "Browse prompts" },
  { id: "memo", icon: "bi-journal-text", name: "Memos", title: "Keep useful answers as knowledge", description: "Save AI responses as Markdown memos, find them later, or share selected notes with your team.", href: "/memo", linkLabel: "Open memos" }
] as const;

// 機能紹介セクション
// Feature introduction section
export function LpFeatures() {
  const { locale } = useTranslation();
  const features = locale === "en" ? LP_FEATURES_EN : LP_FEATURES;
  return (
    <section id="features" className="lp-section lp-features" aria-labelledby="lp-features-heading">
      <div className="lp-container">
        <p className="lp-eyebrow">{locale === "en" ? "FEATURES" : "できること"}</p>
        {/* 日本語は狭い画面向けに改行位置を指定する。英語は単語間の空白が必要なため
            改行を入れず自然な折り返しに任せる
            Japanese pins the line break for narrow screens. English needs word spacing,
            so it wraps naturally instead */}
        <h2 id="lp-features-heading" className="lp-heading">
          {locale === "en" ? "Three essential tools in one workspace." : (
            <>
              ひとつのワークスペースに、
              <br className="lp-br-sp" />
              3つの道具。
            </>
          )}
        </h2>
        <div className="lp-features__grid">
          {features.map((feature) => (
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
import { useTranslation } from "../../contexts/locale_context";
