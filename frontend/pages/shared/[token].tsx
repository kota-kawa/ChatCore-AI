import type { GetServerSideProps } from "next";
import { SandboxArtifactFrame } from "../../components/chat_page/sandbox_artifact_frame";
import MarkdownContent from "../../components/MarkdownContent";
import { SeoHead } from "../../components/SeoHead";
import { formatDateTime } from "../../lib/datetime";
import type { ChatMessagePart } from "../../lib/chat_page/types";
import { resilientFetch } from "../../scripts/core/resilient_fetch";

// 共有チャットの個別メッセージを表す型
// Represents a single message in a shared chat
type SharedMessage = {
  message: string;
  message_parts?: ChatMessagePart[];
  sender: "user" | "assistant" | string;
  timestamp?: string;
};

// 共有チャットルームのメタ情報を表す型
// Represents metadata for a shared chat room
type SharedRoom = {
  id: string;
  title?: string;
  created_at?: string;
};

// バックエンドから取得した共有チャット全体のペイロード型
// Top-level payload returned from the shared chat API
type SharedChatPayload = {
  room?: SharedRoom;
  messages?: SharedMessage[];
  error?: string;
};

// ページコンポーネントに渡されるProps型
// Props passed to the SharedChatPage component
type SharedChatPageProps = {
  payload: SharedChatPayload;
  pageUrl: string;
  ogImageUrl: string;
};

// APIレスポンスの型エイリアス（ペイロードと同一構造）
// Type alias for the API response (same shape as the payload)
type SharedChatResponse = SharedChatPayload;

// DBに保存されたHTMLエスケープ済み文字列を表示用プレーンテキストに戻す
// Reverses HTML entity encoding so stored messages render correctly
function decodeStoredMessage(raw: string) {
  return raw
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}

// リバースプロキシ経由でも正しいホスト名を取得するためにヘッダーを正規化する
// Normalises the Host header so it works correctly behind reverse proxies
function normalizeHostHeader(header: string | string[] | undefined) {
  if (Array.isArray(header)) return header[0] || "";
  return header || "";
}

// カンマ区切りで複数の値が来た場合に最初のプロトコルだけを取り出す
// Extracts only the first protocol value when the header contains a comma-separated list
function normalizeProtoHeader(header: string | string[] | undefined) {
  const raw = Array.isArray(header) ? header[0] : header;
  if (!raw) return "";
  return raw.split(",")[0]?.trim() || "";
}

// OGP用のdescriptionからMarkdown記法や画像・リンクを除去してプレーンテキスト化する
// Strips Markdown syntax to produce plain text suitable for OGP meta descriptions
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

// SEOのmeta descriptionが長くなり過ぎないよう指定文字数で切り詰める
// Truncates text to keep meta descriptions within a reasonable length for SEO
function truncateText(value: string, maxLength = 140) {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1).trimEnd()}…`;
}

// ページのmeta descriptionをペイロードの内容から動的に生成する
// Dynamically builds the meta description from the payload content
function buildMetaDescription(payload: SharedChatPayload) {
  if (payload.error) {
    return truncateText(payload.error);
  }
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  // アシスタントの最初のメッセージを優先してdescriptionのソースにする
  // Prefer the first assistant message as the description source for richer preview text
  const previewTarget = messages.find((item) => item.sender === "assistant") || messages[0];
  if (!previewTarget?.message) {
    return "Chat Core で共有されたチャットの閲覧ページです。";
  }
  const normalized = stripPreviewText(decodeStoredMessage(previewTarget.message));
  return truncateText(normalized || "Chat Core で共有されたチャットの閲覧ページです。");
}

// サーバーサイドでトークンを検証し、共有チャットデータをバックエンドから取得する
// Validates the token server-side and fetches shared chat data from the backend
export const getServerSideProps: GetServerSideProps<SharedChatPageProps> = async (context) => {
  const rawToken = context.params?.token;
  const token = Array.isArray(rawToken) ? rawToken[0] : rawToken;
  if (!token) {
    return { notFound: true };
  }

  const backendUrl = process.env.BACKEND_URL || "http://localhost:5004";
  // プロキシ環境でも正しい正規URLを構築するためにリクエストヘッダーを参照する
  // Use request headers to build the correct canonical URL when running behind a proxy
  const host = normalizeHostHeader(context.req.headers["x-forwarded-host"]) || normalizeHostHeader(context.req.headers.host);
  const proto = normalizeProtoHeader(context.req.headers["x-forwarded-proto"])
    || (process.env.NODE_ENV === "development" ? "http" : "https");
  const origin = host ? `${proto}://${host}` : "";
  const resolvedPath = context.resolvedUrl || `/shared/${encodeURIComponent(token)}`;
  const pageUrl = origin ? `${origin}${resolvedPath}` : resolvedPath;
  const ogImageUrl = origin ? `${origin}/static/Chat-Core-OG-compressed.jpg` : "/static/Chat-Core-OG-compressed.jpg";

  let payload: SharedChatPayload = {};

  try {
    const res = await resilientFetch(`${backendUrl}/api/shared_chat_room?token=${encodeURIComponent(token)}`);
    const data: SharedChatResponse = await res.json().catch(() => ({}));
    // バックエンドのステータスコードをそのままクライアントに転送する
    // Forward the backend status code to the client response
    if (!res.ok) {
      context.res.statusCode = res.status;
    }
    payload = data && typeof data === "object" ? data : {};
    if (!res.ok && !payload.error) {
      payload.error = `共有チャットの取得に失敗しました (${res.status})`;
    }
  } catch {
    context.res.statusCode = 500;
    payload = { error: "共有チャットの取得に失敗しました。" };
  }

  return {
    props: {
      payload,
      pageUrl,
      ogImageUrl
    }
  };
};

