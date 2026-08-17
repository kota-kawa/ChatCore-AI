import { act, renderHook } from "@testing-library/react";
import { useCallback, useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { useHomePageRoomActions } from "../hooks/chat_page/use_home_page_room_actions";
import type { ChatRoom, ChatRoomMode } from "../lib/chat_page/types";

vi.mock("../scripts/core/alert_modal", () => ({
  showConfirmModal: vi.fn(),
}));
vi.mock("../scripts/core/toast", () => ({
  showToast: vi.fn(),
}));
vi.mock("../scripts/core/resilient_fetch", () => ({
  resilientFetch: vi.fn(),
}));
vi.mock("../scripts/core/runtime_validation", () => ({
  extractApiErrorMessage: vi.fn(() => "エラー"),
  readJsonBodySafe: vi.fn(async () => ({})),
}));
vi.mock("../scripts/setup/setup_viewport", () => ({
  scheduleSetupViewportFit: vi.fn(),
}));

type RoomActionsParams = Parameters<typeof useHomePageRoomActions>[0];
type PageViewState = RoomActionsParams["pageViewState"];

const makeRoom = (id: string): ChatRoom => ({
  id,
  title: `ルーム${id}`,
  createdAt: "2026-01-01T00:00:00Z",
  mode: "normal",
});

// 実運用の状態管理（use_home_page_ui_state / use_home_page_controller）を、テストに
// 必要な範囲だけ再現する最小ハーネス。
// A minimal harness reproducing just enough of the real state wiring
// (use_home_page_ui_state / use_home_page_controller) for these tests.
function useRoomScopedTogglesHarness(initialRooms: ChatRoom[]) {
  const [chatRooms, setChatRooms] = useState(initialRooms);
  const [pageViewState, setPageViewState] = useState<PageViewState>("setup");
  const [setupInfo, setSetupInfo] = useState("");
  const [personalKnowledgeEnabled, setPersonalKnowledgeEnabled] = useState(false);
  const [sharedPromptsEnabled, setSharedPromptsEnabled] = useState(false);
  const currentRoomIdRef = useRef<string | null>(null);
  const [currentRoomId, setCurrentRoomId] = useState<string | null>(null);

  const persistCurrentRoomId = useCallback((roomId: string | null) => {
    currentRoomIdRef.current = roomId;
    setCurrentRoomId(roomId);
  }, []);

  const createNewChatRoom = useCallback(
    async (roomId: string, title: string, mode: ChatRoomMode) => {
      setChatRooms((previous) => [{ id: roomId, title, createdAt: "2026-01-01T00:00:00Z", mode }, ...previous]);
    },
    [],
  );

  const params = {
    chatRooms,
    setChatRooms,
    currentRoomIdRef,
    persistCurrentRoomId,
    pageViewState,
    setPageViewState,
    selectedRoomIds: new Set<string>(),
    setSelectedRoomIds: vi.fn(),
    mutateChatRooms: vi.fn(async () => undefined),
    fetchChatRoomsPage: vi.fn(),
    loggedIn: true,
    isGenerating: false,
    isTaskOrderEditing: false,
    chatInput: "",
    setupInfo,
    selectedModel: "model",
    temporaryModeEnabled: false,
    personalKnowledgeEnabled,
    sharedPromptsEnabled,
    attachedFiles: [],
    taskLaunchInProgressRef: { current: false },
    pendingProjectIdRef: { current: null },
    createNewChatRoom,
    generateResponse: vi.fn(async () => true),
    loadChatHistory: vi.fn(async () => undefined),
    loadLocalChatHistory: vi.fn(),
    removeStoredHistory: vi.fn(),
    clearPendingProject: vi.fn(),
  } as unknown as RoomActionsParams;

  const actions = useHomePageRoomActions({
    ...params,
    closeOverlaySidebar: vi.fn(),
    closeShareModal: vi.fn(),
    prepareChatViewTransition: vi.fn(),
    setAttachedFiles: vi.fn(),
    setChatInput: vi.fn(),
    setChatRoomsHasMore: vi.fn(),
    setChatRoomsNextCursor: vi.fn(),
    setCurrentRoomMode: vi.fn(),
    setHistoryHasMore: vi.fn(),
    setHistoryNextBeforeId: vi.fn(),
    setIsBulkDeletingRooms: vi.fn(),
    setIsLoadingOlder: vi.fn(),
    setIsRoomSelectionMode: vi.fn(),
    setChatMessageListResetKey: vi.fn(),
    setLaunchingTaskId: vi.fn(),
    setLaunchingTaskName: vi.fn(),
    setMessages: vi.fn(),
    setOpenRoomActionsFor: vi.fn(),
    setSetupInfo,
    setShareStatus: vi.fn(),
    setShareUrl: vi.fn(),
    setTemporaryModeEnabled: vi.fn(),
    setPersonalKnowledgeEnabled,
    setSharedPromptsEnabled,
  });

  return {
    chatRooms,
    currentRoomId,
    pageViewState,
    setupInfo,
    setSetupInfo,
    personalKnowledgeEnabled,
    sharedPromptsEnabled,
    setPersonalKnowledgeEnabled,
    setSharedPromptsEnabled,
    ...actions,
  };
}

describe("メモ／共有プロンプト参照設定のルームスコープ化 / Room-scoped memo & shared-prompt toggles", () => {
  // 日本語: 新規チャットをONで作成した後、別の既存ルームへ移動するとOFFに戻ります。
  // English: After creating a new chat with the toggle on, switching to a different existing room turns it off.
  it("別ルームへ切り替えると参照設定はOFFに戻る", async () => {
    const { result, rerender } = renderHook(
      ({ rooms }: { rooms: ChatRoom[] }) => useRoomScopedTogglesHarness(rooms),
      { initialProps: { rooms: [makeRoom("existing")] } },
    );

    act(() => {
      result.current.setSetupInfo("沖縄旅行の予算は？");
      result.current.setPersonalKnowledgeEnabled(true);
    });
    rerender({ rooms: result.current.chatRooms });

    await act(async () => {
      await result.current.handleSetupSendMessage();
    });
    rerender({ rooms: result.current.chatRooms });

    expect(result.current.personalKnowledgeEnabled).toBe(true);
    const newRoomId = result.current.currentRoomId;
    expect(newRoomId).not.toBeNull();

    act(() => {
      result.current.switchChatRoom("existing", "normal");
    });
    rerender({ rooms: result.current.chatRooms });

    expect(result.current.currentRoomId).toBe("existing");
    expect(result.current.personalKnowledgeEnabled).toBe(false);
    expect(result.current.sharedPromptsEnabled).toBe(false);
  });

  // 日本語: ONで作ったルームへ戻ると、作成時の設定が復元されます。
  // English: Returning to a room created with the toggle on restores that setting.
  it("元のルームへ戻ると参照設定が復元される", async () => {
    const { result, rerender } = renderHook(
      ({ rooms }: { rooms: ChatRoom[] }) => useRoomScopedTogglesHarness(rooms),
      { initialProps: { rooms: [makeRoom("existing")] } },
    );

    act(() => {
      result.current.setSetupInfo("議事録のテンプレを教えて");
      result.current.setSharedPromptsEnabled(true);
    });
    rerender({ rooms: result.current.chatRooms });

    await act(async () => {
      await result.current.handleSetupSendMessage();
    });
    rerender({ rooms: result.current.chatRooms });
    const newRoomId = result.current.currentRoomId as string;

    act(() => {
      result.current.switchChatRoom("existing", "normal");
    });
    rerender({ rooms: result.current.chatRooms });
    expect(result.current.sharedPromptsEnabled).toBe(false);

    act(() => {
      result.current.switchChatRoom(newRoomId, "normal");
    });
    rerender({ rooms: result.current.chatRooms });

    expect(result.current.currentRoomId).toBe(newRoomId);
    expect(result.current.sharedPromptsEnabled).toBe(true);
    expect(result.current.personalKnowledgeEnabled).toBe(false);
  });

  // 日本語: 「新規チャット」ボタンでセットアップ画面に戻ると、前のルームの設定を引き継ぎません。
  // English: The "New chat" button returns to setup without carrying over the previous room's setting.
  it("新規チャットへ戻ると参照設定はOFFに戻る", async () => {
    const { result, rerender } = renderHook(
      ({ rooms }: { rooms: ChatRoom[] }) => useRoomScopedTogglesHarness(rooms),
      { initialProps: { rooms: [] as ChatRoom[] } },
    );

    act(() => {
      result.current.setSetupInfo("沖縄旅行の予算は？");
      result.current.setPersonalKnowledgeEnabled(true);
    });
    rerender({ rooms: result.current.chatRooms });

    await act(async () => {
      await result.current.handleSetupSendMessage();
    });
    rerender({ rooms: result.current.chatRooms });
    expect(result.current.personalKnowledgeEnabled).toBe(true);

    act(() => {
      result.current.handleNewChat();
    });
    rerender({ rooms: result.current.chatRooms });

    expect(result.current.currentRoomId).toBeNull();
    expect(result.current.personalKnowledgeEnabled).toBe(false);
    expect(result.current.sharedPromptsEnabled).toBe(false);
  });
});
