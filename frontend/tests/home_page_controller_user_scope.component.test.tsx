import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useHomePageController } from "../hooks/chat_page/use_home_page_controller";
import { readStoredHistory, readStoredUserScope, writeStoredActiveChatRoom, writeStoredHomePageViewState } from "../lib/chat_page/storage";
import { resilientFetch } from "../scripts/core/resilient_fetch";

vi.mock("../scripts/core/toast", () => ({ showToast: vi.fn() }));
vi.mock("../scripts/components/prompt_assist", () => ({ initPromptAssist: vi.fn(() => ({ destroy: vi.fn() })) }));
vi.mock("../scripts/core/resilient_fetch", () => ({ resilientFetch: vi.fn() }));

const fetchMock = vi.mocked(resilientFetch);

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    status: 200,
    headers: { get: (name: string) => (name.toLowerCase() === "content-type" ? "application/json" : null) },
    json: async () => payload,
    text: async () => JSON.stringify(payload),
    clone() {
      return jsonResponse(payload);
    },
  } as unknown as Response;
}

function installMatchMediaStub() {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      onchange: null,
      dispatchEvent: () => false,
    }),
  });
}

// ログアウトを経由しないユーザー切り替え（別アカウントでの再ログインなど）から、
// 前の利用者のローカル本文を守る最後の砦。認証確認（/api/current_user）が別の
// 利用者を返した時点で、画面とローカル状態の両方を破棄することを確認する。
// The last line of defense protecting a previous user's local chat text from a
// user switch that skips logout (re-login as a different account, etc.). Once
// the auth check (/api/current_user) reports a different user, both the screen
// and the local state must be wiped.
describe("useHomePageController user scope reconciliation", () => {
  // これがレビューで指摘された主要シナリオ: ログイン済みの利用者ならほぼ全員が
  // userScope を記録済みなので、「userScope が記録されているか」では利用者1と
  // 利用者2を区別できない。区別できない以上、認証確認の応答が届くまでは本文を
  // 一切描画してはならない（レイアウト＝どの部屋・どの画面かは即時復元してよい）。
  // This is the primary scenario the review reported: almost every logged-in
  // user already has a recorded userScope, so "is userScope recorded" cannot
  // distinguish user 1 from user 2. Since it cannot distinguish them, no
  // message text may be painted until the auth check's response arrives
  // (restoring the layout — which room/view was active — instantly is fine).
  it("never paints a previous user's message text before auth resolves, even when userScope matches the stale cache", async () => {
    installMatchMediaStub();
    localStorage.clear();

    // ブラウザに残っていた利用者1の状態。userScope は "ほぼ全員" が持つ状態を
    // 再現するためにあえて記録済みにしておく（認証キャッシュも "ログイン中"の
    // まま残す）。
    // State left behind by user 1. userScope is deliberately already recorded,
    // reproducing the state "almost everyone" logged in is in (the auth cache
    // is also left "logged in").
    localStorage.setItem("chatcore.chat.userScope", "user:1");
    localStorage.setItem("chatcore.auth.loggedIn", "1");
    localStorage.setItem("chatcore.auth.cachedAt", String(Date.now()));
    writeStoredActiveChatRoom("room-of-user-1", "normal");
    writeStoredHomePageViewState("chat");
    localStorage.setItem(
      "chatHistory_room-of-user-1",
      JSON.stringify([{ text: "USER 1 PRIVATE MESSAGE", sender: "user" }]),
    );

    let resolveCurrentUser!: (response: Response) => void;
    const currentUserPromise = new Promise<Response>((resolve) => {
      resolveCurrentUser = resolve;
    });

    fetchMock.mockImplementation(async (url: unknown) => {
      const requestedUrl = String(url);
      if (requestedUrl.includes("current_user")) return currentUserPromise;
      return jsonResponse({});
    });

    const { result } = renderHook(() => useHomePageController());

    // 認証確認が解決する前: レイアウト（部屋・ビュー状態）は即時復元されて
    // よいが、本文は空でなければならない。ここが失敗する場合、fetch の
    // 往復時間だけ前の利用者の本文が画面に出てから消えるフラッシュが
    // 実際に起きている。
    // Before the auth check resolves: the layout (room/view state) may be
    // restored instantly, but the message text must be empty. If this fails,
    // the previous user's text is actually flashing on screen for the
    // duration of the fetch round trip.
    expect(result.current.pageViewState).toBe("chat");
    expect(result.current.messages).toEqual([]);
    expect(readStoredUserScope()).toBe("user:1");

    await act(async () => {
      resolveCurrentUser(jsonResponse({ logged_in: true, user: { id: 2 } }));
    });

    await waitFor(() => expect(readStoredUserScope()).toBe("user:2"));

    expect(readStoredHistory("room-of-user-1")).toEqual([]);
    expect(localStorage.getItem("chatcore.chat.activeRoomId")).toBeNull();
    await waitFor(() => expect(result.current.pageViewState).toBe("setup"));
    expect(result.current.messages).toEqual([]);
  });

  // 本文の即時復元をやめても、機微でないレイアウト（部屋の選択・画面状態）は
  // 引き続き認証解決を待たずに復元されることを確認する。ここが壊れると、
  // 正当な同一利用者の再訪問のたびにセットアップ画面が一瞬表示されてしまう。
  // Confirm that giving up on instantly restoring message text does not
  // regress the non-sensitive layout restore (which room, which view). If
  // this breaks, a legitimate same-user revisit would flash the setup view
  // every time.
  it("still restores the room/view layout instantly for a legitimate revisit", async () => {
    installMatchMediaStub();
    localStorage.clear();

    localStorage.setItem("chatcore.chat.userScope", "user:1");
    localStorage.setItem("chatcore.auth.loggedIn", "1");
    localStorage.setItem("chatcore.auth.cachedAt", String(Date.now()));
    writeStoredActiveChatRoom("room-of-user-1", "normal");
    writeStoredHomePageViewState("chat");
    localStorage.setItem(
      "chatHistory_room-of-user-1",
      JSON.stringify([{ text: "user 1's own message", sender: "user" }]),
    );

    const currentUserPromise = new Promise<Response>(() => {
      // 認証確認をあえて未解決のままにし、レイアウト復元が解決を待たずに
      // 行われることを確認する。
      // Deliberately leave the auth check unresolved to confirm the layout
      // restore does not wait for it.
    });

    fetchMock.mockImplementation(async (url: unknown) => {
      const requestedUrl = String(url);
      if (requestedUrl.includes("current_user")) return currentUserPromise;
      return jsonResponse({});
    });

    const { result } = renderHook(() => useHomePageController());

    expect(result.current.pageViewState).toBe("chat");
    expect(result.current.currentRoomId).toBe("room-of-user-1");
    // 本文だけは認証解決まで空のまま（スケルトン相当）。
    // Only the message text stays empty until auth resolves (skeleton state).
    expect(result.current.messages).toEqual([]);
  });

  it("keeps everything when the same user is confirmed again", async () => {
    installMatchMediaStub();
    localStorage.clear();

    localStorage.setItem("chatcore.chat.userScope", "user:1");
    localStorage.setItem("chatcore.auth.loggedIn", "1");
    localStorage.setItem("chatcore.auth.cachedAt", String(Date.now()));
    writeStoredActiveChatRoom("room-of-user-1", "normal");
    writeStoredHomePageViewState("chat");
    localStorage.setItem(
      "chatHistory_room-of-user-1",
      JSON.stringify([{ text: "user 1's own message", sender: "user" }]),
    );

    fetchMock.mockImplementation(async (url: unknown) => {
      const requestedUrl = String(url);
      if (requestedUrl.includes("current_user")) {
        return jsonResponse({ logged_in: true, user: { id: 1 } });
      }
      return jsonResponse({});
    });

    renderHook(() => useHomePageController());

    // 同じ利用者の再確認では、スコープも部屋の指し先も破棄されない。
    // Neither the scope marker nor the active-room pointer is wiped when the
    // same user is reconfirmed.
    await waitFor(() => expect(readStoredUserScope()).toBe("user:1"));
    expect(localStorage.getItem("chatcore.chat.activeRoomId")).toBe("room-of-user-1");
  });

  // 「ログイン中」キャッシュだけでは、ログアウトを経由しないユーザー切り替え
  // （別アカウントでの再ログインなど）を検出できない。chatcore.auth.loggedIn は
  // 立っているが、この端末の持ち主を記録した userScope がまだ一度も書かれて
  // いない状態（＝現在の利用者がこのキャッシュの持ち主だと確認された実績が
  // 一度もない）では、認証確認が解決する前にローカル本文を描画してはならない。
  // A "logged in" cache alone cannot detect a user switch that skips logout
  // (re-login as a different account, etc.). chatcore.auth.loggedIn is set,
  // but when this device's owner marker (userScope) has never been recorded
  // (i.e. nothing has ever confirmed that whoever is behind this cache is
  // still the user reading the screen now), local text must not be painted
  // before the auth check resolves.
  it("does not paint locally cached text before auth resolves when no owner scope has been recorded", async () => {
    installMatchMediaStub();
    localStorage.clear();

    // 認証キャッシュだけが残り、userScope は一度も記録されていない状態
    // （レビューで指摘された再現手順: chatcore.auth.loggedIn=1 と
    // chatHistory_<roomId> だけが残っている）。
    // Only the auth cache remains; userScope has never been written (the
    // scenario the review reported: chatcore.auth.loggedIn=1 and
    // chatHistory_<roomId> alone).
    localStorage.setItem("chatcore.auth.loggedIn", "1");
    localStorage.setItem("chatcore.auth.cachedAt", String(Date.now()));
    writeStoredActiveChatRoom("room-of-user-1", "normal");
    writeStoredHomePageViewState("chat");
    localStorage.setItem(
      "chatHistory_room-of-user-1",
      JSON.stringify([{ text: "USER 1 PRIVATE MESSAGE", sender: "user" }]),
    );
    expect(readStoredUserScope()).toBeNull();

    let resolveCurrentUser!: (response: Response) => void;
    const currentUserPromise = new Promise<Response>((resolve) => {
      resolveCurrentUser = resolve;
    });

    fetchMock.mockImplementation(async (url: unknown) => {
      const requestedUrl = String(url);
      if (requestedUrl.includes("current_user")) return currentUserPromise;
      return jsonResponse({});
    });

    const { result } = renderHook(() => useHomePageController());

    // 認証確認 (/api/current_user) が解決する前でも、ユーザー1の本文は
    // 一切描画されない。ここが失敗する場合、fetch の往復時間だけ前の利用者の
    // 本文が画面に出てから消えるフラッシュが実際に起きている。
    // Even before the auth check (/api/current_user) resolves, user 1's text
    // must never be rendered. If this fails, the previous user's text is
    // actually flashing on screen for the duration of the fetch round trip.
    expect(result.current.pageViewState).toBe("chat");
    expect(result.current.messages).toEqual([]);

    await act(async () => {
      resolveCurrentUser(jsonResponse({ logged_in: true, user: { id: 2 } }));
    });
    await waitFor(() => expect(result.current.authResolved).toBe(true));

    expect(result.current.messages).toEqual([]);
  });

  // ログアウト後（chatcore.auth.loggedIn が消えている状態）に、まだ残っている
  // ローカル本文を認証確認より前に描画してはいけない。
  // After a logout (chatcore.auth.loggedIn cleared), any local text still on
  // disk must not be painted before the auth check resolves.
  it("does not paint locally cached text before auth resolves when the auth cache is absent", async () => {
    installMatchMediaStub();
    localStorage.clear();

    // 何らかの理由でローカル本文だけが残っている状態（ログアウト直後の端末を模す）。
    // ログイン中キャッシュは無い。
    // Local text alone is still present for some reason (mimics a device right
    // after logout); no "logged in" cache remains.
    writeStoredActiveChatRoom("room-of-user-1", "normal");
    writeStoredHomePageViewState("chat");
    localStorage.setItem(
      "chatHistory_room-of-user-1",
      JSON.stringify([{ text: "user 1's private message", sender: "user" }]),
    );

    let resolveCurrentUser!: (response: Response) => void;
    const currentUserPromise = new Promise<Response>((resolve) => {
      resolveCurrentUser = resolve;
    });

    fetchMock.mockImplementation(async (url: unknown) => {
      const requestedUrl = String(url);
      if (requestedUrl.includes("current_user")) return currentUserPromise;
      return jsonResponse({});
    });

    const { result } = renderHook(() => useHomePageController());

    // 認証確認が解決する前でも、ユーザー1の本文は一切描画されない。
    // Even before the auth check resolves, user 1's text is never rendered.
    expect(result.current.messages).toEqual([]);

    await act(async () => {
      resolveCurrentUser(jsonResponse({ logged_in: false }));
    });
    await waitFor(() => expect(result.current.authResolved).toBe(true));

    expect(result.current.messages).toEqual([]);
  });
});
