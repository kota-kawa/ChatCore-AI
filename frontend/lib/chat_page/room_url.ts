// ホーム画面（/）をルーム指定で開く URL の組み立てと、開いたときの room クエリの取り込み。
// 所有者の確認はサーバーの履歴 API が行うので、ここでは URL として妥当かどうかだけを見る。
// Builds the home-page URL that opens a given room, and consumes the room query when the page opens.
// Ownership is checked by the server's history API, so this module only checks that the value is usable.

import Router from "next/router";

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

// room クエリを取り除いた URL へ置き換える。Next.js のルーターが動いているときはルーター経由（shallow）にする。
// 履歴の state と router.asPath がルーターの持ち物で、history.replaceState だけで URL を変えると state の as/url と
// asPath に ?room= が残り、別ページから戻ったときや router.replace(router.asPath) で room が復活するため。
// ルーターが無い環境（単体テストなど）では history.replaceState にする。
// Replaces the URL with one without the room query. When the Next.js router is running, go through it (shallow):
// the history state and router.asPath belong to the router, and changing only the URL with history.replaceState leaves
// ?room= in the state's as/url and in asPath, so the room would come back on returning from another page or on
// router.replace(router.asPath). Without a router (unit tests, for example) fall back to history.replaceState.
function replaceUrlWithoutRoom(): void {
  try {
    if (Router.router) {
      const url = new URL(Router.asPath, window.location.origin);
      url.searchParams.delete(ROOM_QUERY_PARAM);
      void Router.replace(`${url.pathname}${url.search}${url.hash}`, undefined, { shallow: true, scroll: false }).catch(() => {});
      return;
    }
  } catch {
    // ルーターが使えないときは下の history.replaceState に任せる。
    // Fall through to history.replaceState below when the router is unusable.
  }
  const url = new URL(window.location.href);
  url.searchParams.delete(ROOM_QUERY_PARAM);
  window.history.replaceState(window.history.state, document.title, `${url.pathname}${url.search}${url.hash}`);
}

// URL の room クエリを取り除き、使える値ならルーム ID を返す。クエリが無い・使えない値なら null。
// 取り除くのは履歴を汚さないため。ほかのクエリとハッシュは残す。
// Strips the room query from the URL and returns the room id when it is usable, or null when absent or unusable.
// Stripping keeps the address bar clean; other query parameters and the hash stay.
export function consumeRoomIdFromUrl(): string | null {
  if (typeof window === "undefined") return null;

  const params = new URL(window.location.href).searchParams;
  if (!params.has(ROOM_QUERY_PARAM)) return null;

  const roomId = normalizeRoomId(params.get(ROOM_QUERY_PARAM));
  replaceUrlWithoutRoom();
  return roomId;
}
