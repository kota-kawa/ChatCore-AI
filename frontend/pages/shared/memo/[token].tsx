import type { GetServerSideProps } from "next";
import MarkdownContent from "../../../components/MarkdownContent";
import { SeoHead } from "../../../components/SeoHead";
import { formatDateTime } from "../../../lib/datetime";
import { stripMarkdownForDescription, truncateSeoText } from "../../../lib/seo";

type SharedMemo = {
  title?: string;
  tags?: string;
  created_at?: string | null;
  input_content?: string;
  ai_response?: string;
};

type SharedMemoPayload = {
  memo?: SharedMemo;
  error?: string;
};

type SharedMemoPageProps = {
  payload: SharedMemoPayload;
  pageUrl: string;
  ogImageUrl: string;
};

function normalizeHostHeader(header: string | string[] | undefined) {
  if (Array.isArray(header)) return header[0] || "";
  return header || "";
}

function normalizeProtoHeader(header: string | string[] | undefined) {
  const raw = Array.isArray(header) ? header[0] : header;
  if (!raw) return "";
  return raw.split(",")[0]?.trim() || "";
}

function buildMetaDescription(payload: SharedMemoPayload) {
  if (payload.error) {
    return truncateSeoText(payload.error);
  }
  const memo = payload.memo;
  const summarySource = memo?.ai_response || memo?.input_content || "";
  const normalized = stripMarkdownForDescription(summarySource);
  return truncateSeoText(normalized || "Chat Coreで共有されたメモの閲覧ページです。");
}

export const getServerSideProps: GetServerSideProps<SharedMemoPageProps> = async (context) => {
  const rawToken = context.params?.token;
  const token = Array.isArray(rawToken) ? rawToken[0] : rawToken;
  if (!token) {
    return { notFound: true };
  }

  const backendUrl = process.env.BACKEND_URL || "http://localhost:5004";
  const host = normalizeHostHeader(context.req.headers["x-forwarded-host"]) || normalizeHostHeader(context.req.headers.host);
  const proto = normalizeProtoHeader(context.req.headers["x-forwarded-proto"])
    || (process.env.NODE_ENV === "development" ? "http" : "https");
  const origin = host ? `${proto}://${host}` : "";
  const resolvedPath = context.resolvedUrl || `/shared/memo/${encodeURIComponent(token)}`;
  const pageUrl = origin ? `${origin}${resolvedPath}` : resolvedPath;
  const ogImageUrl = origin ? `${origin}/static/img.jpg` : "/static/img.jpg";

  let payload: SharedMemoPayload = {};

  try {
    const res = await fetch(`${backendUrl}/memo/api/shared?token=${encodeURIComponent(token)}`);
    const data: SharedMemoPayload = await res.json().catch(() => ({}));
    if (!res.ok) {
      context.res.statusCode = res.status;
    }
    payload = data && typeof data === "object" ? data : {};
    if (!res.ok && !payload.error) {
      payload.error = `共有メモの取得に失敗しました (${res.status})`;
    }
  } catch {
    context.res.statusCode = 500;
    payload = { error: "共有メモの取得に失敗しました。" };
  }

  return {
    props: {
      payload,
      pageUrl,
      ogImageUrl
    }
  };
};

export default function SharedMemoPage({ payload, pageUrl, ogImageUrl }: SharedMemoPageProps) {
  const memo = payload.memo;
  const title = memo?.title || "共有メモ";
  const tags = memo?.tags ? memo.tags.split(/\s+/).filter(Boolean) : [];
  const pageTitle = `${title} | Chat Core 共有`;
  const description = buildMetaDescription(payload);
  const structuredData = memo
    ? {
        "@context": "https://schema.org",
        "@type": "CreativeWork",
        headline: title,
        name: title,
        description,
        datePublished: memo.created_at || undefined,
        url: pageUrl,
        inLanguage: "ja",
        keywords: tags.join(", ") || undefined,
        isPartOf: {
          "@type": "WebSite",
          name: "Chat Core"
        }
      }
    : undefined;

  return (
    <>
      <SeoHead
        title={pageTitle}
        description={description}
        canonicalUrl={pageUrl}
        imageUrl={ogImageUrl}
        ogType="article"
        noindex={Boolean(payload.error || !memo)}
        structuredData={structuredData}
      >
        <link rel="stylesheet" href="/static/css/pages/shared_memo.css" />
      </SeoHead>

      <div className="shared-memo-page">
        {payload.error && <div className="shared-memo-state shared-memo-state--error">{payload.error}</div>}

        {!payload.error && memo && (
          <article className="shared-memo-shell">
            <header className="shared-memo-header">
              <h1>{title}</h1>
              {memo.created_at ? <p>保存日時: {formatDateTime(memo.created_at) || memo.created_at}</p> : null}
              <div className="shared-memo-tags">
                {tags.length ? tags.map((tag) => <span key={tag}>{tag}</span>) : <span>タグなし</span>}
              </div>
            </header>

            <section className="shared-memo-section">
              <h2>入力内容</h2>
              <MarkdownContent text={memo.input_content || ""} className="md-content" />
            </section>

            <section className="shared-memo-section">
              <h2>AIの回答</h2>
              <MarkdownContent text={memo.ai_response || ""} className="md-content" />
            </section>
          </article>
        )}
      </div>
    </>
  );
}
