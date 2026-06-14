import type { GetServerSideProps } from "next";
import MarkdownContent from "../../../components/MarkdownContent";
import { SeoHead } from "../../../components/SeoHead";
import { formatDateTime } from "../../../lib/datetime";
import { stripMarkdownForDescription, truncateSeoText } from "../../../lib/seo";

// 共有メモのデータ型
// Type for shared memo data
type SharedMemo = {
  title?: string;
  created_at?: string | null;
  ai_response?: string;
  background_color?: string | null;
};

// バックエンドAPIから返されるペイロード（メモまたはエラーメッセージ）
// Payload returned from the backend API (memo or error message)
type SharedMemoPayload = {
  memo?: SharedMemo;
  error?: string;
};

// ページコンポーネントのプロップス
// Props for the page component
type SharedMemoPageProps = {
  payload: SharedMemoPayload;
  pageUrl: string;
  ogImageUrl: string;
};

// Hostヘッダーの値を正規化する（配列の場合は先頭を取得）
// Normalize the Host header value (take the first if it's an array)
function normalizeHostHeader(header: string | string[] | undefined) {
  if (Array.isArray(header)) return header[0] || "";
  return header || "";
}

// X-Forwarded-Protoヘッダーを正規化する（カンマ区切りの最初の値を取得）
// Normalize the X-Forwarded-Proto header (take the first comma-separated value)
function normalizeProtoHeader(header: string | string[] | undefined) {
  const raw = Array.isArray(header) ? header[0] : header;
  if (!raw) return "";
  return raw.split(",")[0]?.trim() || "";
}

// OGP用のmeta descriptionをメモ本文から生成する
// Build the OGP meta description from the memo content
function buildMetaDescription(payload: SharedMemoPayload) {
  if (payload.error) {
    return truncateSeoText(payload.error);
  }
  const memo = payload.memo;
  const summarySource = memo?.ai_response || "";
  const normalized = stripMarkdownForDescription(summarySource);
  return truncateSeoText(normalized || "Chat Coreで共有されたメモの閲覧ページです。");
}

// URLトークンでメモを取得してSSRで返す（トークンが無効な場合は404）
// Fetch memo by URL token for SSR (returns 404 if the token is invalid)
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
    // バックエンドのエラーステータスをフロントのレスポンスコードに伝播させる
    // Propagate backend error status to the frontend response code
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

// 共有メモ表示ページ（エラー時はメッセージを表示、正常時はMarkdownレンダリング）
// Shared memo display page (shows error message or renders Markdown content)
export default function SharedMemoPage({ payload, pageUrl, ogImageUrl }: SharedMemoPageProps) {
  const memo = payload.memo;
  const title = memo?.title || "共有メモ";
  const pageTitle = `${title} | Chat Core 共有`;
  const description = buildMetaDescription(payload);
  // Schema.orgの構造化データ（メモが存在する場合のみ付与）
  // Schema.org structured data (only included when memo exists)
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
        {/* エラー時はエラーメッセージを表示 / Show error message on failure */}
        {payload.error && <div className="shared-memo-state shared-memo-state--error">{payload.error}</div>}

        {!payload.error && memo && (
          <article
            className="shared-memo-shell"
            // CSS変数でメモのテーマカラーを適用する / Apply memo theme color via CSS custom property
            style={memo.background_color ? { "--shared-memo-color": memo.background_color } as React.CSSProperties : undefined}
          >
            <header className="shared-memo-header">
              <h1>{title}</h1>
              {memo.created_at ? <p>保存日時: {formatDateTime(memo.created_at) || memo.created_at}</p> : null}
            </header>

            <section className="shared-memo-section">
              <h2>本文</h2>
              <MarkdownContent text={memo.ai_response || ""} className="md-content" />
            </section>
          </article>
        )}
      </div>
    </>
  );
}
