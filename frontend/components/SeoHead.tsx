import Head from "next/head";

import {
  absoluteUrl,
  DEFAULT_OG_IMAGE_PATH,
  DEFAULT_SEO_DESCRIPTION,
  DEFAULT_SEO_TITLE,
  jsonLdScriptContent,
  SITE_NAME
} from "../lib/seo";

type SeoHeadProps = {
  title?: string;
  description?: string;
  canonicalPath?: string;
  canonicalUrl?: string;
  imageUrl?: string;
  ogType?: "website" | "article" | "profile";
  noindex?: boolean;
  structuredData?: Record<string, unknown> | Record<string, unknown>[];
  children?: React.ReactNode;
};

export function SeoHead({
  title = DEFAULT_SEO_TITLE,
  description = DEFAULT_SEO_DESCRIPTION,
  canonicalPath,
  canonicalUrl,
  imageUrl = DEFAULT_OG_IMAGE_PATH,
  ogType = "website",
  noindex = false,
  structuredData,
  children
}: SeoHeadProps) {
  const resolvedCanonicalUrl = canonicalUrl || (canonicalPath ? absoluteUrl(canonicalPath) : "");
  const resolvedImageUrl = absoluteUrl(imageUrl);
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
      <meta name="robots" content={robotsContent} />
      <meta name="googlebot" content={robotsContent} />
      <meta property="og:locale" content="ja_JP" />
      <meta property="og:site_name" content={SITE_NAME} />
      <meta property="og:type" content={ogType} />
      <meta property="og:title" content={title} />
      <meta property="og:description" content={description} />
      {resolvedCanonicalUrl ? <link rel="canonical" href={resolvedCanonicalUrl} /> : null}
      {resolvedCanonicalUrl ? <meta property="og:url" content={resolvedCanonicalUrl} /> : null}
      {resolvedImageUrl ? <meta property="og:image" content={resolvedImageUrl} /> : null}
      {resolvedImageUrl ? <meta property="og:image:alt" content={`${SITE_NAME} preview`} /> : null}
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content={title} />
      <meta name="twitter:description" content={description} />
      {resolvedImageUrl ? <meta name="twitter:image" content={resolvedImageUrl} /> : null}
      <link rel="icon" type="image/webp" href="/static/favicon.webp" />
      <link rel="icon" type="image/png" href="/static/favicon.png" />
      <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png" />
      <meta name="theme-color" content="#f7f2e8" media="(prefers-color-scheme: light)" />
      <meta name="theme-color" content="#111827" media="(prefers-color-scheme: dark)" />
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
