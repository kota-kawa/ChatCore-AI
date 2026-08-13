import { act, renderHook } from "@testing-library/react";
import { useRef, useState, type Dispatch, type SetStateAction } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useHomePageGenerationActions } from "../hooks/chat_page/use_home_page_generation_actions";
import { createGenerationGuard } from "../lib/chat_page/generation_guard";
import { readStoredHistory } from "../lib/chat_page/storage";
import type { ChatRoom, UiChatMessage } from "../lib/chat_page/types";
import { resilientFetch } from "../scripts/core/resilient_fetch";

vi.mock("../scripts/core/toast", () => ({
  showToast: vi.fn(),
}));
vi.mock("../scripts/core/resilient_fetch", () => ({
  resilientFetch: vi.fn(),
}));

const resilientFetchMock = vi.mocked(resilientFetch);
const encoder = new TextEncoder();

// エラー本文を返す JSON レスポンス。SSE ではないので JSON 分岐が使われる。
// A JSON error response; not an SSE stream, so the JSON branch handles it.
function createJsonResponse(status: number, payload: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get: (name: string) => (name.toLowerCase() === "content-type" ? "application/json" : null),
    },
    json: async () => payload,
  } as unknown as Response;
}

function createStreamResponse(blocks: string[]) {
  let index = 0;
  return {
    ok: true,
    status: 200,
    headers: {
      get: (name: string) => (name.toLowerCase() === "content-type" ? "text/event-stream" : null),
    },
    body: {
      getReader: () => ({
        read: async () => {
          if (index >= blocks.length) return { value: undefined, done: true };
          const value = encoder.encode(blocks[index]);
          index += 1;
          return { value, done: false };
        },
        cancel: async () => undefined,
      }),
    },
  } as unknown as Response;
}

function requestedUrls() {
  return resilientFetchMock.mock.calls.map((call) => String(call[0]));
}

type HarnessState = {
  messages: UiChatMessage[];
  chatInput: string;
};

function useGenerationHarness() {
  const [, setRenderTick] = useState(0);
  const messagesRef = useRef<UiChatMessage[]>([]);
  const chatInputRef = useRef("");

  const setMessages: Dispatch<SetStateAction<UiChatMessage[]>> = (action) => {
    messagesRef.current =
      typeof action === "function"
        ? (action as (previous: UiChatMessage[]) => UiChatMessage[])(messagesRef.current)
        : action;
    setRenderTick((tick) => tick + 1);
  };
  const setChatInput: Dispatch<SetStateAction<string>> = (action) => {
    chatInputRef.current =
      typeof action === "function"
        ? (action as (previous: string) => string)(chatInputRef.current)
        : action;
    setRenderTick((tick) => tick + 1);
  };

  const [, setChatRooms] = useState<ChatRoom[]>([]);
  const [, setCurrentRoomId] = useState<string | null>("room-1");
  const [, setCurrentRoomMode] = useState<"normal" | "temporary">("normal");
  const [, setHistoryHasMore] = useState(false);
  const [, setHistoryNextBeforeId] = useState<number | null>(null);
  const [, setIsGenerating] = useState(false);
  const [, setIsLoadingOlder] = useState(false);

  const abortControllerRef = useRef<AbortController | null>(null);
  const chatMessagesRef = useRef<HTMLDivElement | null>(null);
  const currentRoomIdRef = useRef<string | null>("room-1");
  const generationGuardRef = useRef(createGenerationGuard());
  const localStorageWarningShownRef = useRef(false);
  const messageSeqRef = useRef(0);
  const pendingAutoScrollRef = useRef(false);
  const prependScrollRestoreRef = useRef<{ prevScrollHeight: number; prevScrollTop: number } | null>(null);
  const streamLastEventIdByRoomRef = useRef(new Map<string, number>());

  const actions = useHomePageGenerationActions({
    abortControllerRef,
    chatMessagesRef,
    currentRoomIdRef,
    currentRoomMode: "normal",
    generationGuardRef,
    historyHasMore: false,
    historyNextBeforeId: null,
    isLoadingOlder: false,
    personalKnowledgeEnabled: false,
    sharedPromptsEnabled: false,
    localStorageWarningShownRef,
    messageSeqRef,
    pendingAutoScrollRef,
    prependScrollRestoreRef,
    streamLastEventIdByRoomRef,
    setChatInput,
    setChatRooms,
    setCurrentRoomId,
    setCurrentRoomMode,
    setHistoryHasMore,
    setHistoryNextBeforeId,
    setIsGenerating,
    setIsLoadingOlder,
    setMessages,
  });

  const state: HarnessState = {
    get messages() {
      return messagesRef.current;
    },
    get chatInput() {
      return chatInputRef.current;
    },
  } as HarnessState;

  return { actions, state };
}

