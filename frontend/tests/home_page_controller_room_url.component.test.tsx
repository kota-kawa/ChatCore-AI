// URL の room クエリでルームを開く挙動（優先順、失敗時の通常表示への復帰、ゲスト・不正値の無視）を検証する。
// Tests opening a room from the URL's room query: priority, falling back to the normal view on failure, and ignoring guests and unusable values.

import { act, configure, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useHomePageController } from "../hooks/chat_page/use_home_page_controller";
import { buildHomeRoomUrl } from "../lib/chat_page/room_url";
import {
  readStoredActiveChatRoom,
  writeStoredActiveChatRoom,
  writeStoredGenerationState,
  writeStoredHomePageViewState,
} from "../lib/chat_page/storage";
import { resilientFetch } from "../scripts/core/resilient_fetch";
import { showToast } from "../scripts/core/toast";

// 履歴・保存まわりのコールバックの参照を、テストの指示で作り直せるようにする（復元の effect を再実行させるため）。
// Lets a test recreate a callback's identity on demand, to make the restore effect re-run.
const generationActionsIdentity = vi.hoisted(() => ({ version: 0 }));
vi.mock("../hooks/chat_page/use_home_page_generation_actions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../hooks/chat_page/use_home_page_generation_actions")>();
  const React = await import("react");
  return {
    ...actual,
    useHomePageGenerationActions: (...args: Parameters<typeof actual.useHomePageGenerationActions>) => {
      const result = actual.useHomePageGenerationActions(...args);
      const version = generationActionsIdentity.version;
      const persistCurrentRoomId = React.useCallback(
        (...persistArgs: Parameters<typeof result.persistCurrentRoomId>) => result.persistCurrentRoomId(...persistArgs),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [result.persistCurrentRoomId, version],
      );
      return { ...result, persistCurrentRoomId };
    },
  };
});
vi.mock("../scripts/core/toast", () => ({ showToast: vi.fn() }));
vi.mock("../lib/prompt_assist", () => ({ initPromptAssist: vi.fn(() => ({ destroy: vi.fn() })) }));
vi.mock("../scripts/core/resilient_fetch", () => ({ resilientFetch: vi.fn() }));

