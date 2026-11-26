import { act, renderHook } from "@testing-library/react";
import type { Dispatch, SetStateAction } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDeferredRoomTitlePolling } from "../hooks/chat_page/use_deferred_room_title_polling";
import type { ChatRoom } from "../lib/chat_page/types";
import { resilientFetch } from "../scripts/core/resilient_fetch";

vi.mock("../scripts/core/resilient_fetch", () => ({ resilientFetch: vi.fn() }));

const resilientFetchMock = vi.mocked(resilientFetch);

function createJsonResponse(status: number, payload: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as unknown as Response;
}

function createRoomState() {
  const state: { rooms: ChatRoom[] } = { rooms: [{ id: "room-1", title: "初期名", mode: "normal" }] };
  const setChatRooms: Dispatch<SetStateAction<ChatRoom[]>> = (update) => {
    state.rooms = typeof update === "function" ? update(state.rooms) : update;
  };
  return { state, setChatRooms };
}

describe("deferred room title polling", () => {
  beforeEach(() => {
    resilientFetchMock.mockReset();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("retries transient failures with increasing delays and applies a changed title", async () => {
    resilientFetchMock
      .mockRejectedValueOnce(new TypeError("network unavailable"))
      .mockResolvedValueOnce(createJsonResponse(200, { title: "自動タイトル" }));
    const { state, setChatRooms } = createRoomState();
    const { result } = renderHook(() => useDeferredRoomTitlePolling(setChatRooms));

    act(() => result.current.startDeferredRoomTitlePolling("room-1", ["初期名"]));
    await act(async () => { await vi.advanceTimersByTimeAsync(250); });
    expect(resilientFetchMock).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(499); });
    expect(resilientFetchMock).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });

    expect(resilientFetchMock).toHaveBeenCalledTimes(2);
    expect(resilientFetchMock.mock.calls[0]?.[2]).toMatchObject({ retries: 0, timeoutMs: 2_000 });
    expect(state.rooms[0]?.title).toBe("自動タイトル");
  });

  it("does not retry a missing room-title endpoint", async () => {
    resilientFetchMock.mockResolvedValue(createJsonResponse(404, {}));
    const { setChatRooms } = createRoomState();
    const { result } = renderHook(() => useDeferredRoomTitlePolling(setChatRooms));

    act(() => result.current.startDeferredRoomTitlePolling("room-1", ["初期名"]));
    await act(async () => { await vi.advanceTimersByTimeAsync(250); });
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });

    expect(resilientFetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps a local rename made while the title request is pending", async () => {
    let resolveRequest!: (response: Response) => void;
    resilientFetchMock.mockImplementation(() => new Promise((resolve) => { resolveRequest = resolve; }));
    const { state, setChatRooms } = createRoomState();
    const { result } = renderHook(() => useDeferredRoomTitlePolling(setChatRooms));

    act(() => result.current.startDeferredRoomTitlePolling("room-1", ["初期名"]));
    await act(async () => { await vi.advanceTimersByTimeAsync(250); });
    state.rooms = [{ ...state.rooms[0]!, title: "手動タイトル" }];
    await act(async () => { resolveRequest(createJsonResponse(200, { title: "自動タイトル" })); });

    expect(state.rooms[0]?.title).toBe("手動タイトル");
  });

  it("aborts a pending title request when the hook unmounts", async () => {
    let requestSignal: AbortSignal | undefined;
    let resolveRequest!: (response: Response) => void;
    resilientFetchMock.mockImplementation((_url, init) => {
      requestSignal = init?.signal as AbortSignal;
      return new Promise((resolve) => { resolveRequest = resolve; });
    });
    const { setChatRooms } = createRoomState();
    const { result, unmount } = renderHook(() => useDeferredRoomTitlePolling(setChatRooms));

    act(() => result.current.startDeferredRoomTitlePolling("room-1", ["初期名"]));
    await act(async () => { await vi.advanceTimersByTimeAsync(250); });
    expect(requestSignal?.aborted).toBe(false);

    unmount();
    expect(requestSignal?.aborted).toBe(true);
    resolveRequest(createJsonResponse(200, { title: "自動タイトル" }));
    await Promise.resolve();
    expect(resilientFetchMock).toHaveBeenCalledTimes(1);
  });
});
