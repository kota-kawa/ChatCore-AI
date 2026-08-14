import { SeoHead } from "../../components/SeoHead";
import { LpFooter } from "../../components/lp/lp_footer";
import { MemoLpFinalCta } from "../../components/memo_lp/memo_lp_cta";
import { MemoLpFaq, MEMO_LP_FAQ_ITEMS, MEMO_LP_FAQ_ITEMS_EN } from "../../components/memo_lp/memo_lp_faq";
import { MemoLpHeader } from "../../components/memo_lp/memo_lp_header";
import { MemoLpHero } from "../../components/memo_lp/memo_lp_hero";
import { MemoLpScope } from "../../components/memo_lp/memo_lp_scope";
import { MemoLpUsage } from "../../components/memo_lp/memo_lp_usage";
import { MemoLpValue } from "../../components/memo_lp/memo_lp_value";
import { useTranslation } from "../../contexts/locale_context";
import { localizedAbsoluteUrl } from "../../lib/seo";
import type { Locale } from "../../lib/i18n/config";

const MEMO_LP_PATH = "/memo/lp";

// 紹介ページの構造化データ（WebPage・FAQ・パンくず）
// Structured data for the introduction page (WebPage, FAQ, breadcrumbs)
export function buildMemoLpStructuredData(locale: Locale, title: string, description: string) {
  const faqItems = locale === "en" ? MEMO_LP_FAQ_ITEMS_EN : MEMO_LP_FAQ_ITEMS;
  const homeUrl = localizedAbsoluteUrl("/", locale);
  const memoUrl = localizedAbsoluteUrl("/memo", locale);
  const pageUrl = localizedAbsoluteUrl(MEMO_LP_PATH, locale);
  return [
    {
      "@context": "https://schema.org",
      "@type": "WebPage",
      name: title,
      url: pageUrl,
      description,
      inLanguage: locale,
      isPartOf: {
        "@type": "WebSite",
        name: "Chat Core",
        url: homeUrl
      }
    },
    {
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: faqItems.map((item) => ({
        "@type": "Question",
        name: item.question,
        acceptedAnswer: { "@type": "Answer", text: item.answer }
      }))
    },
    {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: locale === "en" ? "Home" : "ホーム", item: homeUrl },
        {
          "@type": "ListItem",
          position: 2,
          name: locale === "en" ? "Memos" : "メモ",
          item: memoUrl
        },
        {
          "@type": "ListItem",
          position: 3,
          name: locale === "en" ? "About memos" : "メモとは",
          item: pageUrl
        }
      ]
    }
  ];
}

// メモ機能の紹介ページ（ブランドマーク以外は画像を使わず、文字とCSSだけで構成する）
// Landing page introducing the memo feature, built from text and CSS apart from the brand mark
export default function MemoLandingPage() {
  const { locale, t } = useTranslation();
  const title = t("memoLp.title");
  const description = t("memoLp.description");
  const structuredData = buildMemoLpStructuredData(locale, title, description);
  return (
    <>
      <SeoHead
        title={title}
        description={description}
        canonicalPath={MEMO_LP_PATH}
        structuredData={structuredData}
      >
        {/* LP共通のシェル（ヘッダー・ボタン・FAQ・フッター）とこのページ固有のCSSを読み込む
            Load the shared LP shell (header, buttons, FAQ, footer) plus this page's own CSS */}
        <link rel="stylesheet" href="/static/css/pages/lp/lp.css" />
        <link rel="stylesheet" href="/static/css/pages/memo_lp/memo_lp.css" />
        {/* 見出し用の明朝体（LPと同じ書体をそろえる） / Mincho display face, shared with /lp */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@500;600;700&display=swap"
          rel="stylesheet"
        />
      </SeoHead>

      <div className="lp-page mslp-page">
        <MemoLpHeader />
        <main>
          <MemoLpHero />
          <MemoLpValue />
          <MemoLpScope />
          <MemoLpUsage />
          <MemoLpFaq />
          <MemoLpFinalCta />
        </main>
        <LpFooter />
      </div>
    </>
  );
}
