import type { GetServerSideProps } from "next";
import MarkdownContent from "../../../components/MarkdownContent";
import { SeoHead } from "../../../components/SeoHead";
import { formatDateTime } from "../../../lib/datetime";

type SharedPrompt = {
  id?: number | string;
  title?: string;
  category?: string;
  content?: string;
  author?: string;
  prompt_type?: string;
  reference_image_url?: string | null;
  input_examples?: string;
  output_examples?: string;
  ai_model?: string;
  created_at?: string;
};

type SharedPromptPayload = {
  prompt?: SharedPrompt;
  error?: string;
};

type SharedPromptPageProps = {
  payload: SharedPromptPayload;
  pageUrl: string;
  defaultOgImageUrl: string;
};

type SharedPromptResponse = SharedPromptPayload;

function formatDate(value?: string) {
  return formatDateTime(value) || value || "";
}

function normalizeHostHeader(header: string | string[] | undefined) {
  if (Array.isArray(header)) return header[0] || "";
  return header || "";
}

function normalizeProtoHeader(header: string | string[] | undefined) {
  const raw = Array.isArray(header) ? header[0] : header;
  if (!raw) return "";
  return raw.split(",")[0]?.trim() || "";
}

function stripPreviewText(value: string) {
  return value
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[#>*_\-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function truncateText(value: string, maxLength = 140) {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1).trimEnd()}…`;
}

function resolveAbsoluteUrl(value: string | null | undefined, origin: string) {
  if (!value) return "";
  if (/^https?:\/\//i.test(value)) return value;
  if (!origin) return value;
  if (value.startsWith("/")) return `${origin}${value}`;
  return `${origin}/${value}`;
}

function buildMetaDescription(payload: SharedPromptPayload) {
  if (payload.error) {
    return truncateText(payload.error);
  }
  const prompt = payload.prompt;
  if (!prompt) {
    return "Chat Core で共有されたプロンプトの閲覧ページです。";
  }
  const summarySource = prompt.content || prompt.output_examples || prompt.input_examples || "";
  const normalized = stripPreviewText(summarySource);
  if (!normalized) {
    return "Chat Core で共有されたプロンプトの閲覧ページです。";
  }
  return truncateText(normalized);
}

export const getServerSideProps: GetServerSideProps<SharedPromptPageProps> = async (context) => {
  const rawId = context.params?.id;
  const promptId = Array.isArray(rawId) ? rawId[0] : rawId;
  if (!promptId) {
    return { notFound: true };
  }

  const backendUrl = process.env.BACKEND_URL || "http://localhost:5004";
  const host = normalizeHostHeader(context.req.headers["x-forwarded-host"]) || normalizeHostHeader(context.req.headers.host);
  const proto = normalizeProtoHeader(context.req.headers["x-forwarded-proto"])
    || (process.env.NODE_ENV === "development" ? "http" : "https");
  const origin = host ? `${proto}://${host}` : "";
  const resolvedPath = context.resolvedUrl || `/shared/prompt/${encodeURIComponent(promptId)}`;
  const pageUrl = origin ? `${origin}${resolvedPath}` : resolvedPath;
  const defaultOgImageUrl = origin ? `${origin}/static/img.jpg` : "/static/img.jpg";

  let payload: SharedPromptPayload = {};

  try {
    const res = await fetch(`${backendUrl}/prompt_share/api/prompts/${encodeURIComponent(promptId)}`);
    const data: SharedPromptResponse = await res.json().catch(() => ({}));
    if (!res.ok) {
      context.res.statusCode = res.status;
    }
    payload = data && typeof data === "object" ? data : {};
    if (!res.ok && !payload.error) {
      payload.error = `共有プロンプトの取得に失敗しました (${res.status})`;
    }
  } catch {
    context.res.statusCode = 500;
    payload = { error: "共有プロンプトの取得に失敗しました。" };
  }

  return {
    props: {
      payload,
      pageUrl,
      defaultOgImageUrl
    }
  };
};

export default function SharedPromptPage({ payload, pageUrl, defaultOgImageUrl }: SharedPromptPageProps) {
  const prompt = payload.prompt;
  const pageTitle = `${prompt?.title || "共有プロンプト"} | Chat Core 共有`;
  const description = buildMetaDescription(payload);
  const promptTypeLabel = prompt?.prompt_type === "image" ? "画像生成プロンプト" : "通常プロンプト";
  const ogImageUrl = resolveAbsoluteUrl(prompt?.reference_image_url, (() => {
    try {
      const parsed = new URL(pageUrl);
      return `${parsed.protocol}//${parsed.host}`;
    } catch {
      return "";
    }
  })()) || defaultOgImageUrl;
  const structuredData = prompt
    ? {
        "@context": "https://schema.org",
        "@type": "CreativeWork",
        headline: prompt.title || "共有プロンプト",
        name: prompt.title || "共有プロンプト",
        description,
        author: {
          "@type": "Person",
          name: prompt.author || "匿名ユーザー"
        },
        datePublished: prompt.created_at || undefined,
        image: ogImageUrl,
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
        noindex={Boolean(payload.error || !prompt)}
        structuredData={structuredData}
      >
        <link rel="stylesheet" href="/static/css/pages/shared_prompt.css" />
      </SeoHead>

      <div className="shared-prompt-page">
        {payload.error ? (
          <div className="shared-prompt-state shared-prompt-state--error">{payload.error}</div>
        ) : prompt ? (
          <article className="shared-prompt-shell">
            <header className="shared-prompt-header">
              <span className="shared-prompt-pill">{promptTypeLabel}</span>
              <h1>{prompt.title || "共有プロンプト"}</h1>
              <div className="shared-prompt-meta">
                <span>カテゴリ: {prompt.category || "未分類"}</span>
                <span>投稿者: {prompt.author || "匿名ユーザー"}</span>
                {prompt.created_at ? <span>投稿日: {formatDate(prompt.created_at)}</span> : null}
                {prompt.ai_model ? <span>使用AI: {prompt.ai_model}</span> : null}
              </div>
            </header>

            {prompt.reference_image_url ? (
              <div className="shared-prompt-image">
                <img src={prompt.reference_image_url} alt={prompt.title || "共有プロンプトの作例画像"} />
              </div>
            ) : null}

            <section className="shared-prompt-section">
              <h2>内容</h2>
              <MarkdownContent text={prompt.content || ""} className="md-content" />
            </section>

            {prompt.input_examples ? (
              <section className="shared-prompt-section">
                <h2>入力例</h2>
                <MarkdownContent text={prompt.input_examples} className="md-content" />
              </section>
            ) : null}

            {prompt.output_examples ? (
              <section className="shared-prompt-section">
                <h2>出力例</h2>
                <MarkdownContent text={prompt.output_examples} className="md-content" />
              </section>
            ) : null}
          </article>
        ) : (
          <div className="shared-prompt-state shared-prompt-state--error">共有プロンプトの取得に失敗しました。</div>
        )}
      </div>
    </>
  );
}
