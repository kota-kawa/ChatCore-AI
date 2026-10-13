import { act, renderHook, waitFor } from "@testing-library/react";
import { useRef, useState, type Dispatch, type SetStateAction } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useHomePageGenerationActions } from "../hooks/chat_page/use_home_page_generation_actions";
import { LocaleProvider } from "../contexts/locale_context";
import { createGenerationGuard } from "../lib/chat_page/generation_guard";
import { readStoredGenerationState, readStoredHistory, writeStoredGenerationState, writeStoredHistory } from "../lib/chat_page/storage";
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

function createStreamResponse(blocks: string[], generationId?: string) {
  let index = 0;
  return {
    ok: true,
    status: 200,
    headers: {
      get: (name: string) => {
        if (name.toLowerCase() === "content-type") return "text/event-stream";
        if (name.toLowerCase() === "x-chat-generation-id") return generationId ?? null;
        return null;
      },
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

describe("generation identity", () => {
  beforeEach(() => resilientFetchMock.mockReset());

  it("pins initial request recovery to the id sent before losing the POST response", async () => {
    let requestGenerationId = "";
    resilientFetchMock.mockImplementation(async (url, init) => {
      if (String(url) === "/api/chat") {
        requestGenerationId = JSON.parse(String(init?.body)).generation_id;
        expect(requestGenerationId).toMatch(/^[0-9a-f]{32}$/);
        expect(readStoredGenerationState("room-1")?.generationId).toBe(requestGenerationId);
        throw new TypeError("lost POST response");
      }
      if (!String(url).includes("chat_generation_stream")) return createJsonResponse(500, { error: "unrelated request" });
      expect(new URL(String(url), "https://example.test").searchParams.get("generation_id"), String(url)).toBe(requestGenerationId);
      return createStreamResponse([
        'id: 1\nevent: done\ndata: {"response":"今回の回答"}\n\n',
      ], requestGenerationId);
    });
    const { result } = renderHook(() => useGenerationHarness());
    await act(async () => {
      expect(await result.current.actions.generateResponse("今回の質問", "model", "room-1")).toBe(true);
    });
    expect(result.current.state.messages.filter((message) => message.sender === "assistant").map((message) => message.text))
      .toEqual(["今回の回答"]);
  });

  it("creates distinct request ids for successive turns", async () => {
    const ids: string[] = [];
    resilientFetchMock.mockImplementation(async (url, init) => {
      if (String(url) !== "/api/chat") return createJsonResponse(500, { error: "unrelated request" });
      ids.push(JSON.parse(String(init?.body)).generation_id);
      return createJsonResponse(200, { response: `回答${ids.length}` });
    });
    const { result } = renderHook(() => useGenerationHarness());
    await act(async () => { await result.current.actions.generateResponse("質問1", "model", "room-1"); });
    await act(async () => { await result.current.actions.generateResponse("質問2", "model", "room-1"); });
    expect(ids).toHaveLength(2);
    expect(ids.every((id) => /^[0-9a-f]{32}$/.test(id))).toBe(true);
    expect(ids[0]).not.toBe(ids[1]);
  });

  it("does not let an aborted stream flush its draft into a later turn", async () => {
    let rejectOldRead!: (error: Error) => void;
    const oldRead = new Promise<never>((_resolve, reject) => { rejectOldRead = reject; });
    let resolveNewPost!: (response: Response) => void;
    const newPost = new Promise<Response>((resolve) => { resolveNewPost = resolve; });
    let postCount = 0;
    let newGenerationId = "";
    let oldStreamRead = false;
    resilientFetchMock.mockImplementation(async (url, init) => {
      if (String(url) === "/api/chat_stop") return createJsonResponse(200, {});
      if (String(url) !== "/api/chat") return createJsonResponse(500, {});
      postCount += 1;
      const generationId = JSON.parse(String(init?.body)).generation_id;
      if (postCount === 2) {
        newGenerationId = generationId;
        return newPost;
      }
      let reads = 0;
      const getReader = () => ({
        read: async () => {
          reads += 1;
          if (reads > 1) {
            oldStreamRead = true;
            return oldRead;
          }
          return { done: false, value: encoder.encode('id: 1\nevent: chunk\ndata: {"text":"前回の途中回答"}\n\n') };
        },
        cancel: async () => undefined,
      });
      return { ...createStreamResponse([], generationId), body: { getReader } } as unknown as Response;
    });
    const { result } = renderHook(() => useGenerationHarness());
    let firstTurn!: Promise<boolean>;
    act(() => { firstTurn = result.current.actions.generateResponse("質問1", "model", "room-1"); });
    await waitFor(() => expect(oldStreamRead).toBe(true));
    await act(async () => { await result.current.actions.stopGeneration(); });
    let secondTurn!: Promise<boolean>;
    act(() => { secondTurn = result.current.actions.generateResponse("質問2", "model", "room-1"); });
    await act(async () => {
      rejectOldRead(new TypeError("old stream closed"));
      await firstTurn;
    });
    expect(readStoredGenerationState("room-1")).toMatchObject({
      generationId: newGenerationId, lastEventId: 0, streamedText: "",
    });
    await act(async () => {
      resolveNewPost(createJsonResponse(200, { response: "今回の回答" }));
      await secondTurn;
    });
  });

  it("resets a previous turn's draft before reconnecting to the current status id", async () => {
    writeStoredGenerationState({
      roomId: "room-1", roomMode: "normal", generationId: "old-generation",
      lastEventId: 99, streamedText: "前回の下書き", updatedAt: Date.now(),
    });
    resilientFetchMock.mockImplementation(async (url, init) => {
      if (String(url).includes("get_chat_history")) {
        return createJsonResponse(200, { messages: [{ sender: "user", message: "今回の質問" }] });
      }
      if (String(url).includes("chat_generation_status")) {
        return createJsonResponse(200, { is_generating: true, generation_id: "new-generation" });
      }
      if (!String(url).includes("chat_generation_stream")) return createJsonResponse(500, { error: "unrelated request" });
      expect(new URL(String(url), "https://example.test").searchParams.get("generation_id")).toBe("new-generation");
      expect((init?.headers as Record<string, string>)["Last-Event-ID"]).toBeUndefined();
      return createStreamResponse(['id: 1\nevent: done\ndata: {"response":"今回の回答"}\n\n'], "new-generation");
    });
    const { result } = renderHook(() => useGenerationHarness());
    await act(async () => { await result.current.actions.loadChatHistory("room-1"); });
    await waitFor(() => {
      expect(result.current.state.messages.find((message) => message.sender === "assistant")?.text).toBe("今回の回答");
    });
    expect(result.current.state.messages.some((message) => message.text.includes("前回の下書き"))).toBe(false);
  });

  it("does not let a delayed JSON body clear or append to a newer turn", async () => {
    let resolveOldBody!: (payload: unknown) => void;
    const oldBody = new Promise<unknown>((resolve) => { resolveOldBody = resolve; });
    let resolveNewPost!: (response: Response) => void;
    const newPost = new Promise<Response>((resolve) => { resolveNewPost = resolve; });
    let oldBodyRead = false;
    let posts = 0;
    resilientFetchMock.mockImplementation(async (url) => {
      if (String(url) === "/api/chat_stop") return createJsonResponse(200, {});
      if (String(url) !== "/api/chat") return createJsonResponse(500, {});
      posts += 1;
      if (posts === 2) return newPost;
      return { ...createJsonResponse(200, {}), json: async () => { oldBodyRead = true; return oldBody; } } as Response;
    });
    const { result } = renderHook(() => useGenerationHarness());
    let first!: Promise<boolean>;
    act(() => { first = result.current.actions.generateResponse("前回の質問", "model", "room-1"); });
    await waitFor(() => expect(oldBodyRead).toBe(true));
    await act(async () => { await result.current.actions.stopGeneration(); });
    let second!: Promise<boolean>;
    act(() => { second = result.current.actions.generateResponse("今回の質問", "model", "room-1"); });
    const pending = readStoredGenerationState("room-1");
    await act(async () => { resolveOldBody({ response: "前回の回答" }); await first; });
    expect(readStoredGenerationState("room-1")).toEqual(pending);
    expect(readStoredHistory("room-1").some((entry) => entry.text === "前回の回答")).toBe(false);
    await act(async () => { resolveNewPost(createJsonResponse(200, { response: "今回の回答" })); await second; });
  });

  it("does not let delayed history status replace the messages or draft of a newer turn", async () => {
    let resolveStatus!: (response: Response) => void;
    const status = new Promise<Response>((resolve) => { resolveStatus = resolve; });
    let statusRequested = false;
    let resolvePost!: (response: Response) => void;
    const post = new Promise<Response>((resolve) => { resolvePost = resolve; });
    resilientFetchMock.mockImplementation(async (url) => {
      if (String(url).includes("get_chat_history")) return createJsonResponse(200, {
        messages: [{ sender: "assistant", message: "前回の回答" }],
      });
      if (String(url).includes("chat_generation_status")) { statusRequested = true; return status; }
      if (String(url) === "/api/chat") return post;
      return createJsonResponse(500, {});
    });
    const { result } = renderHook(() => useGenerationHarness());
    let history!: Promise<void>;
    act(() => { history = result.current.actions.loadChatHistory("room-1"); });
    await waitFor(() => expect(statusRequested).toBe(true));
    let turn!: Promise<boolean>;
    act(() => { turn = result.current.actions.generateResponse("今回の質問", "model", "room-1"); });
    const pending = readStoredGenerationState("room-1");
    await act(async () => { resolveStatus(createJsonResponse(200, { is_generating: false })); await history; });
    expect(readStoredGenerationState("room-1")).toEqual(pending);
    expect(result.current.state.messages.some((message) => message.text === "今回の質問")).toBe(true);
    await act(async () => { resolvePost(createJsonResponse(200, { response: "今回の回答" })); await turn; });
  });
});

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
  const messageSeqRef = useRef(0);
  const pendingAutoScrollRef = useRef(false);
  const prependScrollRestoreRef = useRef<{ prevScrollHeight: number; prevScrollTop: number } | null>(null);
  const streamLastEventIdByRoomRef = useRef(new Map<string, number>());

  const actions = useHomePageGenerationActions({
    messageList: { messageSeqRef, setMessages },
    generationStream: {
      abortControllerRef,
      generationGuardRef,
      setIsGenerating,
      streamLastEventIdByRoomRef,
    },
    roomSelection: {
      currentRoomIdRef,
      currentRoomMode: "normal",
      setChatRooms,
      setCurrentRoomId,
      setCurrentRoomMode,
    },
    historyPagination: {
      historyHasMore: false,
      historyNextBeforeId: null,
      isLoadingOlder: false,
      setHistoryHasMore,
      setHistoryNextBeforeId,
      setIsLoadingOlder,
    },
    scrollRestore: {
      chatMessagesRef,
      pendingAutoScrollRef: pendingAutoScrollRef,
      prependScrollRestoreRef,
    },
    retrievalSettings: { personalKnowledgeEnabled: false, sharedPromptsEnabled: false },
    setChatInput,
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

  it("shows an English error prefix in an English UI", async () => {
    resilientFetchMock.mockResolvedValue(
      createJsonResponse(502, { error: "The AI provider is busy." }),
    );

    const { result } = renderHook(() => useGenerationHarness(), {
      wrapper: ({ children }) => <LocaleProvider initialLocale="en">{children}</LocaleProvider>,
    });

    await act(async () => {
      await result.current.actions.generateResponse("Help me", "model", "room-1");
    });

    const error = result.current.state.messages.find((message) => message.error);
    expect(error?.text).toBe("Error: The AI provider is busy.");
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

  it("sends the stored browser theme preference for an explicit theme read", async () => {
    window.localStorage.setItem("chatcore-theme", "auto");
    resilientFetchMock.mockResolvedValue(createJsonResponse(502, { error: "失敗" }));

    const { result } = renderHook(() => useGenerationHarness());

    await act(async () => {
      await result.current.actions.generateResponse("今のテーマ設定を教えて", "model", "room-1");
    });

    const request = resilientFetchMock.mock.calls[0]?.[1];
    expect(JSON.parse(String(request?.body))).toMatchObject({ theme_preference: "auto" });
  });

  it("does not send the stored browser theme preference for unrelated messages", async () => {
    window.localStorage.setItem("chatcore-theme", "dark");
    resilientFetchMock.mockResolvedValue(createJsonResponse(502, { error: "失敗" }));

    const { result } = renderHook(() => useGenerationHarness());

    await act(async () => {
      await result.current.actions.generateResponse("このメモを要約して", "model", "room-1");
    });

    const request = resilientFetchMock.mock.calls[0]?.[1];
    expect(JSON.parse(String(request?.body))).not.toHaveProperty("theme_preference");
  });

  it("preserves an explicit theme request when regenerating its answer", async () => {
    window.localStorage.setItem("chatcore-theme", "dark");
    writeStoredHistory("room-1", [
      { text: "今のテーマ設定を教えて", sender: "user" },
      { text: "ダークです。", sender: "bot" },
    ]);
    resilientFetchMock.mockImplementation(async (url) =>
      String(url).includes("chat_regenerate")
        ? createJsonResponse(200, { response: "ダークです。" })
        : createJsonResponse(500, { error: "履歴を更新できません" }),
    );

    const { result } = renderHook(() => useGenerationHarness());

    await act(async () => {
      await result.current.actions.regenerateLastResponse("model", "room-1");
    });

    const request = resilientFetchMock.mock.calls.find((call) => String(call[0]).includes("chat_regenerate"))?.[1];
    expect(JSON.parse(String(request?.body))).toMatchObject({ theme_preference: "dark" });
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

  // 検索画像だけの完了は回答ではない。画像だけの吹き出しを残さず失敗として扱う。
  // A completion carrying only web-search images is not an answer: treat it as a
  // failure instead of leaving an image-only bubble behind.
  it("treats a done event carrying only web-search images as an empty answer", async () => {
    resilientFetchMock.mockResolvedValue(
      createStreamResponse([
        `id: 1\nevent: done\ndata: ${JSON.stringify({
          response: "",
          parts: [
            {
              type: "web_search_image",
              image: {
                url: "https://cdn.example.com/maple.jpg",
                alt: "紅葉の写真",
                source_url: "https://example.com/kyoto",
                source_title: "京都の紅葉ガイド",
              },
            },
          ],
        })}\n\n`,
      ]),
    );

    const { result } = renderHook(() => useGenerationHarness());

    await act(async () => {
      await result.current.actions.generateResponse("京都の紅葉を教えて", "model", "room-1");
    });

    const messages = result.current.state.messages;
    expect(messages).toHaveLength(1);
    expect(messages[0].error).toBe(true);
    expect(messages[0].text).toContain("空");
    expect(readStoredHistory("room-1")).toEqual([]);
  });

  it("keeps a server-persisted partial answer when the stream ends incomplete", async () => {
    resilientFetchMock.mockResolvedValue(
      createStreamResponse([
        `id: 1\nevent: chunk\ndata: ${JSON.stringify({ text: "途中までの回答" })}\n\n`,
        `id: 2\nevent: incomplete\ndata: ${JSON.stringify({
          response: "途中までの回答",
          partial: true,
          retryable: true,
          message: "途中までの回答を保存しました。",
        })}\n\n`,
      ]),
    );

    const { result } = renderHook(() => useGenerationHarness());

    await act(async () => {
      await result.current.actions.generateResponse("長い調査をして", "model", "room-1");
    });

    const assistantMessages = result.current.state.messages.filter(
      (message) => message.sender === "assistant",
    );
    expect(assistantMessages).toHaveLength(2);
    expect(assistantMessages[0].text).toBe("途中までの回答");
    expect(assistantMessages[0].streaming).toBe(false);
    expect(assistantMessages[1].error).toBe(true);
    expect(assistantMessages[1].text).toContain("保存");
    // 途中保存の印が付いていないと「続きを生成」の導線が出せない。
    // Without the partial marker the "continue the answer" affordance cannot appear.
    expect(assistantMessages[0].partial).toBe(true);
  });

  it("does not mark a completed answer as partial", async () => {
    resilientFetchMock.mockResolvedValue(
      createStreamResponse([
        `id: 1\nevent: chunk\ndata: ${JSON.stringify({ text: "完了した回答" })}\n\n`,
        `id: 2\nevent: done\ndata: ${JSON.stringify({ response: "完了した回答" })}\n\n`,
      ]),
    );

    const { result } = renderHook(() => useGenerationHarness());

    await act(async () => {
      await result.current.actions.generateResponse("普通の質問", "model", "room-1");
    });

    const assistantMessages = result.current.state.messages.filter(
      (message) => message.sender === "assistant",
    );
    expect(assistantMessages).toHaveLength(1);
    expect(assistantMessages[0].partial).toBeFalsy();
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

// 「一時チャット」は本文を端末に残さない約束の機能なので、JSON応答・ストリーム応答
// のどちらでも localStorage には一切書き込まれないことを確認する。
// "Temporary chat" promises never to leave its text on the device, so neither a
// JSON nor a streamed answer may ever be written to localStorage.
describe("temporary chat rooms never persist locally", () => {
  beforeEach(() => {
    resilientFetchMock.mockReset();
    window.localStorage.clear();
  });

  it("does not persist a JSON-answered turn", async () => {
    resilientFetchMock.mockResolvedValue(createJsonResponse(200, { response: "一時的な回答" }));

    const { result } = renderHook(() => useGenerationHarness());

    await act(async () => {
      await result.current.actions.generateResponse("一時的な質問", "model", "room-1", undefined, "temporary");
    });

    expect(result.current.state.messages.map((message) => message.sender)).toEqual(["user", "assistant"]);
    expect(readStoredHistory("room-1")).toEqual([]);
    expect(readStoredGenerationState("room-1")).toBeNull();
  });

  it("does not persist a streamed answer", async () => {
    resilientFetchMock.mockResolvedValue(
      createStreamResponse([
        `id: 1\nevent: chunk\ndata: ${JSON.stringify({ text: "一時" })}\n\n`,
        `id: 2\nevent: done\ndata: ${JSON.stringify({ response: "一時的な回答" })}\n\n`,
      ]),
    );

    const { result } = renderHook(() => useGenerationHarness());

    await act(async () => {
      await result.current.actions.generateResponse("一時的な質問", "model", "room-1", undefined, "temporary");
    });

    const assistantMessages = result.current.state.messages.filter((message) => message.sender === "assistant");
    expect(assistantMessages).toHaveLength(1);
    expect(assistantMessages[0].text).toBe("一時的な回答");
    expect(readStoredHistory("room-1")).toEqual([]);
    expect(readStoredGenerationState("room-1")).toBeNull();
  });

  it("still persists a normal room's answer for comparison", async () => {
    resilientFetchMock.mockResolvedValue(createJsonResponse(200, { response: "通常の回答" }));

    const { result } = renderHook(() => useGenerationHarness());

    await act(async () => {
      await result.current.actions.generateResponse("通常の質問", "model", "room-1", undefined, "normal");
    });

    expect(readStoredHistory("room-1")).toEqual([
      { text: "通常の質問", sender: "user" },
      { text: "通常の回答", sender: "bot" },
    ]);
  });
});

// isGenerating は React state なので同じ tick 内の二重クリックでは更新前の値のまま
// ガードを通過する。acquireGeneration() は ref ベースで即時に効くため、取得できた
// ときだけ履歴を切り詰めることで、2回目のクリックがさらに1つ前の回答まで
// 消してしまわないことを確認する。
// isGenerating is React state, so a double click within the same tick still sees
// the stale value and slips past that guard. acquireGeneration() is ref-based and
// takes effect immediately; only truncating once it succeeds must stop a second
// click from deleting one answer too many.
describe("regenerate double click", () => {
  beforeEach(() => {
    resilientFetchMock.mockReset();
    window.localStorage.clear();
  });

  it("truncates only once when regenerate is triggered twice in the same tick", async () => {
    resilientFetchMock.mockResolvedValueOnce(createJsonResponse(200, { response: "answer-1" }));
    const { result } = renderHook(() => useGenerationHarness());
    await act(async () => {
      await result.current.actions.generateResponse("question-1", "model", "room-1");
    });

    resilientFetchMock.mockResolvedValueOnce(createJsonResponse(200, { response: "answer-2" }));
    await act(async () => {
      await result.current.actions.generateResponse("question-2", "model", "room-1");
    });

    expect(readStoredHistory("room-1").map((entry) => entry.text)).toEqual([
      "question-1",
      "answer-1",
      "question-2",
      "answer-2",
    ]);

    // regenerateLastResponse also fires an unawaited refreshActivePath() GET after
    // a JSON answer; let it fail harmlessly so it does not overwrite the local
    // cache this assertion checks (its own catch keeps the optimistic state).
    resilientFetchMock.mockImplementation(async (url) => {
      if (String(url).includes("chat_regenerate")) {
        return createJsonResponse(200, { response: "answer-3" });
      }
      return createJsonResponse(500, { error: "not relevant to this test" });
    });

    let firstRegenerate: Promise<void>;
    let secondRegenerate: Promise<void>;
    act(() => {
      firstRegenerate = result.current.actions.regenerateLastResponse("model", "room-1");
      secondRegenerate = result.current.actions.regenerateLastResponse("model", "room-1");
    });
    await act(async () => {
      await Promise.all([firstRegenerate!, secondRegenerate!]);
    });

    // 2回目のクリックは生成を開始せず（guard busy）、履歴も切り詰めない。
    // question-2 とその回答が失われず、最後の回答だけが置き換わる。
    // The second click starts no generation (guard busy) and truncates
    // nothing: question-2 and its answer survive, only the last answer changes.
    expect(readStoredHistory("room-1").map((entry) => entry.text)).toEqual([
      "question-1",
      "answer-1",
      "question-2",
      "answer-3",
    ]);
    expect(requestedUrls().filter((url) => url.includes("chat_regenerate"))).toHaveLength(1);
  });

  // editAndRegenerateMessage received the identical fix (acquire before
  // truncate); verify it symmetrically so the two code paths do not drift.
  it("truncates only once when edit-and-regenerate is triggered twice in the same tick", async () => {
    resilientFetchMock.mockResolvedValueOnce(createJsonResponse(200, { response: "answer-1" }));
    const { result } = renderHook(() => useGenerationHarness());
    await act(async () => {
      await result.current.actions.generateResponse("question-1", "model", "room-1");
    });

    resilientFetchMock.mockResolvedValueOnce(createJsonResponse(200, { response: "answer-2" }));
    await act(async () => {
      await result.current.actions.generateResponse("question-2", "model", "room-1");
    });

    expect(readStoredHistory("room-1").map((entry) => entry.text)).toEqual([
      "question-1",
      "answer-1",
      "question-2",
      "answer-2",
    ]);

    // editAndRegenerateMessage also fires an unawaited refreshActivePath() GET
    // after a JSON answer; let it fail harmlessly so it does not overwrite the
    // local cache this assertion checks (its own catch keeps the optimistic
    // state).
    resilientFetchMock.mockImplementation(async (url) => {
      if (String(url).includes("chat_edit_and_regenerate")) {
        return createJsonResponse(200, { response: "edited-answer" });
      }
      return createJsonResponse(500, { error: "not relevant to this test" });
    });

    let firstEdit: Promise<void>;
    let secondEdit: Promise<void>;
    act(() => {
      firstEdit = result.current.actions.editAndRegenerateMessage("edited-question", 0, "model", "room-1");
      secondEdit = result.current.actions.editAndRegenerateMessage("edited-question-2", 0, "model", "room-1");
    });
    await act(async () => {
      await Promise.all([firstEdit!, secondEdit!]);
    });

    // 2回目のクリックは生成を開始せず（guard busy）、履歴も切り詰めない。
    // question-1 とその回答は残り、直前のやり取りだけが編集後の内容に置き換わる。
    // The second click starts no generation (guard busy) and truncates
    // nothing: question-1 and its answer survive, only the last exchange is
    // replaced by the edit.
    expect(readStoredHistory("room-1").map((entry) => entry.text)).toEqual([
      "question-1",
      "answer-1",
      "edited-question",
      "edited-answer",
    ]);
    expect(requestedUrls().filter((url) => url.includes("chat_edit_and_regenerate"))).toHaveLength(1);
  });
});