describe("failed chat turns", () => {
  beforeEach(() => {
    resilientFetchMock.mockReset();
    window.localStorage.clear();
  });

  it("does not stack the user's own messages when a turn produces no answer", async () => {
    resilientFetchMock.mockResolvedValue(
      createJsonResponse(502, { error: "AI応答の生成に失敗しました。", code: "api_error" }),
    );

    const { result } = renderHook(() => useGenerationHarness());

    await act(async () => {
      await result.current.actions.generateResponse("一回目", "model", "room-1", undefined, "normal", {
        unsentInputText: "一回目",
      });
    });
    await act(async () => {
      await result.current.actions.generateResponse("二回目", "model", "room-1", undefined, "normal", {
        unsentInputText: "二回目",
      });
    });

    // 失敗したユーザー発話は取り消され、エラー表示だけが残る。
    // The failed user message is rolled back, leaving only the error notices.
    const senders = result.current.state.messages.map((message) => message.sender);
    expect(senders).toEqual(["assistant", "assistant"]);
    expect(result.current.state.messages.every((message) => message.error)).toBe(true);
    expect(readStoredHistory("room-1")).toEqual([]);
  });

  it("puts the unsent text back into an empty composer", async () => {
    resilientFetchMock.mockResolvedValue(createJsonResponse(502, { error: "失敗" }));

    const { result } = renderHook(() => useGenerationHarness());

    await act(async () => {
      await result.current.actions.generateResponse("送れなかった本文", "model", "room-1", undefined, "normal", {
        unsentInputText: "送れなかった本文",
      });
    });

    expect(result.current.state.chatInput).toBe("送れなかった本文");
  });

  it("treats an empty streamed answer as a failure instead of rendering a blank bubble", async () => {
    resilientFetchMock.mockResolvedValue(
      createStreamResponse([`id: 1\nevent: done\ndata: ${JSON.stringify({ response: "" })}\n\n`]),
    );

    const { result } = renderHook(() => useGenerationHarness());

    await act(async () => {
      await result.current.actions.generateResponse("こんにちは", "model", "room-1");
    });

    const messages = result.current.state.messages;
    expect(messages).toHaveLength(1);
    expect(messages[0].error).toBe(true);
    expect(messages[0].text).toContain("空");
    expect(readStoredHistory("room-1")).toEqual([]);
  });

  it("recreates a chat room that no longer exists and sends the message again", async () => {
    resilientFetchMock
      .mockResolvedValueOnce(
        createJsonResponse(404, { error: "該当ルームが見つかりません", code: "chat.room_not_found" }),
      )
      .mockResolvedValueOnce(createJsonResponse(201, { id: "room-1" }))
      .mockResolvedValueOnce(createJsonResponse(200, { response: "こんにちは" }));

    const { result } = renderHook(() => useGenerationHarness());

    let completed = false;
    await act(async () => {
      completed = await result.current.actions.generateResponse("続きをお願い", "model", "room-1");
    });

    expect(completed).toBe(true);
    expect(requestedUrls()).toEqual(["/api/chat", "/api/new_chat_room", "/api/chat"]);
    const senders = result.current.state.messages.map((message) => message.sender);
    expect(senders).toEqual(["user", "assistant"]);
  });

  it("reports the failure once when the room cannot be recreated", async () => {
    resilientFetchMock
      .mockResolvedValueOnce(
        createJsonResponse(404, { error: "該当ルームが見つかりません", code: "chat.room_not_found" }),
      )
      .mockResolvedValueOnce(createJsonResponse(500, { error: "作成に失敗しました" }));

    const { result } = renderHook(() => useGenerationHarness());

    await act(async () => {
      await result.current.actions.generateResponse("続きをお願い", "model", "room-1");
    });

    const messages = result.current.state.messages;
    expect(messages).toHaveLength(1);
    expect(messages[0].error).toBe(true);
    expect(messages[0].text).toContain("該当ルームが見つかりません");
  });
});
