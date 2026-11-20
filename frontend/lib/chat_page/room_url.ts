// ホーム画面（/）をルーム指定で開く URL の組み立てと、開いたときの room クエリの取り込み。
// 所有者の確認はサーバーの履歴 API が行うので、ここでは URL として妥当かどうかだけを見る。
// Builds the home-page URL that opens a given room, and consumes the room query when the page opens.
// Ownership is checked by the server's history API, so this module only checks that the value is usable.

const ROOM_QUERY_PARAM = "room";
// ルーム ID の上限。サーバーの MAX_CHAT_ROOM_ID_LENGTH（services/request_models.py）と揃える。
// Upper bound for a room id; keep in step with the server's MAX_CHAT_ROOM_ID_LENGTH (services/request_models.py).
const MAX_ROOM_ID_LENGTH = 128;
// 制御文字と、壊れた %エスケープが復号されたときに入る U+FFFD は ID として使えない。
// Control characters, and U+FFFD which a malformed %-escape decodes to, cannot be part of an id.
function hasUnusableCharacter(value: string): boolean {
  return Array.from(value).some((character) => {
    const code = character.charCodeAt(0);
    return code < 0x20 || code === 0x7f || code === 0xfffd;
  });
}

// ルーム ID を使える形に整える。使えない値（空・長すぎる・制御文字を含む）は null。
// Normalizes a room id into a usable form; returns null for values that cannot be used (empty, too long, control characters).
function normalizeRoomId(value: string | null): string | null {
  const roomId = value?.trim();
  if (!roomId || roomId.length > MAX_ROOM_ID_LENGTH || hasUnusableCharacter(roomId)) return null;
  return roomId;
}

// 指定ルームをホーム画面で開く URL を返す。ルーム ID はクライアント採番の任意の文字列なのでエンコードする。
// Returns the home-page URL that opens the given room; the id is client-generated free text, so it is encoded.
export function buildHomeRoomUrl(roomId: string): string {
  const params = new URLSearchParams({ [ROOM_QUERY_PARAM]: roomId });
  return `/?${params.toString()}`;
}

// URL の room クエリを取り除き、使える値ならルーム ID を返す。クエリが無い・使えない値なら null。
// 取り除くのは履歴を汚さないため。ほかのクエリとハッシュは残す。
// history.state は Next.js のルーターが戻る操作の復元に使うので、そのまま引き継ぐ。
// Strips the room query from the URL and returns the room id when it is usable, or null when absent or unusable.
// Stripping keeps the address bar clean; other query parameters and the hash stay.
// history.state is carried over because Next.js's router relies on it to handle back navigation.
export function consumeRoomIdFromUrl(): string | null {
  if (typeof window === "undefined") return null;

  const url = new URL(window.location.href);
  if (!url.searchParams.has(ROOM_QUERY_PARAM)) return null;

  const roomId = normalizeRoomId(url.searchParams.get(ROOM_QUERY_PARAM));
  url.searchParams.delete(ROOM_QUERY_PARAM);
  window.history.replaceState(window.history.state, document.title, `${url.pathname}${url.search}${url.hash}`);
  return roomId;
}
