import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useHomePageRoomActions } from "../hooks/chat_page/use_home_page_room_actions";
import type { ChatRoom } from "../lib/chat_page/types";

vi.mock("../scripts/core/alert_modal", () => ({
  showConfirmModal: vi.fn(),
  showPromptModal: vi.fn(),
}));
vi.mock("../scripts/core/toast", () => ({
  showToast: vi.fn(),
}));
vi.mock("../scripts/core/resilient_fetch", () => ({
  resilientFetch: vi.fn(),
}));
vi.mock("../scripts/core/runtime_validation", () => ({
  extractApiErrorMessage: vi.fn(() => "サーバーエラー"),
  readJsonBodySafe: vi.fn(),
}));
vi.mock("../scripts/setup/setup_viewport", () => ({
  scheduleSetupViewportFit: vi.fn(),
}));

type RoomActionsParams = Parameters<typeof useHomePageRoomActions>[0];

// 再レンダーで別物にならないよう、モックはハーネスの外で1度だけ作る。
// Create the mocks once, outside the harness, so re-renders keep the same references.
const closeOverlaySidebar = vi.fn();
const openOverlaySidebar = vi.fn();
const setPageViewState = vi.fn();
const mutateChatRooms = vi.fn(async () => undefined);
const stub = vi.fn();
const asyncStub = vi.fn(async () => undefined);

const rooms: ChatRoom[] = [
  { id: "a", title: "A", mode: "normal", lastActivityAt: "2026-09-20T10:00:00" },
  { id: "b", title: "B", mode: "normal", lastActivityAt: "2026-09-10T10:00:00" },
];

function useAccessChatHarness(chatRooms: ChatRoom[]) {
  return useHomePageRoomActions({
    chatRooms,
    cachedChatRooms: [],
    setChatRooms: stub,
    mutateChatRooms,
    setOpenRoomActionsFor: stub,
    currentRoomIdRef: { current: null },
    selectedRoomIds: new Set<string>(),
    loggedIn: true,
    pageViewState: "setup",
    taskLaunchInProgressRef: { current: false },
    pendingProjectIdRef: { current: null },
    attachedFiles: [],
    closeOverlaySidebar,
    openOverlaySidebar,
    setPageViewState,
    setPersonalKnowledgeEnabled: stub,
    setSharedPromptsEnabled: stub,
    setShareStatus: stub,
    setShareUrl: stub,
    prepareChatViewTransition: stub,
    resetChatRoomsPaginationWindow: stub,
    setChatRoomsHasMore: stub,
    setChatRoomsNextCursor: stub,
    setChatMessageListResetKey: stub,
    setCurrentRoomMode: stub,
    setHistoryHasMore: stub,
    setHistoryNextBeforeId: stub,
    setIsLoadingOlder: stub,
    setMessages: stub,
    persistCurrentRoomId: stub,
    loadLocalChatHistory: stub,
    loadChatHistory: asyncStub,
  } as unknown as RoomActionsParams);
}

describe("ホームからのチャット履歴入口 / entering chat history from home", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("読み込み済みの直近ルームを開いたあと、オーバーレイ幅ではサイドバーを開く", async () => {
    const { result } = renderHook(() => useAccessChatHarness(rooms));

    await act(async () => {
      await result.current.handleAccessChat();
    });

    expect(setPageViewState).toHaveBeenCalledWith("chat");
    expect(openOverlaySidebar).toHaveBeenCalledTimes(1);
    // ルーム切替が閉じた直後に開き直すので、最後の操作が「開く」になっていること
    // The room switch closes it first; the final call must be the one that opens it
    const lastClose = Math.max(...closeOverlaySidebar.mock.invocationCallOrder);
    expect(openOverlaySidebar.mock.invocationCallOrder[0]).toBeGreaterThan(lastClose);
  });

  it("ルームが 1 件も無くても、一覧（サイドバー）を開いた状態でチャット画面へ移る", async () => {
    // ログイン中の再取得は mutateChatRooms 経由で、未解決（undefined）ならキャッシュ（空）に落ちる
    // While logged in the refetch goes through mutateChatRooms; undefined falls back to the (empty) cache
    const { result } = renderHook(() => useAccessChatHarness([]));

    await act(async () => {
      await result.current.handleAccessChat();
    });

    expect(setPageViewState).toHaveBeenCalledWith("chat");
    expect(openOverlaySidebar).toHaveBeenCalled();
    expect(closeOverlaySidebar).not.toHaveBeenCalled();
  });
});
