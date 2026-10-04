// アカウント切り替えメニューのデータ層。
// ログイン状態の正本はサーバー（待機セッション）で、ここが localStorage に持つのは
// 「このブラウザでログインしたことがあるアカウント」の表示用の控えだけ。控えがあっても
// サーバーにセッションが無ければ切り替えはできず、ログインし直しになる。
// Data layer for the account switcher menu.
// The server (parked sessions) is the source of truth for who is signed in. What this keeps
// in localStorage is only a display record of accounts that have signed in on this browser:
// a record without a server session cannot be switched to and needs a fresh sign-in.

import { clearAllHomePagePersistedState, clearStoredUserScope } from "../chat_page/storage";
import { clearPersistentCache } from "../data/persistent_cache";
import { clearCachedUserIconProfile } from "../../scripts/core/user_icon_cache";
import { resilientFetch } from "../../scripts/core/resilient_fetch";

const KNOWN_ACCOUNTS_KEY = "chatcore.accountSwitcher.knownAccounts";
const MAX_KNOWN_ACCOUNTS = 8;
const ADD_ACCOUNT_QUERY_PARAM = "add_account";
const LOGIN_EMAIL_QUERY_PARAM = "email";

export type AccountIdentity = {
  username: string;
  email: string;
  avatarUrl: string;
};

export type KnownAccount = AccountIdentity & { userId: number };

export type SwitchableAccount = KnownAccount & { signedIn: boolean };

export type SignedInAccounts = {
  current: KnownAccount | null;
  others: KnownAccount[];
};

function toKnownAccount(value: unknown): KnownAccount | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const userId = record.userId ?? record.user_id;
  if (typeof userId !== "number" || !Number.isInteger(userId)) return null;
  const text = (field: unknown) => (typeof field === "string" ? field.trim() : "");
  return {
    userId,
    username: text(record.username),
    email: text(record.email),
    avatarUrl: text(record.avatarUrl ?? record.avatar_url)
  };
}

export function readKnownAccounts(): KnownAccount[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KNOWN_ACCOUNTS_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.map(toKnownAccount).filter((account): account is KnownAccount => account !== null);
  } catch {
    return [];
  }
}

function writeKnownAccounts(accounts: KnownAccount[]) {
  try {
    localStorage.setItem(KNOWN_ACCOUNTS_KEY, JSON.stringify(accounts.slice(0, MAX_KNOWN_ACCOUNTS)));
  } catch {
    // localStorage が使えなくてもメニューは表示できる / The menu still works without localStorage
  }
}

// ログイン中と確認できたアカウントを控えの先頭へ入れ直す（名前やアイコンの変更も反映する）。
// Move accounts confirmed as signed in to the front of the record, refreshing name and avatar.
export function rememberAccounts(accounts: KnownAccount[]) {
  const refreshedIds = new Set(accounts.map((account) => account.userId));
  writeKnownAccounts([...accounts, ...readKnownAccounts().filter((account) => !refreshedIds.has(account.userId))]);
}

export function forgetKnownAccount(userId: number) {
  writeKnownAccounts(readKnownAccounts().filter((account) => account.userId !== userId));
}

// メニューに並べる「表示中以外」のアカウント。ログイン中を先に、控えだけ残るものを後に置く。
// The non-active accounts for the menu: signed-in ones first, then the ones only on record.
export function listSwitchableAccounts(signedIn: SignedInAccounts, known: KnownAccount[]): SwitchableAccount[] {
  const signedInIds = new Set(signedIn.others.map((account) => account.userId));
  const signedOut = known.filter(
    (account) => account.userId !== signedIn.current?.userId && !signedInIds.has(account.userId)
  );
  return [
    ...signedIn.others.map((account) => ({ ...account, signedIn: true })),
    ...signedOut.map((account) => ({ ...account, signedIn: false }))
  ];
}

export async function fetchSignedInAccounts(): Promise<SignedInAccounts | null> {
  try {
    const response = await resilientFetch("/api/auth/accounts", { credentials: "same-origin" });
    if (!response.ok) return null;
    const data = (await response.json()) as { accounts?: unknown };
    if (!Array.isArray(data.accounts)) return null;
    const result: SignedInAccounts = { current: null, others: [] };
    for (const entry of data.accounts) {
      const account = toKnownAccount(entry);
      if (!account) continue;
      if ((entry as { current?: unknown }).current === true) {
        result.current = account;
      } else {
        result.others.push(account);
      }
    }
    return result;
  } catch (error) {
    console.warn("account_switcher: failed to load accounts", error);
    return null;
  }
}

export type AccountSwitchResult = "switched" | "signed_out" | "failed";

// signed_out はサーバーに待機セッションが無い（期限切れなど）ことを表し、ログインし直しが要る。
// failed は一時的な失敗で、セッションは残っているかもしれないのでログインへは送らない。
// "signed_out" means the server holds no parked session (expired, for example) and a fresh
// sign-in is needed. "failed" is a transient failure: the session may still be there, so the
// user is not sent to the login page.
export async function requestAccountSwitch(userId: number): Promise<AccountSwitchResult> {
  try {
    const response = await resilientFetch("/api/auth/accounts/switch", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId })
    });
    if (response.ok) return "switched";
    return response.status === 404 ? "signed_out" : "failed";
  } catch (error) {
    console.warn("account_switcher: switch request failed", error);
    return "failed";
  }
}

// ログイン中のまま別アカウントでログインするためのログイン画面の URL。
// Login page URL for signing in to another account while staying signed in.
export function buildAddAccountUrl(email = ""): string {
  const params = new URLSearchParams({ [ADD_ACCOUNT_QUERY_PARAM]: "1" });
  if (email) params.set(LOGIN_EMAIL_QUERY_PARAM, email);
  return `/login?${params.toString()}`;
}

export function isAddAccountRequest(query: URLSearchParams): boolean {
  return query.get(ADD_ACCOUNT_QUERY_PARAM) === "1";
}

export function getLoginEmailHint(query: URLSearchParams): string {
  return (query.get(LOGIN_EMAIL_QUERY_PARAM) || "").trim();
}

// 利用者が替わる（ログアウト・切り替え・別アカウントでのログイン）ときに、直前の利用者の
// データをこのブラウザから消す。永続 SWR キャッシュ、ホーム画面のチャット全文・生成状態・下書き、
// 持ち主の記録、アイコンの表示キャッシュが対象で、次の利用者に前の利用者の本文を見せない。
// アカウントの控え（名前・メール・アイコン）は切り替えメニューに使うので消さない。
// Wipe the outgoing user's data from this browser whenever the user changes (sign-out, switch,
// or signing in as another account): the persisted SWR cache, the home page's chat text,
// generation state and drafts, the owner marker and the icon's display cache, so the next user
// never sees the previous user's text. The account record (name, email, avatar) is kept because
// the switcher menu needs it.
export function clearPreviousUserBrowserState() {
  clearPersistentCache();
  clearAllHomePagePersistedState();
  clearStoredUserScope();
  clearCachedUserIconProfile();
}
