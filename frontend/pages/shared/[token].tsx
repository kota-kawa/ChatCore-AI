import Head from "next/head";
import type { GetServerSideProps } from "next";
import MarkdownContent from "../../components/MarkdownContent";
import { formatDateTime } from "../../lib/datetime";

type SharedMessage = {
  message: string;
  sender: "user" | "assistant" | string;
  timestamp?: string;
};

type SharedRoom = {
  id: string;
  title?: string;
  created_at?: string;
};

type SharedChatPayload = {
  room?: SharedRoom;
  messages?: SharedMessage[];
  error?: string;
};

type SharedChatPageProps = {
  payload: SharedChatPayload;
  pageUrl: string;
  ogImageUrl: string;
};

type SharedChatResponse = SharedChatPayload;

function decodeStoredMessage(raw: string) {
  return raw
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
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

function buildMetaDescription(payload: SharedChatPayload) {
  if (payload.error) {
    return truncateText(payload.error);
  }
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  const previewTarget = messages.find((item) => item.sender === "assistant") || messages[0];
  if (!previewTarget?.message) {
    return "Chat Core で共有されたチャットの閲覧ページです。";
  }
  const normalized = stripPreviewText(decodeStoredMessage(previewTarget.message));
  return truncateText(normalized || "Chat Core で共有されたチャットの閲覧ページです。");
}

export const getServerSideProps: GetServerSideProps<SharedChatPageProps> = async (context) => {
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
  const resolvedPath = context.resolvedUrl || `/shared/${encodeURIComponent(token)}`;
  const pageUrl = origin ? `${origin}${resolvedPath}` : resolvedPath;
  const ogImageUrl = origin ? `${origin}/static/img.jpg` : "/static/img.jpg";

  let payload: SharedChatPayload = {};

  try {
    const res = await fetch(`${backendUrl}/api/shared_chat_room?token=${encodeURIComponent(token)}`);
    const data: SharedChatResponse = await res.json().catch(() => ({}));
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

export default function SharedChatPage({ payload, pageUrl, ogImageUrl }: SharedChatPageProps) {
  const title = payload.room?.title || "共有チャット";
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  const pageTitle = `${title} | Chat Core 共有`;
  const description = buildMetaDescription(payload);

  return (
    <>
      <Head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
        <title>{pageTitle}</title>
        <meta name="description" content={description} />
        <meta property="og:title" content={pageTitle} />
        <meta property="og:description" content={description} />
        <meta property="og:type" content="article" />
        <meta property="og:site_name" content="Chat Core" />
        <meta property="og:url" content={pageUrl} />
        <meta property="og:image" content={ogImageUrl} />
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content={pageTitle} />
        <meta name="twitter:description" content={description} />
        <meta name="twitter:image" content={ogImageUrl} />
        <link rel="stylesheet" href="/static/css/pages/chat/shared_chat.css" />
      </Head>

      <div className="shared-chat-page">
        {payload.error ? (
          <div className="shared-chat-error">{payload.error}</div>
        ) : (
          <div className="shared-chat-shell">
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
                const normalizedSender = message.sender === "user" ? "user" : "assistant";
                const decoded = decodeStoredMessage(message.message || "");
                return (
                  <article
                    key={`${normalizedSender}-${index}-${message.timestamp || ""}`}
                    className={`shared-chat-message shared-chat-message--${normalizedSender}`}
                  >
                    {normalizedSender === "assistant" ? (
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