// 共有チャットの読み取り専用ビューを表示するページコンポーネント
// Page component that renders a read-only view of a shared chat conversation
export default function SharedChatPage({ payload, pageUrl, ogImageUrl }: SharedChatPageProps) {
  const title = payload.room?.title || "共有チャット";
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  const pageTitle = `${title} | Chat Core 共有`;
  const description = buildMetaDescription(payload);
  // エラー時はStructured Dataを出力せずインデックスもブロックする
  // Suppress structured data on error pages to prevent indexing invalid content
  const structuredData = !payload.error
    ? {
        "@context": "https://schema.org",
        "@type": "DiscussionForumPosting",
        headline: title,
        description,
        datePublished: payload.room?.created_at || undefined,
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
        noindex={Boolean(payload.error)}
        structuredData={structuredData}
      >
        <link rel="stylesheet" href="/static/css/pages/chat/shared_chat.css" />
      </SeoHead>

      <div className="shared-chat-page">
        {/* エラー時はエラーメッセージのみ表示する / Show only the error message when the fetch failed */}
        {payload.error ? (
          <div className="shared-chat-error cc-fade-in">{payload.error}</div>
        ) : (
          <div className="shared-chat-shell cc-fade-in">
            <header className="shared-chat-header">
              <h1 className="shared-chat-header__title">{title}</h1>
              {payload.room?.created_at ? (
                <p className="shared-chat-header__meta">
                  作成日: {formatDateTime(payload.room.created_at) || payload.room.created_at}
                </p>
              ) : null}
            </header>

            <main className="shared-chat-messages">
              {messages.length === 0 ? (
                <p className="shared-chat-empty">この共有チャットにはまだメッセージがありません。</p>
              ) : null}

              {messages.map((message, index) => {
                // "user" 以外の送信者はすべて "assistant" として扱う
                // Treat any sender value other than "user" as "assistant"
                const normalizedSender = message.sender === "user" ? "user" : "assistant";
                const decoded = decodeStoredMessage(message.message || "");
                const parts = Array.isArray(message.message_parts) ? message.message_parts : [];
                return (
                  <article
                    key={`${normalizedSender}-${index}-${message.timestamp || ""}`}
                    className={`shared-chat-message shared-chat-message--${normalizedSender}`}
                  >
                    {normalizedSender === "assistant" && parts.length > 0 ? (
                      <div className="shared-chat-message__parts">
                        {parts.map((part, partIndex) => {
                          if (part.type === "text") {
                            return (
                              <MarkdownContent
                                key={`text-${partIndex}`}
                                text={part.text}
                                className="md-content"
                              />
                            );
                          }
                          if (part.type === "sandbox_artifact") {
                            return (
                              <SandboxArtifactFrame
                                key={`artifact-${partIndex}`}
                                artifact={part.artifact}
                              />
                            );
                          }
                          if (part.type === "interactive_buttons") {
                            {/* 共有ページでは対話型ボタンは機能しないため非活性状態で表示する */}
                            {/* Interactive buttons are non-functional on shared pages, so display them as disabled */}
                            return (
                              <div key={`buttons-${partIndex}`} style={{ marginTop: "1rem", opacity: 0.7 }}>
                                <strong>{part.buttons.question}</strong>
                                <div style={{ fontSize: "0.85rem", color: "#666" }}>(対話型ボタンは共有画面では動作しません)</div>
                              </div>
                            );
                          }
                          return null;
                        })}
                      </div>
                    ) : normalizedSender === "assistant" ? (
                      <MarkdownContent text={decoded} className="md-content" />
                    ) : (
                      decoded
                    )}
                  </article>
                );
              })}
            </main>

            <footer className="shared-chat-footer">
              このページは読み取り専用です。送信や編集はできません。
            </footer>
          </div>
        )}
      </div>
    </>
  );
}
