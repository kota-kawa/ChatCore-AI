import { SeoHead } from "../../components/SeoHead";
import { LpFooter } from "../../components/lp/lp_footer";
import { PromptShareLpFinalCta } from "../../components/prompt_share_lp/prompt_share_lp_cta";
import {
  PromptShareLpFaq,
  PROMPT_SHARE_LP_FAQ_ITEMS,
  PROMPT_SHARE_LP_FAQ_ITEMS_EN
} from "../../components/prompt_share_lp/prompt_share_lp_faq";
import { PromptShareLpHeader } from "../../components/prompt_share_lp/prompt_share_lp_header";
import { PromptShareLpHero } from "../../components/prompt_share_lp/prompt_share_lp_hero";
import { PromptShareLpScope } from "../../components/prompt_share_lp/prompt_share_lp_scope";
import { PromptShareLpUsage } from "../../components/prompt_share_lp/prompt_share_lp_usage";
import { PromptShareLpValue } from "../../components/prompt_share_lp/prompt_share_lp_value";
import { useTranslation } from "../../contexts/locale_context";
import { absoluteUrl, localizedAbsoluteUrl } from "../../lib/seo";
import type { Locale } from "../../lib/i18n/config";

const PROMPT_SHARE_LP_PATH = "/prompt_share/lp";

// 紹介ページの構造化データ（WebPage・FAQ・パンくず）
// Structured data for the introduction page (WebPage, FAQ, breadcrumbs)
export function buildPromptShareLpStructuredData(locale: Locale, title: string, description: string) {
  const faqItems = locale === "en" ? PROMPT_SHARE_LP_FAQ_ITEMS_EN : PROMPT_SHARE_LP_FAQ_ITEMS;
  const homeUrl = localizedAbsoluteUrl("/", locale);
  const feedUrl = localizedAbsoluteUrl("/prompt_share", locale);
  const pageUrl = localizedAbsoluteUrl(PROMPT_SHARE_LP_PATH, locale);
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
          name: locale === "en" ? "Prompt library" : "プロンプト共有",
          item: feedUrl
        },
        {
          "@type": "ListItem",
          position: 3,
          name: locale === "en" ? "About the prompt library" : "プロンプト共有とは",
          item: pageUrl
        }
      ]
    }
  ];
}

// プロンプト共有サービスの紹介ページ（画像を使わず、文字とCSSだけで構成する）
// Landing page introducing the prompt sharing service, built from text and CSS with no images
export default function PromptShareLandingPage() {
  const { locale, t } = useTranslation();
  const title = t("promptShareLp.title");
  const description = t("promptShareLp.description");
  const structuredData = buildPromptShareLpStructuredData(locale, title, description);
  return (
    <>
      <SeoHead
        title={title}
        description={description}
        canonicalPath={PROMPT_SHARE_LP_PATH}
        structuredData={structuredData}
      >
        {/* LP共通のシェル（ヘッダー・ボタン・FAQ・フッター）とこのページ固有のCSSを読み込む
            Load the shared LP shell (header, buttons, FAQ, footer) plus this page's own CSS */}
        <link rel="stylesheet" href="/static/css/pages/lp/lp.css" />
        <link rel="stylesheet" href="/static/css/pages/prompt_share_lp/prompt_share_lp.css" />
        {/* 見出し用の明朝体（LPと同じ書体をそろえる） / Mincho display face, shared with /lp */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@500;600;700&display=swap"
          rel="stylesheet"
        />
      </SeoHead>

      <div className="lp-page pslp-page">
        <PromptShareLpHeader />
        <main>
          <PromptShareLpHero />
          <PromptShareLpValue />
          <PromptShareLpScope />
          <PromptShareLpUsage />
          <PromptShareLpFaq />
          <PromptShareLpFinalCta />
        </main>
        <LpFooter />
      </div>
    </>
  );
}
