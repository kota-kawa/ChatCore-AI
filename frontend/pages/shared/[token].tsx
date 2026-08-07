import type { GetServerSideProps } from "next";
import { useEffect } from "react";
import { SharedChatContinueButton } from "../../components/shared_chat/shared_chat_continue_button";
import { SharedChatMessageList } from "../../components/shared_chat/shared_chat_message_list";
import { SeoHead } from "../../components/SeoHead";
import { formatDateTime } from "../../lib/datetime";
import { decodeStoredMessage } from "../../lib/shared_chat/message_text";
import type { SharedChatPayload } from "../../lib/shared_chat/types";
import { resilientFetch } from "../../scripts/core/resilient_fetch";
import { useTranslation } from "../../contexts/locale_context";

// ページコンポーネントに渡されるProps型
// Props passed to the SharedChatPage component
type SharedChatPageProps = {
  payload: SharedChatPayload;
  pageUrl: string;
  ogImageUrl: string;
  // 「このチャットを続ける」で複製元を指定するための共有トークン。
  // Share token identifying the source conversation for "continue this chat".
  token: string;
};

// APIレスポンスの型エイリアス（ペイロードと同一構造）
// Type alias for the API response (same shape as the payload)
type SharedChatResponse = SharedChatPayload;

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
function buildMetaDescription(payload: SharedChatPayload, english = false) {
  if (payload.error) {
    return truncateText(payload.error);
  }
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  // アシスタントの最初のメッセージを優先してdescriptionのソースにする
  // Prefer the first assistant message as the description source for richer preview text
  const previewTarget = messages.find((item) => item.sender === "assistant") || messages[0];
  if (!previewTarget?.message) {
    return english ? "A read-only chat shared from Chat Core." : "Chat Core で共有されたチャットの閲覧ページです。";
  }
  const normalized = stripPreviewText(decodeStoredMessage(previewTarget.message));
  return truncateText(normalized || (english ? "A read-only chat shared from Chat Core." : "Chat Core で共有されたチャットの閲覧ページです。"));
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
      ogImageUrl,
      token
    }
  };
};

// 共有チャットの読み取り専用ビューを表示するページコンポーネント
// Page component that renders a read-only view of a shared chat conversation
export default function SharedChatPage({ payload, pageUrl, ogImageUrl, token }: SharedChatPageProps) {
  const { locale } = useTranslation();
  const english = locale === "en";
  // 他ページと共通の右下アクションメニューをクライアント側で登録する
  // Register the shared bottom-right action menu on the client.
  useEffect(() => {
    void import("../../scripts/components/popup_menu");
  }, []);

  const title = payload.room?.title || (english ? "Shared chat" : "共有チャット");
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  const pageTitle = `${title} | ${english ? "Shared on Chat Core" : "Chat Core 共有"}`;
  const description = buildMetaDescription(payload, english);
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
        inLanguage: locale,
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
      />

      {/* chat-page-shell を付けることで、通常チャットと同じデザイントークンと
          メッセージのスタイル（chat_messages.css）がそのまま適用される。 */}
      {/* The chat-page-shell class brings in the same design tokens and message styles
          (chat_messages.css) that the regular chat view uses. */}
      <div className="shared-chat-page chat-page-shell">
        {/* 他ページと共通の右下メニュー / Shared bottom-right menu used across pages */}
        <action-menu></action-menu>

        {/* エラー時はエラーメッセージのみ表示する / Show only the error message when the fetch failed */}
        {payload.error ? (
          <div className="shared-chat-error cc-fade-in">{payload.error}</div>
        ) : (
          <div className="shared-chat-shell cc-fade-in">
            <header className="shared-chat-header">
              <div className="shared-chat-header__text">
                <h1 className="shared-chat-header__title">{title}</h1>
                <p className="shared-chat-header__meta">
                  <span className="shared-chat-header__badge">
                    <i className="bi bi-eye" aria-hidden="true"></i>
                    {english ? "Read-only" : "読み取り専用"}
                  </span>
                  {payload.room?.created_at ? (
                    <span>
                      {english ? "Created" : "作成日"}: {formatDateTime(payload.room.created_at) || payload.room.created_at}
                    </span>
                  ) : null}
                </p>
              </div>
              <SharedChatContinueButton token={token} />
            </header>

            <main className="shared-chat-messages">
              <SharedChatMessageList
                messages={messages}
                emptyLabel={english ? "This shared chat has no messages yet." : "この共有チャットにはまだメッセージがありません。"}
              />
            </main>

            <footer className="shared-chat-footer">
              {english
                ? "This page is read-only. “Continue this chat” copies the conversation into your own chat; the original stays unchanged."
                : "このページは読み取り専用です。「このチャットを続ける」を押すと、会話が自分のチャットに複製され、共有元は変更されません。"}
              <SharedChatContinueButton token={token} />
            </footer>
          </div>
        )}
      </div>
    </>
  );
}
