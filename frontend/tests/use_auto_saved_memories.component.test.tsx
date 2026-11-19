// 自動保存された記憶の通知の取得タイミング（開いたとき・回答の確定後の2回だけ）、無効時と未ログイン・一時チャットでの停止、取り消しを検証する。
// Tests when auto-saved memory notices are fetched (on open and twice after an answer settles), that they stop when
// disabled / signed out / temporary, and the undo flow.

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AUTO_SAVED_MEMORY_REFETCH_DELAYS_MS, useAutoSavedMemories } from "../hooks/chat_page/use_auto_saved_memories";

const { fetchAutoSavedMemoriesMock, updateContextFactMock, showToastMock } = vi.hoisted(() => ({
  fetchAutoSavedMemoriesMock: vi.fn(),
  updateContextFactMock: vi.fn(),
  showToastMock: vi.fn(),
}));

vi.mock("../lib/chat_page/auto_saved_memory_api", () => ({ fetchAutoSavedMemories: fetchAutoSavedMemoriesMock }));
vi.mock("../lib/memo/context_api", () => ({ updateContextFact: updateContextFactMock }));
vi.mock("../scripts/core/toast", () => ({ showToast: showToastMock }));
vi.mock("../contexts/locale_context", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

const saved = { id: 31, messageId: 55, title: "Rust", revision: 2 };

type Options = Parameters<typeof useAutoSavedMemories>[0];

function setup(initial: Partial<Options> = {}) {
  return renderHook((props: Options) => useAutoSavedMemories(props), {
    initialProps: {
      roomId: "room-1",
      roomMode: "normal",
      loggedIn: true,
      isGenerating: false,
      lastAssistantServerId: 55,
      ...initial,
    } as Options,
  });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  fetchAutoSavedMemoriesMock.mockResolvedValue({ enabled: true, memories: [saved] });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useAutoSavedMemories", () => {
  it("loads once when a signed-in normal room opens and exposes notices by message id", async () => {
    const { result } = setup();
    await flush();
    expect(fetchAutoSavedMemoriesMock).toHaveBeenCalledTimes(1);
    expect(fetchAutoSavedMemoriesMock).toHaveBeenCalledWith("room-1");
    expect(result.current.memoriesByMessageId.get(55)?.[0]).toMatchObject({ id: 31, title: "Rust", status: "saved" });
    // 常時ポーリングはしない。 / No continuous polling.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fetchAutoSavedMemoriesMock).toHaveBeenCalledTimes(1);
  });

  it("never fetches for guests, temporary chats or a missing room", async () => {
    setup({ loggedIn: false });
    setup({ roomMode: "temporary" });
    setup({ roomId: null });
    await flush();
    expect(fetchAutoSavedMemoriesMock).not.toHaveBeenCalled();
  });

  it("re-fetches exactly twice after an answer settles, then stops", async () => {
    const { rerender } = setup();
    await flush();
    fetchAutoSavedMemoriesMock.mockClear();

    rerender({ roomId: "room-1", roomMode: "normal", loggedIn: true, isGenerating: true, lastAssistantServerId: 55 });
    rerender({ roomId: "room-1", roomMode: "normal", loggedIn: true, isGenerating: false, lastAssistantServerId: 60 });
    expect(fetchAutoSavedMemoriesMock).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTO_SAVED_MEMORY_REFETCH_DELAYS_MS[0]);
    });
    expect(fetchAutoSavedMemoriesMock).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(AUTO_SAVED_MEMORY_REFETCH_DELAYS_MS[1] - AUTO_SAVED_MEMORY_REFETCH_DELAYS_MS[0]);
    });
    expect(fetchAutoSavedMemoriesMock).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    expect(fetchAutoSavedMemoriesMock).toHaveBeenCalledTimes(2);
  });

  it("stops re-fetching for the session once the server reports auto-extraction as disabled", async () => {
    fetchAutoSavedMemoriesMock.mockResolvedValue({ enabled: false, memories: [] });
    const { rerender } = setup();
    await flush();
    fetchAutoSavedMemoriesMock.mockClear();

    rerender({ roomId: "room-1", roomMode: "normal", loggedIn: true, isGenerating: true, lastAssistantServerId: 55 });
    rerender({ roomId: "room-1", roomMode: "normal", loggedIn: true, isGenerating: false, lastAssistantServerId: 60 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fetchAutoSavedMemoriesMock).not.toHaveBeenCalled();
  });

  it("does not re-fetch when no generation settled (a loaded history keeps one fetch)", async () => {
    const { rerender } = setup({ lastAssistantServerId: null });
    await flush();
    fetchAutoSavedMemoriesMock.mockClear();
    rerender({ roomId: "room-1", roomMode: "normal", loggedIn: true, isGenerating: false, lastAssistantServerId: 55 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fetchAutoSavedMemoriesMock).not.toHaveBeenCalled();
  });

  it("drops a result that arrives after the room changed, and swallows fetch failures", async () => {
    let resolveFirst: (value: unknown) => void = () => undefined;
    fetchAutoSavedMemoriesMock.mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }));
    fetchAutoSavedMemoriesMock.mockResolvedValueOnce({ enabled: true, memories: [] });
    const { result, rerender } = setup();
    rerender({ roomId: "room-2", roomMode: "normal", loggedIn: true, isGenerating: false, lastAssistantServerId: null });
    await act(async () => {
      resolveFirst({ enabled: true, memories: [saved] });
      await Promise.resolve();
    });
    expect(result.current.memoriesByMessageId.get(55)).toBeUndefined();

    fetchAutoSavedMemoriesMock.mockRejectedValueOnce(new TypeError("offline"));
    rerender({ roomId: "room-3", roomMode: "normal", loggedIn: true, isGenerating: false, lastAssistantServerId: null });
    await flush();
    expect(result.current.memoriesByMessageId.size).toBe(0);
    expect(showToastMock).not.toHaveBeenCalled();
  });

  it("undoes through the memory update API and keeps the notice as undone", async () => {
    updateContextFactMock.mockResolvedValue({});
    const { result } = setup();
    await flush();
    await act(async () => {
      await result.current.undo(saved);
    });
    expect(updateContextFactMock).toHaveBeenCalledWith(31, { revision: 2, status: "deprecated" });
    expect(result.current.memoriesByMessageId.get(55)?.[0]?.status).toBe("undone");
  });

  it("shows an error and refreshes the revision when the undo fails", async () => {
    updateContextFactMock.mockRejectedValue(new Error("conflict"));
    const { result } = setup();
    await flush();
    fetchAutoSavedMemoriesMock.mockClear();
    await act(async () => {
      await result.current.undo(saved);
    });
    expect(showToastMock).toHaveBeenCalledWith("chat.memoryNotice.undoFailed", { variant: "error" });
    expect(fetchAutoSavedMemoriesMock).toHaveBeenCalledTimes(1);
    expect(result.current.memoriesByMessageId.get(55)?.[0]?.status).toBe("saved");
  });
});
