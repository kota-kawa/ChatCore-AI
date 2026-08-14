import { SeoHead } from "../../components/SeoHead";
import { ChatLpFinalCta } from "../../components/chat_lp/chat_lp_cta";
import {
  ChatLpFaq,
  CHAT_LP_FAQ_ITEMS,
  CHAT_LP_FAQ_ITEMS_EN
} from "../../components/chat_lp/chat_lp_faq";
import { ChatLpHeader } from "../../components/chat_lp/chat_lp_header";
import { ChatLpHero } from "../../components/chat_lp/chat_lp_hero";
import { ChatLpScope } from "../../components/chat_lp/chat_lp_scope";
import { ChatLpUsage } from "../../components/chat_lp/chat_lp_usage";
import { ChatLpValue } from "../../components/chat_lp/chat_lp_value";
import { LpFooter } from "../../components/lp/lp_footer";
import { useTranslation } from "../../contexts/locale_context";
import { localizedAbsoluteUrl } from "../../lib/seo";
import type { Locale } from "../../lib/i18n/config";

const CHAT_LP_PATH = "/chat/lp";

// 紹介ページの構造化データ（WebPage・FAQ・パンくず）
// Structured data for the introduction page (WebPage, FAQ, breadcrumbs)
export function buildChatLpStructuredData(locale: Locale, title: string, description: string) {
  const faqItems = locale === "en" ? CHAT_LP_FAQ_ITEMS_EN : CHAT_LP_FAQ_ITEMS;
  const homeUrl = localizedAbsoluteUrl("/", locale);
  const pageUrl = localizedAbsoluteUrl(CHAT_LP_PATH, locale);
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
          name: locale === "en" ? "About AI chat" : "AIチャットとは",
          item: pageUrl
        }
      ]
    }
  ];
}

// AIチャットの紹介ページ（ヘッダーのアイコン以外は画像を使わず、文字とCSSだけで構成する）
// Landing page introducing the AI chat, built from text and CSS apart from the header icon
export default function ChatLandingPage() {
  const { locale, t } = useTranslation();
  const title = t("chatLp.title");
  const description = t("chatLp.description");
  const structuredData = buildChatLpStructuredData(locale, title, description);
  return (
    <>
      <SeoHead
        title={title}
        description={description}
        canonicalPath={CHAT_LP_PATH}
        structuredData={structuredData}
      >
        {/* LP共通のシェル（ヘッダー・ボタン・FAQ・フッター）とこのページ固有のCSSを読み込む
            Load the shared LP shell (header, buttons, FAQ, footer) plus this page's own CSS */}
        <link rel="stylesheet" href="/static/css/pages/lp/lp.css" />
        <link rel="stylesheet" href="/static/css/pages/chat_lp/chat_lp.css" />
        {/* 見出し用の明朝体（LPと同じ書体をそろえる） / Mincho display face, shared with /lp */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@500;600;700&display=swap"
          rel="stylesheet"
        />
      </SeoHead>

      <div className="lp-page cslp-page">
        <ChatLpHeader />
        <main>
          <ChatLpHero />
          <ChatLpValue />
          <ChatLpScope />
          <ChatLpUsage />
          <ChatLpFaq />
          <ChatLpFinalCta />
        </main>
        <LpFooter />
      </div>
    </>
  );
}
