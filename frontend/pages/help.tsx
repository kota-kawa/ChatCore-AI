import { SeoHead } from "../components/SeoHead";
import { HELP_CATEGORIES } from "../components/help/help_content";
import { LpFooter } from "../components/lp/lp_footer";
import { LpHeader } from "../components/lp/lp_header";
import { absoluteUrl } from "../lib/seo";

const HELP_TITLE = "ヘルプセンター | ChatCore-AI";

const HELP_DESCRIPTION =
  "ChatCore-AIの使い方とよくある質問をまとめたヘルプセンターです。アカウント登録、AIチャットの使い方、プロンプト共有、メモ、セキュリティ設定、トラブル解決の方法を確認できます。";

// はじめの一歩として案内するページ / First-step destinations to guide users to
const QUICKSTART_CARDS = [
  {
    href: "/",
    icon: "bi-chat-square-text-fill",
    name: "AI CHAT",
    title: "AIチャットを始める",
    description: "調べもの・文章作成・アイデア出しを、日本語で自然に相談できます。"
  },
  {
    href: "/prompt_share",
    icon: "bi-share-fill",
    name: "PROMPT SHARE",
    title: "プロンプトを探す",
    description: "他のユーザーが作った便利なプロンプトを見つけて、すぐに使えます。"
  },
  {
    href: "/memo",
    icon: "bi-journal-check",
    name: "MEMO",
    title: "メモをはじめる",
    description: "チャットの回答や自分の考えを保存して、あとから整理できます。"
  }
];

// ヘルプページの構造化データ（WebPage・FAQ・パンくず）
// Structured data for the help page (WebPage, FAQ, breadcrumbs)
const helpStructuredData = [
  {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: HELP_TITLE,
    url: absoluteUrl("/help"),
    description: HELP_DESCRIPTION,
    inLanguage: "ja",
    isPartOf: {
      "@type": "WebSite",
      name: "Chat Core",
      url: absoluteUrl("/")
    }
  },
  {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: HELP_CATEGORIES.flatMap((category) =>
      category.items.map((item) => ({
        "@type": "Question",
        name: item.question,
        acceptedAnswer: {
          "@type": "Answer",
          text: item.answers.join(" ")
        }
      }))
    )
  },
  {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "ホーム", item: absoluteUrl("/") },
      { "@type": "ListItem", position: 2, name: "ヘルプセンター", item: absoluteUrl("/help") }
    ]
  }
];

// ヘルプセンターページ（クイックスタート＋カテゴリ別FAQ）
// Help center page (quick start + FAQ grouped by category)
export default function HelpPage() {
  return (
    <>
      <SeoHead title={HELP_TITLE} description={HELP_DESCRIPTION} canonicalPath="/help" structuredData={helpStructuredData}>
        {/* ドキュメント系ページはLPのトークンを共有するため両方のCSSを読み込む
            Document pages load both stylesheets since they share the LP tokens */}
        <link rel="stylesheet" href="/static/css/pages/lp/lp.css" />
        <link rel="stylesheet" href="/static/css/pages/docs/docs.css" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@500;600;700&display=swap"
          rel="stylesheet"
        />
      </SeoHead>

      <div className="lp-page docs-page">
        <LpHeader />
        <main>
          <section className="docs-hero">
            <p className="docs-hero__kicker" aria-hidden="true">
              困ったときの道しるべ
            </p>
            <div className="lp-container">
              <p className="lp-eyebrow">HELP CENTER</p>
              <h1 className="docs-hero__title">ヘルプセンター</h1>
              <p className="docs-hero__lead">
                ChatCore-AIの使い方と、よくある質問への回答をまとめました。知りたい項目をカテゴリから選ぶか、下の一覧から探してください。
              </p>
            </div>
          </section>

          <section className="help-quickstart" aria-label="クイックスタート">
            <div className="lp-container help-quickstart__grid">
              {QUICKSTART_CARDS.map((card) => (
                <a key={card.href} href={card.href} className="lp-feature-card">
                  <span className="lp-feature-card__icon" aria-hidden="true">
                    <i className={`bi ${card.icon}`}></i>
                  </span>
                  <span className="lp-feature-card__name">{card.name}</span>
                  <span className="lp-feature-card__title">{card.title}</span>
                  <span className="lp-feature-card__description">{card.description}</span>
                </a>
              ))}
            </div>
          </section>

          <section className="help-body">
            <div className="lp-container help-body__inner">
              <nav className="docs-toc" aria-label="カテゴリ">
                <p className="docs-toc__label">カテゴリ</p>
                <ol className="docs-toc__list">
                  {HELP_CATEGORIES.map((category) => (
                    <li key={category.id}>
                      <a href={`#${category.id}`}>{category.title}</a>
                    </li>
                  ))}
                </ol>
              </nav>

              <div className="help-sections">
                {HELP_CATEGORIES.map((category) => (
                  <section key={category.id} id={category.id} className="help-section" aria-labelledby={`${category.id}-title`}>
                    <h2 className="help-section__title" id={`${category.id}-title`}>
                      <span className="help-section__icon" aria-hidden="true">
                        <i className={`bi ${category.icon}`}></i>
                      </span>
                      {category.title}
                    </h2>
                    <div className="help-section__list">
                      {category.items.map((item) => (
                        <details key={item.question} className="help-qa">
                          <summary className="help-qa__question">{item.question}</summary>
                          <div className="help-qa__answer">
                            {item.answers.map((answer) => (
                              <p key={answer}>{answer}</p>
                            ))}
                            {item.link ? (
                              <p>
                                <a
                                  href={item.link.href}
                                  {...(item.link.external
                                    ? { target: "_blank", rel: "noopener noreferrer" }
                                    : {})}
                                >
                                  {item.link.label}
                                </a>
                              </p>
                            ) : null}
                          </div>
                        </details>
                      ))}
                    </div>
                  </section>
                ))}

                {/* 解決しなかったときのお問い合わせ導線 / Contact strip for unresolved questions */}
                <div className="docs-contact">
                  <div className="docs-contact__copy">
                    <p className="docs-contact__title">解決しませんでしたか？</p>
                    <p className="docs-contact__text">
                      不具合の報告やご要望は、GitHubリポジトリのIssueで受け付けています。利用ルールは利用規約・プライバシーポリシーをご覧ください。
                    </p>
                  </div>
                  <div className="docs-contact__actions">
                    <a
                      href="https://github.com/kota-kawa/Chat-Core/issues"
                      className="lp-btn lp-btn--primary"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      お問い合わせ（Issue）
                    </a>
                    <a href="/terms" className="lp-btn lp-btn--ghost">
                      利用規約
                    </a>
                    <a href="/privacy" className="lp-btn lp-btn--ghost">
                      プライバシーポリシー
                    </a>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </main>
        <LpFooter />
      </div>
    </>
  );
}
