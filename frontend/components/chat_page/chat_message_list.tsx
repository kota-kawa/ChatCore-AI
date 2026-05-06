import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  type CSSProperties,
  type MutableRefObject,
} from "react";
import { List, useDynamicRowHeight, type ListImperativeAPI } from "react-window";

import { InlineLoading } from "../ui/inline_loading";
import type { UiChatMessage } from "../../lib/chat_page/types";
import { BotMessageHtml } from "./bot_message_html";
import { CopyActionButton } from "./copy_action_button";
import { MemoSaveActionButton } from "./memo_save_action_button";
import { ThinkingConstellation } from "./thinking_constellation";
import { UserMessageHtml } from "./user_message_html";

const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

type ChatMessageListRow =
  | { kind: "load-more" }
  | { kind: "message"; message: UiChatMessage };

type ChatMessageRowProps = {
  rows: ChatMessageListRow[];
  isLoadingOlder: boolean;
  loadOlderChatHistory: () => Promise<void>;
};

type ChatMessageRowComponentProps = ChatMessageRowProps & {
  ariaAttributes: {
    "aria-posinset": number;
    "aria-setsize": number;
    role: "listitem";
  };
  index: number;
  style: CSSProperties;
};

function ChatMessageRow({
  ariaAttributes,
  index,
  isLoadingOlder,
  loadOlderChatHistory,
  rows,
  style,
}: ChatMessageRowComponentProps) {
  const row = rows[index];
  const rowClassName = [
    "chat-message-row",
    index === 0 ? "chat-message-row--first" : "",
    index === rows.length - 1 ? "chat-message-row--last" : "",
    row?.kind === "load-more" ? "chat-message-row--history" : "",
  ]
    .filter(Boolean)
    .join(" ");

  if (!row) {
    return <div {...ariaAttributes} className={rowClassName} style={style}></div>;
  }

  if (row.kind === "load-more") {
    return (
      <div {...ariaAttributes} className={rowClassName} style={style}>
        <button
          type="button"
          className="chat-history-load-more-btn"
          disabled={isLoadingOlder}
          onClick={() => {
            void loadOlderChatHistory();
          }}
        >
          {isLoadingOlder ? <InlineLoading label="読み込み中" /> : "過去のメッセージを読み込む"}
        </button>
      </div>
    );
  }

  const { message } = row;
  if (message.sender === "thinking") {
    const statusText = message.text.trim() || "AIが応答を準備しています";
    return (
      <div {...ariaAttributes} className={rowClassName} style={style}>
        <div className="message-wrapper bot-message-wrapper thinking-message-wrapper">
          <div className="thinking-message" role="status" aria-live="polite" aria-label={statusText}>
            <ThinkingConstellation />
            <span className="thinking-message__status">{statusText}</span>
          </div>
        </div>
      </div>
    );
  }

  if (message.sender === "user") {
    const isLaunchPreview = message.id === "launch-preview-user";
    return (
      <div {...ariaAttributes} className={rowClassName} style={style}>
        <div className="message-wrapper user-message-wrapper">
          <div className="user-message">
            <UserMessageHtml text={message.text} />
          </div>
          {isLaunchPreview ? (
            <div className="message-actions" style={{ visibility: "hidden" }}>
              <div className="copy-btn"><i className="bi bi-clipboard"></i></div>
            </div>
          ) : (
            <div className="message-actions">
              <CopyActionButton
                getText={() => {
                  return message.text;
                }}
              />
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div {...ariaAttributes} className={rowClassName} style={style}>
      <div
        className={`message-wrapper bot-message-wrapper ${message.streaming ? "message-wrapper--streaming" : ""}`.trim()}
      >
        <div className={`bot-message ${message.streaming ? "bot-message--streaming" : ""}`.trim()}>
          <BotMessageHtml text={message.text} />
        </div>
        {!message.streaming && (
          <div className="message-actions">
            <CopyActionButton
              getText={() => {
                return message.text;
              }}
            />
            {!message.error && (
              <MemoSaveActionButton
                getText={() => {
                  return message.text;
                }}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

type ChatMessageListProps = {
  chatMessagesRef: MutableRefObject<HTMLDivElement | null>;
  currentRoomId: string | null;
  setupInfo?: string;
  historyHasMore: boolean;
  historyNextBeforeId: number | null;
  isChatLaunching: boolean;
  isGenerating: boolean;
  isLoadingOlder: boolean;
  launchingTaskName: string | null;
  loadOlderChatHistory: () => Promise<void>;
  messages: UiChatMessage[];
};

function ChatMessageListComponent({
  chatMessagesRef,
  currentRoomId,
  setupInfo,
  historyHasMore,
  historyNextBeforeId,
  isChatLaunching,
  isGenerating,
  isLoadingOlder,
  launchingTaskName,
  loadOlderChatHistory,
  messages,
}: ChatMessageListProps) {
  const rowHeight = useDynamicRowHeight({
    defaultRowHeight: 104,
    key: currentRoomId || "no-room",
  });
  const listApiRef = useRef<ListImperativeAPI | null>(null);

  const setListRef = useCallback(
    (api: ListImperativeAPI | null) => {
      listApiRef.current = api;
      chatMessagesRef.current = api?.element ?? null;
    },
    [chatMessagesRef],
  );

  const rows = useMemo<ChatMessageListRow[]>(() => {
    const nextRows: ChatMessageListRow[] = [];
    if (historyHasMore && historyNextBeforeId !== null) {
      nextRows.push({ kind: "load-more" });
    }

    const visibleMessages =
      isChatLaunching && messages.length === 0
        ? [
            {
              id: "launch-preview-user",
              sender: "user" as const,
              text: launchingTaskName
                ? [
                    `【タスク】${launchingTaskName}`,
                    setupInfo?.trim() ? `【状況・作業環境】${setupInfo.trim()}` : "",
                  ]
                    .filter(Boolean)
                    .join("\n")
                : setupInfo?.trim() || "チャットを準備しています...",
            },
            {
              id: "launch-preview-thinking",
              sender: "thinking" as const,
              text: "AIが応答を準備しています",
            },
          ]
        : messages;

    visibleMessages.forEach((message) => {
      nextRows.push({ kind: "message", message });
    });
    return nextRows;
  }, [historyHasMore, historyNextBeforeId, isChatLaunching, launchingTaskName, messages, setupInfo]);

  const rowProps = useMemo<ChatMessageRowProps>(
    () => ({
      rows,
      isLoadingOlder,
      loadOlderChatHistory,
    }),
    [isLoadingOlder, loadOlderChatHistory, rows],
  );

  const shouldRevealThinking = isChatLaunching || messages[messages.length - 1]?.sender === "thinking";

  const scrollThinkingIntoView = useCallback(() => {
    const listApi = listApiRef.current;
    const listElement = chatMessagesRef.current;

    if (listApi && rows.length > 0) {
      try {
        listApi.scrollToRow({ index: rows.length - 1, align: "end", behavior: "instant" });
        return;
      } catch {
        // Fall through to direct DOM scrolling if the virtual list is between renders.
      }
    }

    if (listElement) {
      listElement.scrollTop = listElement.scrollHeight;
    }
  }, [chatMessagesRef, rows.length]);

  const handleListResize = useCallback(() => {
    if (!shouldRevealThinking || typeof window === "undefined") return;
    window.requestAnimationFrame(scrollThinkingIntoView);
  }, [scrollThinkingIntoView, shouldRevealThinking]);

  useIsomorphicLayoutEffect(() => {
    if (!shouldRevealThinking) return;

    scrollThinkingIntoView();

    if (typeof window === "undefined") return;

    const animationFrameIds: number[] = [];
    const timeoutIds: number[] = [];
    const scheduleAnimationFrame = () => {
      const frameId = window.requestAnimationFrame(() => {
        scrollThinkingIntoView();
      });
      animationFrameIds.push(frameId);
    };

    scheduleAnimationFrame();
    const nestedFrameId = window.requestAnimationFrame(() => {
      scrollThinkingIntoView();
      scheduleAnimationFrame();
    });
    animationFrameIds.push(nestedFrameId);

    [80, 220].forEach((delay) => {
      const timeoutId = window.setTimeout(scrollThinkingIntoView, delay);
      timeoutIds.push(timeoutId);
    });

    return () => {
      animationFrameIds.forEach((frameId) => {
        window.cancelAnimationFrame(frameId);
      });
      timeoutIds.forEach((timeoutId) => {
        window.clearTimeout(timeoutId);
      });
    };
  }, [scrollThinkingIntoView, shouldRevealThinking]);

  return (
    <List
      aria-busy={isChatLaunching || isGenerating ? "true" : undefined}
      aria-live="polite"
      aria-relevant="additions text"
      aria-label="チャットメッセージ"
      className="chat-messages chat-messages--virtual scroll-pb-24"
      defaultHeight={480}
      id="chat-messages"
      listRef={setListRef}
      onResize={handleListResize}
      overscanCount={6}
      role="log"
      rowComponent={ChatMessageRow}
      rowCount={rows.length}
      rowHeight={rowHeight}
      rowProps={rowProps}
      style={{ width: "100%" }}
    />
  );
}

export const ChatMessageList = memo(ChatMessageListComponent);
ChatMessageList.displayName = "ChatMessageList";
