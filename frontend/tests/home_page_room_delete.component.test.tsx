import { act, renderHook } from "@testing-library/react";
import { useCallback, useRef, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useHomePageRoomActions } from "../hooks/chat_page/use_home_page_room_actions";
import type { ChatRoom } from "../lib/chat_page/types";
import { showConfirmModal } from "../scripts/core/alert_modal";
import { resilientFetch } from "../scripts/core/resilient_fetch";

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
  extractApiErrorMessage: vi.fn(() => "削除失敗"),
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

function useRoomDeleteHarness(initialRooms: ChatRoom[], openRoomId: string | null) {
  const [chatRooms, setChatRooms] = useState(initialRooms);
  const [pageViewState, setPageViewState] = useState<PageViewState>("chat");
  const [selectedRoomIds, setSelectedRoomIds] = useState<Set<string>>(new Set());
  const currentRoomIdRef = useRef<string | null>(openRoomId);
  const [currentRoomId, setCurrentRoomId] = useState<string | null>(openRoomId);

  const persistCurrentRoomId = useCallback((roomId: string | null) => {
    currentRoomIdRef.current = roomId;
    setCurrentRoomId(roomId);
  }, []);

  const params = {
    chatRooms,
    setChatRooms,
    currentRoomIdRef,
    persistCurrentRoomId,
    pageViewState,
    setPageViewState,
    selectedRoomIds,
    setSelectedRoomIds,
    mutateChatRooms: vi.fn(async () => undefined),
    fetchChatRoomsPage: vi.fn(),
    loggedIn: true,
    isGenerating: false,
    isTaskOrderEditing: false,
    chatInput: "",
    setupInfo: "",
    selectedModel: "model",
    temporaryModeEnabled: false,
    personalKnowledgeEnabled: false,
    sharedPromptsEnabled: false,
    attachedFiles: [],
    taskLaunchInProgressRef: { current: false },
    pendingProjectIdRef: { current: null },
  } as unknown as RoomActionsParams;

  const actions = useHomePageRoomActions({
    ...params,
    // 素通しの stub では検証できない項目だけ、ハーネス側の実装で差し替える。
    // Only the fields the assertions inspect get a real implementation here.
    closeOverlaySidebar: vi.fn(),
    closeShareModal: vi.fn(),
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
    setSetupInfo: vi.fn(),
    setShareStatus: vi.fn(),
    setShareUrl: vi.fn(),
    setTemporaryModeEnabled: vi.fn(),
    setPersonalKnowledgeEnabled: vi.fn(),
    setSharedPromptsEnabled: vi.fn(),
  });

  return {
    chatRooms,
    currentRoomId,
    pageViewState,
    selectRooms: setSelectedRoomIds,
    ...actions,
  };
}

describe("チャットルーム削除後の画面遷移 / view state after deleting a chat room", () => {
  beforeEach(() => {
    vi.mocked(showConfirmModal).mockResolvedValue(true);
    vi.mocked(resilientFetch).mockResolvedValue({ ok: true, status: 200 } as Response);
  });

  it("開いているルームを削除したらトップページへ戻る", async () => {
    const { result } = renderHook(() => useRoomDeleteHarness([makeRoom("a"), makeRoom("b")], "a"));

    await act(async () => {
      await result.current.handleDeleteRoom("a", "ルームa");
    });

    expect(result.current.pageViewState).toBe("setup");
    expect(result.current.currentRoomId).toBeNull();
    expect(result.current.chatRooms.map((room) => room.id)).toEqual(["b"]);
  });

  it("開いていないルームを削除したときはチャット画面に留まる", async () => {
    const { result } = renderHook(() => useRoomDeleteHarness([makeRoom("a"), makeRoom("b")], "a"));

    await act(async () => {
      await result.current.handleDeleteRoom("b", "ルームb");
    });

    expect(result.current.pageViewState).toBe("chat");
    expect(result.current.currentRoomId).toBe("a");
    expect(result.current.chatRooms.map((room) => room.id)).toEqual(["a"]);
  });

  it("一括削除に開いているルームが含まれる場合もトップページへ戻る", async () => {
    const { result } = renderHook(() => useRoomDeleteHarness([makeRoom("a"), makeRoom("b")], "a"));

    act(() => {
      result.current.selectRooms(new Set(["a", "b"]));
    });

    await act(async () => {
      await result.current.handleBulkDeleteRooms();
    });

    expect(result.current.pageViewState).toBe("setup");
    expect(result.current.currentRoomId).toBeNull();
    expect(result.current.chatRooms).toEqual([]);
  });

  it("削除に失敗したときはチャット画面のまま復元する", async () => {
    vi.mocked(resilientFetch).mockResolvedValue({ ok: false, status: 500 } as Response);
    const { result } = renderHook(() => useRoomDeleteHarness([makeRoom("a"), makeRoom("b")], "a"));

    await act(async () => {
      await result.current.handleDeleteRoom("a", "ルームa");
    });

    expect(result.current.pageViewState).toBe("chat");
    expect(result.current.currentRoomId).toBe("a");
    expect(result.current.chatRooms.map((room) => room.id)).toEqual(["a", "b"]);
  });
});