const fetchMock = vi.mocked(resilientFetch);
const showToastMock = vi.mocked(showToast);

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name: string) => (name.toLowerCase() === "content-type" ? "application/json" : null) },
    json: async () => payload,
    text: async () => JSON.stringify(payload),
    clone() {
      return jsonResponse(payload, status);
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

// ルーム ID ごとの履歴 API の応答。登録の無いルームは存在しない扱い（404）にする。
// History API responses by room id; a room that is not registered behaves as nonexistent (404).
let historyByRoom: Record<string, { status?: number; messages: Array<{ sender: string; message: string }> }> = {};
// 履歴の応答を遅らせたいルームに、解放用の Promise を登録する。
// Register a gate promise for rooms whose history response should be held back.
let historyGates: Record<string, Promise<void>> = {};
// 認証確認（/api/current_user）の応答。既定はログイン中。
// Response of the auth check (/api/current_user); logged in by default.
let currentUserResponse: () => Promise<Response> = async () => jsonResponse({ logged_in: true, user: { id: 1 } });

function historyRequests() {
  return fetchMock.mock.calls
    .map((call) => String(call[0]))
    .filter((url) => url.includes("get_chat_history"))
    .map((url) => new URL(url, "http://localhost").searchParams.get("room_id"));
}

function currentUrl() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

function seedLoggedIn() {
  localStorage.setItem("chatcore.chat.userScope", "user:1");
  localStorage.setItem("chatcore.auth.loggedIn", "1");
  localStorage.setItem("chatcore.auth.cachedAt", String(Date.now()));
}

describe("useHomePageController opening a room from the URL", () => {
  afterEach(() => {
    configure({ reactStrictMode: false });
  });

  beforeEach(() => {
    installMatchMediaStub();
    localStorage.clear();
    window.history.replaceState(null, "", "/");
    historyByRoom = {};
    historyGates = {};
    currentUserResponse = async () => jsonResponse({ logged_in: true, user: { id: 1 } });
    fetchMock.mockImplementation(async (url: unknown) => {
      const requestedUrl = String(url);
      if (requestedUrl.includes("current_user")) return currentUserResponse();
      if (requestedUrl.includes("get_chat_history")) {
        const roomId = new URL(requestedUrl, "http://localhost").searchParams.get("room_id") ?? "";
        await historyGates[roomId];
        const history = historyByRoom[roomId];
        if (!history) return jsonResponse({ error: "not found" }, 404);
        return jsonResponse({ messages: history.messages, pagination: { has_more: false, next_before_id: null }, room_mode: "normal" });
      }
      return jsonResponse({});
    });
  });

  it("opens the requested room like a sidebar selection, strips only room from the URL and saves it as the last room", async () => {
    seedLoggedIn();
    historyByRoom["1700000000000"] = { messages: [{ sender: "user", message: "元の会話" }] };
    window.history.replaceState(null, "", `${buildHomeRoomUrl("1700000000000")}&keep=1#top`);

    const { result } = renderHook(() => useHomePageController());

    // 最初の描画前に反映される（セットアップ画面を挟まない）。
    // Applied before the first paint (no setup view in between).
    expect(result.current.pageViewState).toBe("chat");
    expect(result.current.currentRoomId).toBe("1700000000000");
    expect(currentUrl()).toBe("/?keep=1#top");

    await waitFor(() => expect(result.current.messages.map((message) => message.text)).toEqual(["元の会話"]));
    expect(readStoredActiveChatRoom()).toEqual({ roomId: "1700000000000", roomMode: "normal" });
    expect(historyRequests()).toEqual(["1700000000000"]);
    expect(showToastMock).not.toHaveBeenCalled();
  });

  it("takes the URL room over the stored last room and does not fetch the stored room", async () => {
    seedLoggedIn();
    writeStoredActiveChatRoom("stored-room", "normal");
    writeStoredHomePageViewState("chat");
    historyByRoom["url-room"] = { messages: [{ sender: "user", message: "URL の会話" }] };
    window.history.replaceState(null, "", buildHomeRoomUrl("url-room"));

    const { result } = renderHook(() => useHomePageController());

    await waitFor(() => expect(result.current.messages.map((message) => message.text)).toEqual(["URL の会話"]));
    expect(result.current.currentRoomId).toBe("url-room");
    expect(readStoredActiveChatRoom()?.roomId).toBe("url-room");
    expect(historyRequests()).toEqual(["url-room"]);
  });

  it("restores the room of a generation in progress instead, and still strips the query", async () => {
    seedLoggedIn();
    writeStoredGenerationState({
      roomId: "generating-room",
      roomMode: "normal",
      generationId: "a".repeat(32),
      lastEventId: 0,
      streamedText: "途中",
      updatedAt: Date.now(),
    });
    historyByRoom["generating-room"] = { messages: [{ sender: "user", message: "生成中の会話" }] };
    historyByRoom["url-room"] = { messages: [{ sender: "user", message: "URL の会話" }] };
    window.history.replaceState(null, "", buildHomeRoomUrl("url-room"));

    const { result } = renderHook(() => useHomePageController());

    expect(result.current.currentRoomId).toBe("generating-room");
    expect(currentUrl()).toBe("/");
    await waitFor(() => expect(historyRequests()).toContain("generating-room"));
    expect(historyRequests()).not.toContain("url-room");
  });

  it("returns to the normal initial view with a notice when the room cannot be loaded and nothing was stored", async () => {
    seedLoggedIn();
    window.history.replaceState(null, "", buildHomeRoomUrl("someone-elses-room"));

    const { result } = renderHook(() => useHomePageController());
    expect(result.current.pageViewState).toBe("chat");

    await waitFor(() => expect(result.current.pageViewState).toBe("setup"));
    expect(result.current.currentRoomId).toBeNull();
    expect(readStoredActiveChatRoom()).toBeNull();
    expect(showToastMock).toHaveBeenCalledTimes(1);
    expect(showToastMock.mock.calls[0]?.[1]).toMatchObject({ variant: "error" });
    expect(historyRequests()).toEqual(["someone-elses-room"]);
  });

  it("falls back to the stored last room, untouched, when the requested room cannot be loaded", async () => {
    seedLoggedIn();
    writeStoredActiveChatRoom("stored-room", "normal");
    writeStoredHomePageViewState("chat");
    historyByRoom["stored-room"] = { messages: [{ sender: "user", message: "前回の会話" }] };
    window.history.replaceState(null, "", buildHomeRoomUrl("missing-room"));

    const { result } = renderHook(() => useHomePageController());

    await waitFor(() => expect(result.current.messages.map((message) => message.text)).toEqual(["前回の会話"]));
    expect(result.current.pageViewState).toBe("chat");
    expect(result.current.currentRoomId).toBe("stored-room");
    expect(readStoredActiveChatRoom()?.roomId).toBe("stored-room");
    expect(localStorage.getItem("chatcore.home.viewState")).toBe("chat");
    expect(showToastMock).toHaveBeenCalledTimes(1);
  });

  it("keeps the setup view and the stored last room when the requested room fails and the last view was setup", async () => {
    seedLoggedIn();
    writeStoredActiveChatRoom("stored-room", "normal");
    writeStoredHomePageViewState("setup");
    window.history.replaceState(null, "", buildHomeRoomUrl("missing-room"));

    const { result } = renderHook(() => useHomePageController());
    await waitFor(() => expect(showToastMock).toHaveBeenCalledTimes(1));

    await waitFor(() => expect(result.current.pageViewState).toBe("setup"));
    expect(localStorage.getItem("chatcore.home.viewState")).toBe("setup");
    expect(readStoredActiveChatRoom()?.roomId).toBe("stored-room");
    expect(historyRequests()).toEqual(["missing-room"]);
  });

  it("keeps the room the user moved to when the URL room fails afterwards, with no notice", async () => {
    seedLoggedIn();
    let failUrlRoom!: () => void;
    historyGates["slow-missing-room"] = new Promise<void>((resolve) => {
      failUrlRoom = resolve;
    });
    historyByRoom["picked-room"] = { messages: [{ sender: "user", message: "選んだ会話" }] };
    window.history.replaceState(null, "", buildHomeRoomUrl("slow-missing-room"));

    const { result } = renderHook(() => useHomePageController());
    expect(result.current.currentRoomId).toBe("slow-missing-room");

    // URL のルームの読み込み中に、サイドバーから別のルームを選ぶ。
    // Pick another room from the sidebar while the URL's room is still loading.
    act(() => {
      result.current.switchChatRoom("picked-room", "normal", { forceReload: true });
    });
    await waitFor(() => expect(result.current.messages.map((message) => message.text)).toEqual(["選んだ会話"]));

    await act(async () => {
      failUrlRoom();
    });

    expect(result.current.currentRoomId).toBe("picked-room");
    expect(result.current.pageViewState).toBe("chat");
    expect(result.current.messages.map((message) => message.text)).toEqual(["選んだ会話"]);
    expect(readStoredActiveChatRoom()?.roomId).toBe("picked-room");
    expect(showToastMock).not.toHaveBeenCalled();
  });

  it("opens the room once under Strict Mode and keeps one history request", async () => {
    configure({ reactStrictMode: true });
    seedLoggedIn();
    historyByRoom["url-room"] = { messages: [{ sender: "user", message: "URL の会話" }] };
    window.history.replaceState(null, "", buildHomeRoomUrl("url-room"));

    const { result } = renderHook(() => useHomePageController());

    await waitFor(() => expect(result.current.messages.map((message) => message.text)).toEqual(["URL の会話"]));
    expect(historyRequests()).toEqual(["url-room"]);
    expect(readStoredActiveChatRoom()?.roomId).toBe("url-room");
    expect(showToastMock).not.toHaveBeenCalled();
  });

  it("notifies once and returns to the original setup view under Strict Mode when the room cannot be loaded", async () => {
    configure({ reactStrictMode: true });
    seedLoggedIn();
    writeStoredActiveChatRoom("stored-room", "normal");
    writeStoredHomePageViewState("setup");
    window.history.replaceState(null, "", buildHomeRoomUrl("missing-room"));

    const { result } = renderHook(() => useHomePageController());
    await waitFor(() => expect(showToastMock).toHaveBeenCalledTimes(1));
    await act(async () => {});

    expect(showToastMock).toHaveBeenCalledTimes(1);
    expect(historyRequests()).toEqual(["missing-room"]);
    expect(result.current.pageViewState).toBe("setup");
    expect(localStorage.getItem("chatcore.home.viewState")).toBe("setup");
    expect(readStoredActiveChatRoom()?.roomId).toBe("stored-room");
  });

  // 認証キャッシュが無い端末では、認証確認が終わるのを待ってから開く。
  // On a device with no auth cache, wait for the auth check before opening.
  it("waits for the auth check when there is no auth cache, then opens the room for a logged-in user", async () => {
    historyByRoom["url-room"] = { messages: [{ sender: "user", message: "URL の会話" }] };
    window.history.replaceState(null, "", `${buildHomeRoomUrl("url-room")}&keep=1`);
    let resolveCurrentUser!: (response: Response) => void;
    const currentUserPromise = new Promise<Response>((resolve) => {
      resolveCurrentUser = resolve;
    });
    currentUserResponse = () => currentUserPromise;

    const { result } = renderHook(() => useHomePageController());

    // 認証が確定するまでは開かず、前回ルームとしても保存しない。URL からは取り除く。
    // Nothing opens or is saved as the last room before auth settles; the query is already stripped.
    expect(result.current.pageViewState).toBe("setup");
    expect(historyRequests()).toEqual([]);
    expect(currentUrl()).toBe("/?keep=1");

    await act(async () => {
      resolveCurrentUser(jsonResponse({ logged_in: true, user: { id: 1 } }));
    });

    await waitFor(() => expect(result.current.messages.map((message) => message.text)).toEqual(["URL の会話"]));
    expect(result.current.currentRoomId).toBe("url-room");
    expect(historyRequests()).toEqual(["url-room"]);
    expect(readStoredActiveChatRoom()).toEqual({ roomId: "url-room", roomMode: "normal" });
  });

  // 認証待ちの間に利用者が別のルームへ移ったら、認証確定後に URL のルームで上書きしない。
  // effect の再実行（temporary への切り替えでコールバックが変わる）を挟んでも、基準は待機に入った時点のルームのまま。
  // If the user moves to another room while waiting for auth, the URL's room must not override it once auth settles,
  // even when the effect re-runs in between (switching to a temporary room changes the callbacks).
  it("does not open the URL room after auth settles when the user moved to another room while waiting", async () => {
    historyByRoom["url-room"] = { messages: [{ sender: "user", message: "URL の会話" }] };
    historyByRoom["picked-room"] = { messages: [{ sender: "user", message: "選んだ会話" }] };
    window.history.replaceState(null, "", buildHomeRoomUrl("url-room"));
    let resolveCurrentUser!: (response: Response) => void;
    const currentUserPromise = new Promise<Response>((resolve) => {
      resolveCurrentUser = resolve;
    });
    currentUserResponse = () => currentUserPromise;

    const { result, rerender } = renderHook(() => useHomePageController());
    expect(historyRequests()).toEqual([]);

    act(() => {
      result.current.switchChatRoom("picked-room", "normal", { forceReload: true });
    });
    await waitFor(() => expect(result.current.messages.map((message) => message.text)).toEqual(["選んだ会話"]));

    // コールバックの参照を変えて再描画し、復元の effect を認証待ちのまま再実行させる。
    // Change a callback's identity and re-render so the restore effect re-runs while still waiting for auth.
    generationActionsIdentity.version += 1;
    rerender();

    await act(async () => {
      resolveCurrentUser(jsonResponse({ logged_in: true, user: { id: 1 } }));
    });
    await waitFor(() => expect(result.current.authResolved).toBe(true));
    await act(async () => {});

    expect(result.current.currentRoomId).toBe("picked-room");
    expect(result.current.messages.map((message) => message.text)).toEqual(["選んだ会話"]);
    expect(historyRequests()).not.toContain("url-room");
  });

  it("drops the room when the auth check shows a guest and there was no auth cache", async () => {
    historyByRoom["url-room"] = { messages: [] };
    window.history.replaceState(null, "", buildHomeRoomUrl("url-room"));
    currentUserResponse = async () => jsonResponse({ logged_in: false });

    const { result } = renderHook(() => useHomePageController());
    await waitFor(() => expect(result.current.authResolved).toBe(true));
    await act(async () => {});

    expect(result.current.pageViewState).toBe("setup");
    expect(result.current.currentRoomId).toBeNull();
    expect(historyRequests()).toEqual([]);
    expect(readStoredActiveChatRoom()).toBeNull();
    expect(showToastMock).not.toHaveBeenCalled();
    expect(currentUrl()).toBe("/");
  });

  it("ignores the room query for a guest and only strips it", async () => {
    localStorage.setItem("chatcore.auth.loggedIn", "0");
    localStorage.setItem("chatcore.auth.cachedAt", String(Date.now()));
    historyByRoom["url-room"] = { messages: [] };
    window.history.replaceState(null, "", `${buildHomeRoomUrl("url-room")}&keep=1`);

    const { result } = renderHook(() => useHomePageController());
    await act(async () => {});

    expect(currentUrl()).toBe("/?keep=1");
    expect(result.current.pageViewState).toBe("setup");
    expect(result.current.currentRoomId).toBeNull();
    expect(historyRequests()).toEqual([]);
    expect(showToastMock).not.toHaveBeenCalledWith(expect.stringContaining("開けません"), expect.anything());
  });

  it("ignores unusable values, keeping the stored restore as it was", async () => {
    seedLoggedIn();
    writeStoredActiveChatRoom("stored-room", "normal");
    writeStoredHomePageViewState("chat");
    historyByRoom["stored-room"] = { messages: [{ sender: "user", message: "前回の会話" }] };
    window.history.replaceState(null, "", `/?room=${"a".repeat(129)}`);

    const { result } = renderHook(() => useHomePageController());

    await waitFor(() => expect(result.current.messages.map((message) => message.text)).toEqual(["前回の会話"]));
    expect(result.current.currentRoomId).toBe("stored-room");
    expect(currentUrl()).toBe("/");
    expect(historyRequests()).toEqual(["stored-room"]);
    expect(showToastMock).not.toHaveBeenCalled();
  });

  it("keeps the existing restore when there is no room query", async () => {
    seedLoggedIn();
    writeStoredActiveChatRoom("stored-room", "normal");
    writeStoredHomePageViewState("chat");
    historyByRoom["stored-room"] = { messages: [{ sender: "user", message: "前回の会話" }] };

    const { result } = renderHook(() => useHomePageController());

    expect(result.current.currentRoomId).toBe("stored-room");
    await waitFor(() => expect(result.current.messages.map((message) => message.text)).toEqual(["前回の会話"]));
    expect(historyRequests()).toEqual(["stored-room"]);
    expect(showToastMock).not.toHaveBeenCalled();
  });
});
