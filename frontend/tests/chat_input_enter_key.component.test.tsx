import { act, renderHook } from "@testing-library/react";
import { useCallback, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { describe, expect, it, vi } from "vitest";

import { useHomePageRoomActions } from "../hooks/chat_page/use_home_page_room_actions";

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

// Enterキーイベントの最小限のスタブ。preventDefault の呼び出しも記録する。
// Minimal Enter key event stub that also records preventDefault calls.
function makeEnterKeyEvent(overrides: { shiftKey?: boolean; isComposing?: boolean } = {}) {
  const preventDefault = vi.fn();
  const event = {
    key: "Enter",
    shiftKey: overrides.shiftKey ?? false,
    preventDefault,
    nativeEvent: { isComposing: overrides.isComposing ?? false },
  } as unknown as ReactKeyboardEvent<HTMLTextAreaElement>;
  return { event, preventDefault };
}

function useChatInputHarness(initialInput: string) {
  const [chatInput, setChatInput] = useState(initialInput);
  const [isGenerating, setIsGenerating] = useState(false);
  const currentRoomIdRef = useRef<string | null>("room-1");

  // 実際の送信フローと同じく、送信が始まった時点で生成中フラグを立てる。
  // Mirror the real flow: the generating flag flips as soon as a send starts.
  const generateResponse = useRef(vi.fn<RoomActionsParams["generateResponse"]>(async () => true)).current;
  const stopGeneration = useRef(vi.fn<RoomActionsParams["stopGeneration"]>(async () => undefined)).current;
  const handleGenerate = useCallback<RoomActionsParams["generateResponse"]>(
    async (message, model, roomId, files, roomMode, options) => {
      setIsGenerating(true);
      return generateResponse(message, model, roomId, files, roomMode, options);
    },
    [generateResponse],
  );

  const params = {
    chatRooms: [],
    setChatRooms: vi.fn(),
    currentRoomIdRef,
    persistCurrentRoomId: vi.fn(),
    pageViewState: "chat",
    setPageViewState: vi.fn(),
    selectedRoomIds: new Set<string>(),
    setSelectedRoomIds: vi.fn(),
    mutateChatRooms: vi.fn(async () => undefined),
    fetchChatRoomsPage: vi.fn(),
    loggedIn: true,
    isGenerating,
    isTaskOrderEditing: false,
    chatInput,
    setupInfo: "",
    selectedModel: "model",
    temporaryModeEnabled: false,
    personalKnowledgeEnabled: false,
    sharedPromptsEnabled: false,
    attachedFiles: [],
    taskLaunchInProgressRef: { current: false },
    pendingProjectIdRef: { current: null },
    generateResponse: handleGenerate,
    stopGeneration,
  } as unknown as RoomActionsParams;

  const actions = useHomePageRoomActions({
    ...params,
    closeOverlaySidebar: vi.fn(),
    closeShareModal: vi.fn(),
    setAttachedFiles: vi.fn(),
    setChatInput,
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

  return { chatInput, isGenerating, generateResponse, stopGeneration, ...actions };
}

describe("チャット入力のEnterキー操作 / Enter key handling in the chat composer", () => {
  it("Enterを二回連打しても回答生成が停止しない", async () => {
    const { result } = renderHook(() => useChatInputHarness("こんにちは"));

    await act(async () => {
      result.current.handleChatInputKeyDown(makeEnterKeyEvent().event);
    });

    expect(result.current.generateResponse).toHaveBeenCalledTimes(1);
    expect(result.current.isGenerating).toBe(true);

    await act(async () => {
      result.current.handleChatInputKeyDown(makeEnterKeyEvent().event);
    });

    expect(result.current.stopGeneration).not.toHaveBeenCalled();
    expect(result.current.generateResponse).toHaveBeenCalledTimes(1);
    expect(result.current.isGenerating).toBe(true);
  });

  it("生成中でなければEnterで送信できる", async () => {
    const { result } = renderHook(() => useChatInputHarness("送信する内容"));
    const { event, preventDefault } = makeEnterKeyEvent();

    await act(async () => {
      result.current.handleChatInputKeyDown(event);
    });

    expect(preventDefault).toHaveBeenCalled();
    expect(result.current.generateResponse).toHaveBeenCalledWith(
      "送信する内容",
      "model",
      "room-1",
      undefined,
      undefined,
      { unsentInputText: "送信する内容" },
    );
  });

  it("Shift+EnterとIME変換中のEnterでは送信しない", async () => {
    const { result } = renderHook(() => useChatInputHarness("変換中の文字"));

    await act(async () => {
      result.current.handleChatInputKeyDown(makeEnterKeyEvent({ shiftKey: true }).event);
      result.current.handleChatInputKeyDown(makeEnterKeyEvent({ isComposing: true }).event);
    });

    expect(result.current.generateResponse).not.toHaveBeenCalled();
    expect(result.current.stopGeneration).not.toHaveBeenCalled();
  });

  it("停止ボタン相当の送信ハンドラは生成中に停止できる", async () => {
    const { result } = renderHook(() => useChatInputHarness("こんにちは"));

    await act(async () => {
      result.current.handleSendMessage();
    });
    expect(result.current.isGenerating).toBe(true);

    await act(async () => {
      result.current.handleSendMessage();
    });

    expect(result.current.stopGeneration).toHaveBeenCalledTimes(1);
  });
});
