import { SeoHead } from "../components/SeoHead";
import { LpFaq, LP_FAQ_ITEMS, LP_FAQ_ITEMS_EN } from "../components/lp/lp_faq";
import { LpFeatures } from "../components/lp/lp_features";
import { LpFinalCta, LpFooter } from "../components/lp/lp_footer";
import { LpFlow } from "../components/lp/lp_flow";
import { LpHeader } from "../components/lp/lp_header";
import { LpHero } from "../components/lp/lp_hero";
import { absoluteUrl } from "../lib/seo";
import { useTranslation } from "../contexts/locale_context";
import type { Locale } from "../lib/i18n/config";

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

// ロケールに合わせて構造化データを差し替える（FAQ・WebPage・パンくずのすべてを翻訳する）
// Localize the structured data (FAQ, WebPage, and breadcrumbs all need translating)
export function buildLpStructuredData(locale: Locale, title: string, description: string) {
  const faqItems = locale === "en" ? LP_FAQ_ITEMS_EN : LP_FAQ_ITEMS;
  return lpStructuredData.map((entry) => {
    if (entry["@type"] === "FAQPage") {
      return { ...entry, mainEntity: faqItems.map((item) => ({ "@type": "Question", name: item.question, acceptedAnswer: { "@type": "Answer", text: item.answer } })) };
    }
    if (entry["@type"] === "WebPage") {
      return { ...entry, name: title, description, inLanguage: locale };
    }
    if (entry["@type"] === "BreadcrumbList" && locale === "en") {
      return { ...entry, itemListElement: [
        { "@type": "ListItem", position: 1, name: "Home", item: absoluteUrl("/") },
        { "@type": "ListItem", position: 2, name: "About ChatCore-AI", item: absoluteUrl("/lp") }
      ] };
    }
    return entry;
  });
}

// ユーザー獲得向けのマーケティングランディングページ
// Marketing landing page aimed at user acquisition
export default function LandingPage() {
  const { locale, t } = useTranslation();
  const title = t("lp.title");
  const description = t("lp.description");
  const structuredData = buildLpStructuredData(locale, title, description);
  return (
    <>
      <SeoHead title={title} description={description} canonicalPath="/lp" structuredData={structuredData}>
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
