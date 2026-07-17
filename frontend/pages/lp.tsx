import { SeoHead } from "../components/SeoHead";
import { LpFaq, LP_FAQ_ITEMS } from "../components/lp/lp_faq";
import { LpFeatures } from "../components/lp/lp_features";
import { LpFinalCta, LpFooter } from "../components/lp/lp_footer";
import { LpFlow } from "../components/lp/lp_flow";
import { LpHeader } from "../components/lp/lp_header";
import { LpHero } from "../components/lp/lp_hero";
import { absoluteUrl } from "../lib/seo";

const LP_TITLE = "ChatCore-AIとは | 無料の日本語AIチャット・プロンプト共有・メモ管理";

const LP_DESCRIPTION =
  "ChatCore-AIは、AIチャット・プロンプト共有・メモ管理をひとつにまとめた無料の日本語AIワークスペースです。登録は数分、クレジットカード不要。調査・文章作成・アイデア整理をブラウザだけで始められます。";

// ランディングページ用の構造化データ（WebPage・FAQ・パンくず）
// Structured data for the landing page (WebPage, FAQ, breadcrumbs)
const lpStructuredData = [
  {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: LP_TITLE,
    url: absoluteUrl("/lp"),
    description: LP_DESCRIPTION,
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
    mainEntity: LP_FAQ_ITEMS.map((item) => ({
      "@type": "Question",
      name: item.question,
      acceptedAnswer: {
        "@type": "Answer",
        text: item.answer
      }
    }))
  },
  {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "ホーム", item: absoluteUrl("/") },
      { "@type": "ListItem", position: 2, name: "ChatCore-AIとは", item: absoluteUrl("/lp") }
    ]
  }
];

// ユーザー獲得向けのマーケティングランディングページ
// Marketing landing page aimed at user acquisition
export default function LandingPage() {
  return (
    <>
      <SeoHead title={LP_TITLE} description={LP_DESCRIPTION} canonicalPath="/lp" structuredData={lpStructuredData}>
        {/* LP専用CSSは_appに載せず、このページからのみ読み込む / LP-only CSS is linked from this page instead of _app */}
        <link rel="stylesheet" href="/static/css/pages/lp/lp.css" />
        {/* 見出し用の明朝体（このページのみで使用） / Mincho display face used only on this page */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@500;600;700&display=swap"
          rel="stylesheet"
        />
      </SeoHead>

      <div className="lp-page">
        <LpHeader />
        <main>
          <LpHero />
          <LpFeatures />
          <LpFlow />
          <LpFaq />
          <LpFinalCta />
        </main>
        <LpFooter />
      </div>
    </>
  );
}
