import Head from "next/head";

import {
  absoluteUrl,
  DEFAULT_OG_IMAGE_PATH,
  DEFAULT_OG_IMAGE_HEIGHT,
  DEFAULT_OG_IMAGE_WIDTH,
  DEFAULT_SEO_DESCRIPTION,
  DEFAULT_SEO_TITLE,
  jsonLdScriptContent,
  SITE_NAME,
  TWITTER_SITE
} from "../lib/seo";

// SEOヘッドコンポーネントのprops型定義
// Props type definition for the SEO head component
type SeoHeadProps = {
  title?: string;
  description?: string;
  canonicalPath?: string;
  canonicalUrl?: string;
  imageUrl?: string;
  imageWidth?: number;
  imageHeight?: number;
  ogType?: "website" | "article" | "profile";
  noindex?: boolean;
  structuredData?: Record<string, unknown> | Record<string, unknown>[];
  children?: React.ReactNode;
};

// ページのSEOメタタグ・OGP・Twitter Card・構造化データを一括出力するコンポーネント
// Component that outputs SEO meta tags, OGP, Twitter Card, and structured data for a page
export function SeoHead({
  title = DEFAULT_SEO_TITLE,
  description = DEFAULT_SEO_DESCRIPTION,
  canonicalPath,
  canonicalUrl,
  imageUrl = DEFAULT_OG_IMAGE_PATH,
  imageWidth = DEFAULT_OG_IMAGE_WIDTH,
  imageHeight = DEFAULT_OG_IMAGE_HEIGHT,
  ogType = "website",
  noindex = false,
  structuredData,
  children
}: SeoHeadProps) {
  // canonicalUrlが直接指定されていればそれを使い、なければパスから生成する
  // Use canonicalUrl directly if provided, otherwise generate from path
  const resolvedCanonicalUrl = canonicalUrl || (canonicalPath ? absoluteUrl(canonicalPath) : "");
  const resolvedImageUrl = absoluteUrl(imageUrl);
  // noindexフラグに応じてrobotsメタタグの内容を切り替える
  // Switch robots meta tag content based on the noindex flag
  const robotsContent = noindex
    ? "noindex,nofollow,noarchive"
    : "index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1";

  return (
    <Head>
      <meta charSet="UTF-8" />
      <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0, viewport-fit=cover, interactive-widget=resizes-content"
      />
      <title>{title}</title>
      <meta name="description" content={description} />
      {/* 検索エンジンのインデックス制御 / Search engine indexing control */}
      <meta name="robots" content={robotsContent} />
      <meta name="googlebot" content={robotsContent} />
      {/* OGP基本メタタグ / OGP basic meta tags */}
      <meta property="og:locale" content="ja_JP" />
      <meta property="og:site_name" content={SITE_NAME} />
      <meta property="og:type" content={ogType} />
      <meta property="og:title" content={title} />
      <meta property="og:description" content={description} />
      {resolvedCanonicalUrl ? <link rel="canonical" href={resolvedCanonicalUrl} /> : null}
      {resolvedCanonicalUrl ? <meta property="og:url" content={resolvedCanonicalUrl} /> : null}
      {/* OGP画像メタタグ / OGP image meta tags */}
      {resolvedImageUrl ? <meta property="og:image" content={resolvedImageUrl} /> : null}
      {resolvedImageUrl ? <meta property="og:image:type" content={resolvedImageUrl.endsWith(".png") ? "image/png" : "image/jpeg"} /> : null}
      {resolvedImageUrl && imageWidth ? <meta property="og:image:width" content={String(imageWidth)} /> : null}
      {resolvedImageUrl && imageHeight ? <meta property="og:image:height" content={String(imageHeight)} /> : null}
      {resolvedImageUrl ? <meta property="og:image:alt" content={`${SITE_NAME} preview`} /> : null}
      {/* Twitter Cardメタタグ / Twitter Card meta tags */}
      <meta name="twitter:card" content="summary_large_image" />
      {TWITTER_SITE ? <meta name="twitter:site" content={TWITTER_SITE} /> : null}
      <meta name="twitter:title" content={title} />
      <meta name="twitter:description" content={description} />
      {resolvedImageUrl ? <meta name="twitter:image" content={resolvedImageUrl} /> : null}
      {/* ファビコン・アイコン設定 / Favicon and icon settings */}
      <link rel="icon" type="image/webp" href="/static/favicon.webp" />
      <link rel="icon" type="image/png" href="/static/favicon.png" />
      <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png" />
      <meta name="theme-color" content="#f7f2e8" media="(prefers-color-scheme: light)" />
      <meta name="theme-color" content="#111827" media="(prefers-color-scheme: dark)" />
      {/* 構造化データ（JSON-LD）の埋め込み / Embed structured data (JSON-LD) */}
      {structuredData ? (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLdScriptContent(structuredData) }}
        />
      ) : null}
      {children}
    </Head>
  );
}
