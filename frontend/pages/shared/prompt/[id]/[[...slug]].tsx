import type { GetServerSideProps } from "next";
import Link from "next/link";
import { useEffect } from "react";
import MarkdownContent from "../../../../components/MarkdownContent";
import { SeoHead } from "../../../../components/SeoHead";
import { formatDateTime } from "../../../../lib/datetime";
import { buildPromptPath, buildPromptSlug } from "../../../../lib/promptSlug";
import { renderMarkdownToSafeHtmlOnServer } from "../../../../lib/server/markdown_ssr";
import { resilientFetch } from "../../../../scripts/core/resilient_fetch";
import {
  getPromptFormatLabel,
  getPromptMediaLabel,
  normalizePromptContentFormat,
  normalizePromptMediaType
} from "../../../../scripts/prompt_share/formatters";
import { getCategoryLabelOrFallback } from "../../../../scripts/prompt_share/prompt_category_registry";

// 共有プロンプトのデータ型（スキルプロンプトのフィールドも含む）
// Type for shared prompt data (including skill prompt fields)
type SharedPrompt = {
  id?: number | string;
  title?: string;
  category?: string;
  content?: string;
  author?: string;
  content_format?: string;
  media_type?: string;
  prompt_type?: string;
  reference_image_url?: string | null;
  skill_markdown?: string;
  skill_python_script?: string;
  input_examples?: string;
  output_examples?: string;
  ai_model?: string;
  created_at?: string;
};

// バックエンドAPIから返されるペイロード
// Payload returned from the backend API
type SharedPromptPayload = {
  prompt?: SharedPrompt;
  error?: string;
};

// おすすめカードに必要なプロンプト一覧のAPIレスポンス
// API response for the prompts needed by recommendation cards.
type RecommendedPromptsPayload = {
  prompts?: SharedPrompt[];
};

// SSRで事前サニタイズ済みの各セクションHTML（クローラにも本文が見えるようにするため）
// Pre-sanitized HTML for each section rendered during SSR (so crawlers can see the body too)
type SharedPromptHtml = {
  content: string;
  inputExamples: string;
  outputExamples: string;
  skillMarkdown: string;
  skillPythonScript: string;
};

// ページコンポーネントのプロップス
// Props for the page component
type SharedPromptPageProps = {
  payload: SharedPromptPayload;
  recommendedPrompts: SharedPrompt[];
  promptHtml: SharedPromptHtml;
  pageUrl: string;
  defaultOgImageUrl: string;
};

type SharedPromptResponse = SharedPromptPayload;

// 日付文字列を表示用フォーマットに変換する
// Convert date string to display format
function formatDate(value?: string) {
  return formatDateTime(value) || value || "";
}

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

// OGP description用にMarkdown記法を除去してプレーンテキスト化する
// Strip Markdown syntax for plain-text OGP description
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

// テキストを最大文字数で切り詰める
// Truncate text to a maximum character count
function truncateText(value: string, maxLength = 140) {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1).trimEnd()}…`;
}

// 相対URLをオリジンを付与した絶対URLに変換する
// Convert relative URL to absolute URL by prepending the origin
function resolveAbsoluteUrl(value: string | null | undefined, origin: string) {
  if (!value) return "";
  if (/^https?:\/\//i.test(value)) return value;
  if (!origin) return value;
  if (value.startsWith("/")) return `${origin}${value}`;
  return `${origin}/${value}`;
}

// 任意の catch-all セグメントから要求されたスラッグ（先頭セグメント）を取り出す
// Extract the requested slug (first segment) from the optional catch-all params
function extractRequestedSlug(rawSlug: string | string[] | undefined) {
  if (Array.isArray(rawSlug)) return rawSlug[0] ?? "";
  return rawSlug ?? "";
}

// スキルの追加PythonスクリプトをMarkdownコードブロックとして整形する（SSRとクライアントで共通）
// Format the skill's additional Python script as a Markdown code block (shared by SSR and client)
function buildSkillScriptMarkdown(script: string) {
  return `\`\`\`python\n${script}\n\`\`\``;
}

