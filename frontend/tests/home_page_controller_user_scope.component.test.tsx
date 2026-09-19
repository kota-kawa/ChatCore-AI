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
  it("wipes a previous user's cached room once a different user is confirmed", async () => {
    installMatchMediaStub();
    localStorage.clear();

    // ブラウザに残っていた利用者1の状態（別アカウントでの再ログインなどを想定し、
    // 認証キャッシュはあえて "ログイン中" のまま残しておく）。
    // State left behind by user 1 (the auth cache is deliberately left "logged
    // in", simulating a re-login as a different account that skipped logout).
    localStorage.setItem("chatcore.chat.userScope", "user:1");
    localStorage.setItem("chatcore.auth.loggedIn", "1");
    localStorage.setItem("chatcore.auth.cachedAt", String(Date.now()));
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

    // 認証確認が解決する前は、ユーザー1のキャッシュがまだそのまま残っている。
    // Before the auth check resolves, user 1's cache is still untouched.
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
