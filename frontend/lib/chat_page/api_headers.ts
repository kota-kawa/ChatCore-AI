// Structured UI responses are negotiated explicitly so older clients can keep receiving text-only replies.
// Structured UI の応答は明示的にネゴシエーションし、未対応クライアントには文章だけを返せるようにする。
export const CHATCORE_UI_VERSION_HEADERS = { "X-ChatCore-UI-Version": "1" } as const;

export function withChatCoreUiVersionHeader(headers: Record<string, string> = {}) {
  return {
    ...headers,
    ...CHATCORE_UI_VERSION_HEADERS,
  };
}