// 空のセクションHTMLセット（エラー時やプロンプト未取得時に使用）
// Empty section HTML set (used on errors or when the prompt is missing)
function emptyPromptHtml(): SharedPromptHtml {
  return {
    content: "",
    inputExamples: "",
    outputExamples: "",
    skillMarkdown: "",
    skillPythonScript: ""
  };
}

// OGP用のmeta descriptionをプロンプト内容から生成する
// Build the OGP meta description from the prompt content
function buildMetaDescription(payload: SharedPromptPayload) {
  if (payload.error) {
    return truncateText(payload.error);
  }
  const prompt = payload.prompt;
  if (!prompt) {
    return "Chat Core で共有されたプロンプトの閲覧ページです。";
  }
  const isSkillPrompt = normalizePromptContentFormat(prompt.content_format || prompt.prompt_type || "") === "skill";
  const summarySource =
    (isSkillPrompt
      ? prompt.skill_markdown || prompt.skill_python_script || ""
      : prompt.content || prompt.output_examples || prompt.input_examples || "") || "";
  const normalized = stripPreviewText(summarySource);
  if (!normalized) {
    return "Chat Core で共有されたプロンプトの閲覧ページです。";
  }
  return truncateText(normalized);
}

// おすすめカード向けにMarkdownを含む本文から短いプレーンテキスト要約を作る
// Build a short plain-text summary from Markdown-capable content for recommendation cards.
function buildRecommendationPreview(prompt: SharedPrompt) {
  const source = prompt.content || prompt.skill_markdown || "";
  const preview = stripPreviewText(source);
  return truncateText(preview || "詳細を開いてプロンプトの内容を確認してください。", 112);
}

// プロンプトIDでデータを取得してSSRで返す（IDが無効な場合は404）。
// タイトル由来のスラッグが正規URLと一致しない場合は正規パスへ恒久リダイレクトする。
// 本文Markdownはサーバー側でサニタイズ済みHTMLへ変換し、クローラにも本文が見えるようにする。
// Fetch prompt data by ID for SSR (returns 404 if the ID is missing).
// Permanently redirect to the canonical path when the title-derived slug does not match the requested one.
// The body Markdown is converted to sanitized HTML on the server so crawlers can see it too.
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
  const defaultOgImageUrl = origin ? `${origin}/static/img.jpg` : "/static/img.jpg";

  let payload: SharedPromptPayload = {};
  let recommendedPrompts: SharedPrompt[] = [];

  try {
    const [res, recommendedRes] = await Promise.all([
      resilientFetch(`${backendUrl}/prompt_share/api/prompts/${encodeURIComponent(promptId)}`),
      resilientFetch(
        `${backendUrl}/prompt_share/api/prompts/recommended?exclude_id=${encodeURIComponent(promptId)}`
      ).catch(() => null)
    ]);
    const data: SharedPromptResponse = await res.json().catch(() => ({}));
    const recommendedData: RecommendedPromptsPayload = recommendedRes?.ok
      ? await recommendedRes.json().catch(() => ({}))
      : {};
    // バックエンドのエラーステータスをフロントのレスポンスコードに伝播させる
    // Propagate backend error status to the frontend response code
    if (!res.ok) {
      context.res.statusCode = res.status;
    }
    payload = data && typeof data === "object" ? data : {};
    if (!res.ok && !payload.error) {
      payload.error = `共有プロンプトの取得に失敗しました (${res.status})`;
    }
    recommendedPrompts = Array.isArray(recommendedData.prompts) ? recommendedData.prompts : [];
  } catch {
    context.res.statusCode = 500;
    payload = { error: "共有プロンプトの取得に失敗しました。" };
  }

  // タイトルから正規スラッグを算出し、要求スラッグと異なれば正規パスへ301（恒久）リダイレクトする。
  // 旧来のID単体URLや誤ったスラッグを正規URLへ集約し、重複コンテンツを防ぐ。
  // Compute the canonical slug from the title and 301-redirect to the canonical path when the requested slug differs.
  // This consolidates legacy ID-only URLs and incorrect slugs onto the canonical URL, preventing duplicate content.
  const prompt = payload.prompt;
  if (prompt && prompt.id !== undefined && prompt.id !== null) {
    const canonicalSlug = buildPromptSlug(prompt.title);
    const requestedSlug = extractRequestedSlug(context.params?.slug);
    if (canonicalSlug && requestedSlug !== canonicalSlug) {
      return {
        redirect: {
          destination: buildPromptPath(prompt.id, prompt.title),
          permanent: true
        }
      };
    }
  }

  // 本文の各セクションをサーバー側でサニタイズ済みHTMLへ変換する（SEO対策：SSR出力に本文を含める）
  // Convert each body section to sanitized HTML on the server (SEO: include the body in the SSR output)
  const promptHtml = emptyPromptHtml();
  if (prompt) {
    promptHtml.content = renderMarkdownToSafeHtmlOnServer(prompt.content);
    promptHtml.inputExamples = renderMarkdownToSafeHtmlOnServer(prompt.input_examples);
    promptHtml.outputExamples = renderMarkdownToSafeHtmlOnServer(prompt.output_examples);
    promptHtml.skillMarkdown = renderMarkdownToSafeHtmlOnServer(prompt.skill_markdown);
    promptHtml.skillPythonScript = prompt.skill_python_script
      ? renderMarkdownToSafeHtmlOnServer(buildSkillScriptMarkdown(prompt.skill_python_script))
      : "";
  }

  // 正規パス（プロンプトが存在する場合はスラッグ付き、なければ要求パス）から絶対URLを組み立てる
  // Build the absolute canonical URL from the canonical path (slug-based when the prompt exists, otherwise the requested path)
  const canonicalPath = prompt && prompt.id !== undefined && prompt.id !== null
    ? buildPromptPath(prompt.id, prompt.title)
    : context.resolvedUrl || `/shared/prompt/${encodeURIComponent(promptId)}`;
  const pageUrl = origin ? `${origin}${canonicalPath}` : canonicalPath;

  return {
    props: {
      payload,
      recommendedPrompts,
      promptHtml,
      pageUrl,
      defaultOgImageUrl
    }
  };
};

