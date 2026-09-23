import { act, renderHook } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useHomePageRoomActions } from "../hooks/chat_page/use_home_page_room_actions";
import type { ChatRoom, ChatRoomsPage } from "../lib/chat_page/types";
import { resilientFetch } from "../scripts/core/resilient_fetch";
import { readJsonBodySafe } from "../scripts/core/runtime_validation";
import { showToast } from "../scripts/core/toast";

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
const mutateChatRooms = vi.fn(async () => undefined);
const setOpenRoomActionsFor = vi.fn();
const stub = vi.fn();

const rooms: ChatRoom[] = [
  { id: "a", title: "A", mode: "normal", lastActivityAt: "2026-09-20T10:00:00" },
  { id: "b", title: "B", mode: "normal", lastActivityAt: "2026-09-10T10:00:00" },
];

function useRoomPinHarness(initialRooms: ChatRoom[]) {
  const [chatRooms, setChatRooms] = useState(initialRooms);
  const actions = useHomePageRoomActions({
    chatRooms,
    setChatRooms,
    mutateChatRooms,
    setOpenRoomActionsFor,
    currentRoomIdRef: { current: null },
    selectedRoomIds: new Set<string>(),
    loggedIn: true,
    pageViewState: "chat",
    taskLaunchInProgressRef: { current: false },
    pendingProjectIdRef: { current: null },
    attachedFiles: [],
    closeOverlaySidebar: stub,
    setShareStatus: stub,
  } as unknown as RoomActionsParams);
  return { chatRooms, ...actions };
}

function lastCacheUpdate(): ChatRoomsPage {
  const updater = mutateChatRooms.mock.calls
    .map((call) => (call as unknown[])[0])
    .find((arg) => typeof arg === "function") as (page: ChatRoomsPage) => ChatRoomsPage;
  return updater({ rooms, pagination: { hasMore: false, nextCursor: null } });
}

describe("チャットのピン留め / pinning a chat room", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("サーバーが記録した日時でピン留めし、キャッシュも更新する", async () => {
    vi.mocked(resilientFetch).mockResolvedValue({ ok: true, status: 200 } as Response);
    vi.mocked(readJsonBodySafe).mockResolvedValue({ room_id: "b", pinned_at: "2026-09-23T12:00:00" });
    const { result } = renderHook(() => useRoomPinHarness(rooms));

    await act(async () => {
      await result.current.handleToggleRoomPin("b", true);
    });

    expect(vi.mocked(resilientFetch)).toHaveBeenCalledWith(
      "/api/pin_chat_room",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ room_id: "b", pinned: true }) }),
    );
    expect(result.current.chatRooms.find((room) => room.id === "b")?.pinnedAt).toBe("2026-09-23T12:00:00");
    expect(lastCacheUpdate().rooms.find((room) => room.id === "b")?.pinnedAt).toBe("2026-09-23T12:00:00");
    expect(setOpenRoomActionsFor).toHaveBeenCalledWith(null);
    expect(showToast).not.toHaveBeenCalled();
  });

  it("ピン留めを外すと最終アクティビティの位置へ戻る", async () => {
    vi.mocked(resilientFetch).mockResolvedValue({ ok: true, status: 200 } as Response);
    vi.mocked(readJsonBodySafe).mockResolvedValue({ room_id: "c", pinned_at: null });
    const pinnedRoom: ChatRoom = {
      id: "c",
      title: "C",
      mode: "normal",
      lastActivityAt: "2026-09-15T10:00:00",
      pinnedAt: "2026-09-22T09:00:00",
    };
    const { result } = renderHook(() => useRoomPinHarness([pinnedRoom, ...rooms]));

    await act(async () => {
      await result.current.handleToggleRoomPin("c", false);
    });

    expect(result.current.chatRooms.map((room) => room.id)).toEqual(["a", "c", "b"]);
    expect(result.current.chatRooms.find((room) => room.id === "c")?.pinnedAt).toBeUndefined();
  });

  it("失敗したら一覧を変えずにエラーを通知する", async () => {
    vi.mocked(resilientFetch).mockResolvedValue({ ok: false, status: 500 } as Response);
    vi.mocked(readJsonBodySafe).mockResolvedValue({ error: "サーバーエラー" });
    const { result } = renderHook(() => useRoomPinHarness(rooms));

    await act(async () => {
      await result.current.handleToggleRoomPin("a", true);
    });

    expect(result.current.chatRooms).toEqual(rooms);
    expect(mutateChatRooms).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining("サーバーエラー"), { variant: "error" });
  });
});
