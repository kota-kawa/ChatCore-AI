import { act, renderHook } from "@testing-library/react";
import { useRef, useState, type Dispatch, type SetStateAction } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useHomePageGenerationActions } from "../hooks/chat_page/use_home_page_generation_actions";
import { createGenerationGuard } from "../lib/chat_page/generation_guard";
import type { ChatRoom, UiChatMessage } from "../lib/chat_page/types";
import { resilientFetch } from "../scripts/core/resilient_fetch";

vi.mock("../scripts/core/toast", () => ({
  showToast: vi.fn(),
}));
vi.mock("../scripts/core/resilient_fetch", () => ({
  resilientFetch: vi.fn(),
}));

const resilientFetchMock = vi.mocked(resilientFetch);

// 自動スクロールの予約を、いつ・何回行われたかまで記録できる ref。
// A ref that records when — and how often — an auto-scroll was requested.
type ScrollRecorder = {
  ref: { current: boolean };
  requests: string[];
};

function createScrollRecorder(readPhase: () => string): ScrollRecorder {
  const requests: string[] = [];
  let pending = false;
  return {
    ref: {
      get current() {
        return pending;
      },
      set current(next: boolean) {
        pending = next;
        if (next) requests.push(readPhase());
      },
    },
    requests,
  };
}

const encoder = new TextEncoder();

// SSE ブロックを1つずつ返す最小のストリーム応答。最初のチャンクを読んだ時点で
// フェーズを "streaming" へ切り替え、以降のスクロール予約を区別できるようにする。
// A minimal streaming response that yields one SSE block per read. Reading the
// first block flips the phase to "streaming" so later scroll requests stand out.
function createStreamResponse(blocks: string[], onFirstRead: () => void) {
  let index = 0;
  return {
    ok: true,
    headers: {
      get: (name: string) => (name.toLowerCase() === "content-type" ? "text/event-stream" : null),
    },
    body: {
      getReader: () => ({
        read: async () => {
          if (index === 0) onFirstRead();
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

function createInterruptedStreamResponse(block: string) {
  let hasSentBlock = false;
  return {
    ok: true,
    headers: {
      get: (name: string) => (name.toLowerCase() === "content-type" ? "text/event-stream" : null),
    },
    body: {
      getReader: () => ({
        read: async () => {
          if (!hasSentBlock) {
            hasSentBlock = true;
            return { value: encoder.encode(block), done: false };
          }
          throw new TypeError("network changed");
        },
        cancel: async () => undefined,
      }),
    },
  } as unknown as Response;
}

function chunkBlock(id: number, text: string) {
  return `id: ${id}\nevent: chunk\ndata: ${JSON.stringify({ text })}\n\n`;
}

function doneBlock(id: number, response: string) {
  return `id: ${id}\nevent: done\ndata: ${JSON.stringify({ response })}\n\n`;
}

function useGenerationHarness(scrollRef: { current: boolean }, messagesRef: { current: UiChatMessage[] }) {
  // React は updater を次のレンダーまで遅らせるため、act の中で走らせると実際の
  // アプリとは違う順序で適用されてしまう。ここでは即時に適用し、生成中の各段階で
  // メッセージがどう変わるかを本番と同じ順序で観測できるようにする。
  // React defers updaters until the next render, which inside act applies them in
  // an order the real app never sees. Applying them eagerly keeps the sequence
  // of message states identical to production.
  const [, setRenderTick] = useState(0);
  const setMessages: Dispatch<SetStateAction<UiChatMessage[]>> = (action) => {
    messagesRef.current =
      typeof action === "function"
        ? (action as (previous: UiChatMessage[]) => UiChatMessage[])(messagesRef.current)
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
    localStorageWarningShownRef,
    messageSeqRef,
    pendingAutoScrollRef: scrollRef,
    prependScrollRestoreRef,
    streamLastEventIdByRoomRef,
    setChatRooms,
    setCurrentRoomId,
    setCurrentRoomMode,
    setHistoryHasMore,
    setHistoryNextBeforeId,
    setIsGenerating,
    setIsLoadingOlder,
    setMessages,
  });

  return actions;
}

describe("auto-scroll during generation", () => {
  beforeEach(() => {
    resilientFetchMock.mockReset();
    window.localStorage.clear();
  });

  it("never scrolls while the reply is being generated", async () => {
    let phase = "sending";
    const recorder = createScrollRecorder(() => phase);
    const blocks = [
      chunkBlock(1, "こんにちは。"),
      chunkBlock(2, "生成中は画面が動かないことを確かめます。"),
      chunkBlock(3, "最後まで追従スクロールは起きません。"),
      doneBlock(4, "こんにちは。生成中は画面が動かないことを確かめます。最後まで追従スクロールは起きません。"),
    ];
    resilientFetchMock.mockImplementation(async () =>
      createStreamResponse(blocks, () => {
        phase = "streaming";
      }),
    );

    const messagesRef = { current: [] as UiChatMessage[] };
    const { result } = renderHook(() => useGenerationHarness(recorder.ref, messagesRef));

    await act(async () => {
      await result.current.generateResponse("やあ", "model", "room-1");
    });

    // 生成が実際に流れたことを確認したうえで判定する（空振りの防止）。
    // Confirm the reply really streamed, so the assertion below is not vacuous.
    expect(phase).toBe("streaming");
    const finalMessage = messagesRef.current.at(-1);
    expect(finalMessage?.sender).toBe("assistant");
    expect(finalMessage?.text).toContain("追従スクロールは起きません");

    // 送信時の1回だけ。生成が始まってからは一度も予約されない。
    // Exactly one request, made on send; nothing is scheduled once text flows.
    expect(recorder.requests).toEqual(["sending"]);
  });

  it("still scrolls to the bottom when the user sends a message", async () => {
    const recorder = createScrollRecorder(() => "sending");
    resilientFetchMock.mockImplementation(async () => createStreamResponse([
      doneBlock(1, "送信を受け付けました。"),
    ], () => undefined));

    const messagesRef = { current: [] as UiChatMessage[] };
    const { result } = renderHook(() => useGenerationHarness(recorder.ref, messagesRef));

    await act(async () => {
      await result.current.generateResponse("やあ", "model", "room-1");
    });

    expect(messagesRef.current.some((message) => message.sender === "user")).toBe(true);
    expect(recorder.requests).toContain("sending");
  });

  it("reconnects to an interrupted SSE stream without losing received text", async () => {
    const recorder = createScrollRecorder(() => "streaming");
    resilientFetchMock
      .mockResolvedValueOnce(createInterruptedStreamResponse(chunkBlock(1, "切断前の応答。")))
      .mockResolvedValueOnce(createStreamResponse([
        doneBlock(2, "切断前の応答。回線復帰後も続けて受信できます。"),
      ], () => undefined));

    const messagesRef = { current: [] as UiChatMessage[] };
    const { result } = renderHook(() => useGenerationHarness(recorder.ref, messagesRef));

    await act(async () => {
      await result.current.generateResponse("やあ", "model", "room-1");
    });

    expect(resilientFetchMock).toHaveBeenCalledTimes(2);
    expect(messagesRef.current.some((message) => message.error)).toBe(false);
    expect(messagesRef.current.at(-1)?.text).toBe("切断前の応答。回線復帰後も続けて受信できます。");
  });
});