// 共有プロンプト詳細ページ（フォーマット軸・メディア軸に応じて表示）
// Shared prompt detail page (renders according to content format and media type axes)
export default function SharedPromptPage({
  payload,
  recommendedPrompts,
  promptHtml,
  pageUrl,
  defaultOgImageUrl
}: SharedPromptPageProps) {
  // 他ページと共通の右下アクションメニューをクライアント側で登録する
  // Register the shared bottom-right action menu on the client.
  useEffect(() => {
    void import("../../../../scripts/components/popup_menu");
  }, []);

  const prompt = payload.prompt;
  const contentFormat = normalizePromptContentFormat(prompt?.content_format || prompt?.prompt_type || "");
  const mediaType = normalizePromptMediaType(prompt?.media_type || prompt?.prompt_type || "");
  const isSkillPrompt = contentFormat === "skill";
  const promptTitle = prompt?.title || "共有プロンプト";
  const pageTitle = `${promptTitle} | Chat Core 共有`;
  const description = buildMetaDescription(payload);
  const formatLabel = getPromptFormatLabel(contentFormat);
  const mediaLabel = getPromptMediaLabel(mediaType);
  const categoryLabel = getCategoryLabelOrFallback(prompt?.category);
  // ページURLからオリジンを取り出す（OG画像・パンくずの絶対URL組み立てに使用）
  // Extract the origin from the page URL (used to build absolute URLs for the OG image and breadcrumb)
  const pageOrigin = (() => {
    try {
      const parsed = new URL(pageUrl);
      return `${parsed.protocol}//${parsed.host}`;
    } catch {
      return "";
    }
  })();
  // 参照画像URLがある場合はそれをOG画像に使用し、ない場合はデフォルト画像を使う
  // Use the reference image as OG image if available, otherwise fall back to the default
  const ogImageUrl = resolveAbsoluteUrl(prompt?.reference_image_url, pageOrigin) || defaultOgImageUrl;
  // Schema.orgの構造化データ（プロンプトが存在する場合のみ付与）
  // Schema.org structured data (only included when prompt exists)
  const structuredData = prompt
    ? [
        {
          "@context": "https://schema.org",
          "@type": "CreativeWork",
          headline: promptTitle,
          name: promptTitle,
          description,
          genre: categoryLabel,
          keywords: [formatLabel, mediaLabel, categoryLabel].filter(Boolean).join(","),
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
        },
        // パンくずリストの構造化データ（検索結果での階層表示を助ける）
        // BreadcrumbList structured data (helps hierarchical display in search results)
        {
          "@context": "https://schema.org",
          "@type": "BreadcrumbList",
          itemListElement: [
            { "@type": "ListItem", position: 1, name: "Chat Core", item: pageOrigin ? `${pageOrigin}/` : "/" },
            { "@type": "ListItem", position: 2, name: "プロンプト共有", item: pageOrigin ? `${pageOrigin}/prompt_share` : "/prompt_share" },
            { "@type": "ListItem", position: 3, name: promptTitle, item: pageUrl }
          ]
        }
      ]
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
      />

      <div className="shared-prompt-page">
        {/* 他ページと共通の右下メニュー / Shared bottom-right menu used across pages */}
        <action-menu></action-menu>

        {/* パンくずナビ（プロンプト共有トップへの内部リンク） / Breadcrumb nav (internal link back to the prompt share top) */}
        <nav className="shared-prompt-breadcrumb" aria-label="パンくずリスト">
          <ol>
            <li><Link href="/">Chat Core</Link></li>
            <li><Link href="/prompt_share">プロンプト共有</Link></li>
            <li aria-current="page">{promptTitle}</li>
          </ol>
        </nav>

        {payload.error ? (
          <div className="shared-prompt-state shared-prompt-state--error">{payload.error}</div>
        ) : prompt ? (
          <article className="shared-prompt-shell">
            <header className="shared-prompt-header">
              <p className="shared-prompt-kicker">Prompt Share</p>
              <div className="shared-prompt-pills" aria-label="投稿のフォーマットと生成メディア">
                <span className="shared-prompt-pill">フォーマット: {formatLabel}</span>
                <span className="shared-prompt-pill shared-prompt-pill--media">生成メディア: {mediaLabel}</span>
              </div>
              <h1>{promptTitle}</h1>
              <div className="shared-prompt-meta">
                <span><i className="bi bi-folder2-open" aria-hidden="true" /> カテゴリ: {categoryLabel}</span>
                <span><i className="bi bi-person-circle" aria-hidden="true" /> 投稿者: {prompt.author || "匿名ユーザー"}</span>
                {prompt.created_at ? <span><i className="bi bi-calendar3" aria-hidden="true" /> 投稿日: {formatDate(prompt.created_at)}</span> : null}
                {prompt.ai_model ? <span><i className="bi bi-cpu" aria-hidden="true" /> 使用AI: {prompt.ai_model}</span> : null}
              </div>
            </header>

            {/* 作例メディア（現状は画像プレビュー対応） / Reference media (currently image preview) */}
            {prompt.reference_image_url ? (
              <div className="shared-prompt-image">
                <img src={prompt.reference_image_url} alt={prompt.title || "共有プロンプトの作例メディア"} />
              </div>
            ) : null}

            {/* スキルプロンプト以外はプロンプト本文を表示 / Show prompt content for non-skill prompts */}
            {!isSkillPrompt ? (
              <section className="shared-prompt-section">
                <h2><i className="bi bi-file-earmark-text" aria-hidden="true" /> 内容</h2>
                <MarkdownContent text={prompt.content || ""} ssrHtml={promptHtml.content} className="md-content" />
              </section>
            ) : null}

            {!isSkillPrompt && prompt.input_examples ? (
              <section className="shared-prompt-section">
                <h2><i className="bi bi-box-arrow-in-right" aria-hidden="true" /> 入力例</h2>
                <MarkdownContent text={prompt.input_examples} ssrHtml={promptHtml.inputExamples} className="md-content" />
              </section>
            ) : null}

            {!isSkillPrompt && prompt.output_examples ? (
              <section className="shared-prompt-section">
                <h2><i className="bi bi-box-arrow-right" aria-hidden="true" /> 出力例</h2>
                <MarkdownContent text={prompt.output_examples} ssrHtml={promptHtml.outputExamples} className="md-content" />
              </section>
            ) : null}

            {/* スキルプロンプトのMarkdown定義 / Skill prompt Markdown definition */}
            {prompt.skill_markdown ? (
              <section className="shared-prompt-section">
                <h2><i className="bi bi-stars" aria-hidden="true" /> SKILL定義 (Markdown)</h2>
                <MarkdownContent text={prompt.skill_markdown} ssrHtml={promptHtml.skillMarkdown} className="md-content" />
              </section>
            ) : null}

            {/* スキルプロンプトの追加Pythonスクリプト / Additional Python script for skill prompts */}
            {prompt.skill_python_script ? (
              <section className="shared-prompt-section">
                <h2><i className="bi bi-filetype-py" aria-hidden="true" /> 追加 Python スクリプト</h2>
                <MarkdownContent
                  text={buildSkillScriptMarkdown(prompt.skill_python_script)}
                  ssrHtml={promptHtml.skillPythonScript}
                  className="md-content"
                />
              </section>
            ) : null}

            {/* プロンプト共有トップへの誘導（内部リンク） / CTA back to the prompt share top (internal link) */}
            <footer className="shared-prompt-cta">
              <h2>ほかの公開プロンプトも見る</h2>
              <p>Chat Core のプロンプト共有では、文章作成・画像生成・スキルなど、さまざまなカテゴリの公開プロンプトを検索・閲覧できます。</p>
              <Link href="/prompt_share" className="shared-prompt-cta__button">
                <i className="bi bi-collection" aria-hidden="true" /> プロンプト共有ページへ
              </Link>
            </footer>

            {recommendedPrompts.length > 0 ? (
              <section className="shared-prompt-recommendations" aria-labelledby="shared-prompt-recommendations-title">
                <div className="shared-prompt-recommendations__heading">
                  <div>
                    <p>Discover more</p>
                    <h2 id="shared-prompt-recommendations-title">
                      <i className="bi bi-stars" aria-hidden="true" /> おすすめのプロンプト
                    </h2>
                  </div>
                  <Link href="/prompt_share">すべて見る <i className="bi bi-arrow-right" aria-hidden="true" /></Link>
                </div>
                <div className="shared-prompt-recommendations__grid">
                  {recommendedPrompts.map((recommendedPrompt) => {
                    const recommendationId = recommendedPrompt.id;
                    if (recommendationId === undefined || recommendationId === null) return null;

                    const recommendationFormat = normalizePromptContentFormat(
                      recommendedPrompt.content_format || recommendedPrompt.prompt_type || ""
                    );
                    const recommendationMedia = normalizePromptMediaType(
                      recommendedPrompt.media_type || recommendedPrompt.prompt_type || ""
                    );

                    return (
                      <Link
                        key={String(recommendationId)}
                        href={buildPromptPath(recommendationId, recommendedPrompt.title)}
                        className="shared-prompt-recommendation-card"
                      >
                        {recommendedPrompt.reference_image_url ? (
                          <img
                            src={recommendedPrompt.reference_image_url}
                            alt=""
                            loading="lazy"
                            decoding="async"
                          />
                        ) : null}
                        <div className="shared-prompt-recommendation-card__body">
                          <div className="shared-prompt-recommendation-card__pills">
                            <span>{getCategoryLabelOrFallback(recommendedPrompt.category)}</span>
                            <span>{getPromptFormatLabel(recommendationFormat)}</span>
                            <span>{getPromptMediaLabel(recommendationMedia)}</span>
                          </div>
                          <h3>{recommendedPrompt.title || "共有プロンプト"}</h3>
                          <p>{buildRecommendationPreview(recommendedPrompt)}</p>
                          <span className="shared-prompt-recommendation-card__link">詳しく見る <i className="bi bi-arrow-right" aria-hidden="true" /></span>
                        </div>
                      </Link>
                    );
                  })}
                </div>
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
