import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useHomePageRoomActions } from "../hooks/chat_page/use_home_page_room_actions";

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
type PageViewState = RoomActionsParams["pageViewState"];

// 再レンダーで別物にならないよう、モックはハーネスの外で1度だけ作る。
// Create the mocks once, outside the harness, so re-renders keep the same references.
const setPageViewState = vi.fn();
const loadChatHistory = vi.fn(async () => undefined);
const loadLocalChatHistory = vi.fn();
const stub = vi.fn();
const currentRoomIdRef = { current: null as string | null };

function useSwitchRoomHarness(pageViewState: PageViewState, hasMessages: boolean) {
  return useHomePageRoomActions({
    chatRooms: [{ id: "a", title: "A", mode: "normal" }],
    cachedChatRooms: [],
    setChatRooms: stub,
    mutateChatRooms: stub,
    setOpenRoomActionsFor: stub,
    currentRoomIdRef,
    selectedRoomIds: new Set<string>(),
    loggedIn: true,
    pageViewState,
    hasMessages,
    taskLaunchInProgressRef: { current: false },
    pendingProjectIdRef: { current: null },
    attachedFiles: [],
    closeOverlaySidebar: stub,
    openOverlaySidebar: stub,
    setPageViewState,
    setPersonalKnowledgeEnabled: stub,
    setSharedPromptsEnabled: stub,
    setShareStatus: stub,
    setShareUrl: stub,
    prepareChatViewTransition: stub,
    setChatMessageListResetKey: stub,
    setCurrentRoomMode: stub,
    persistCurrentRoomId: stub,
    loadLocalChatHistory,
    loadChatHistory,
  } as unknown as RoomActionsParams);
}

describe("表示中のルームへの切替 / switching to the current room", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentRoomIdRef.current = "a";
  });

  it("トップページで会話が未読み込みなら、前回のルームでも履歴を読み込む", () => {
    // 再読み込み後のトップページは前回のルーム ID だけを復元し、会話は読み込まない
    // After a reload the top page restores only the last room id, not its messages
    const { result } = renderHook(() => useSwitchRoomHarness("setup", false));

    act(() => {
      result.current.switchChatRoom("a", "normal");
    });

    expect(setPageViewState).toHaveBeenCalledWith("chat");
    expect(loadLocalChatHistory).toHaveBeenCalledWith("a");
    expect(loadChatHistory).toHaveBeenCalledWith("a", true);
  });

  it("トップページでも会話を読み込み済みなら、読み込み直さずにチャット画面へ戻る", () => {
    const { result } = renderHook(() => useSwitchRoomHarness("setup", true));

    act(() => {
      result.current.switchChatRoom("a", "normal");
    });

    expect(setPageViewState).toHaveBeenCalledWith("chat");
    expect(loadLocalChatHistory).not.toHaveBeenCalled();
    expect(loadChatHistory).not.toHaveBeenCalled();
  });

  it("チャット画面で表示中のルームを選び直しても読み込み直さない", () => {
    const { result } = renderHook(() => useSwitchRoomHarness("chat", true));

    act(() => {
      result.current.switchChatRoom("a", "normal");
    });

    expect(loadLocalChatHistory).not.toHaveBeenCalled();
    expect(loadChatHistory).not.toHaveBeenCalled();
  });
});
