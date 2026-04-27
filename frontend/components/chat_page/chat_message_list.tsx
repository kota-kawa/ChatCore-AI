import {
  memo,
  useCallback,
  useMemo,
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
    return (
      <div {...ariaAttributes} className={rowClassName} style={style}>
        <div className="message-wrapper bot-message-wrapper thinking-message-wrapper">
          <div className="thinking-message" role="status" aria-live="polite" aria-label="AIが応答を準備しています">
            <ThinkingConstellation />
          </div>
        </div>
      </div>
    );
  }

  if (message.sender === "user") {
    return (
      <div {...ariaAttributes} className={rowClassName} style={style}>
        <div className="message-wrapper user-message-wrapper">
          <div className="user-message">
            <UserMessageHtml text={message.text} />
          </div>
          <div className="message-actions">
            <CopyActionButton
              getText={() => {
                return message.text;
              }}
            />
          </div>
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
  hasLaunchSetupInfo: boolean;
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
  hasLaunchSetupInfo,
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

  const setStaticMessagesRef = useCallback(
    (node: HTMLDivElement | null) => {
      chatMessagesRef.current = node;
    },
    [chatMessagesRef],
  );

  const setListRef = useCallback(
    (api: ListImperativeAPI | null) => {
      chatMessagesRef.current = api?.element ?? null;
    },
    [chatMessagesRef],
  );

  const rows = useMemo<ChatMessageListRow[]>(() => {
    const nextRows: ChatMessageListRow[] = [];
    if (historyHasMore && historyNextBeforeId !== null) {
      nextRows.push({ kind: "load-more" });
    }
    messages.forEach((message) => {
      nextRows.push({ kind: "message", message });
    });
    return nextRows;
  }, [historyHasMore, historyNextBeforeId, messages]);

  const rowProps = useMemo<ChatMessageRowProps>(
    () => ({
      rows,
      isLoadingOlder,
      loadOlderChatHistory,
    }),
    [isLoadingOlder, loadOlderChatHistory, rows],
  );

  if (isChatLaunching) {
    // 実際のチャット開始後に表示されるのと同じ形式のフルメッセージを組み立てる
    const fullDisplayContent = [
      launchingTaskName ? `【タスク】${launchingTaskName}` : "",
      setupInfo ? `【状況・作業環境】${setupInfo}` : "",
    ]
      .filter(Boolean)
      .join("\n");

    return (
      <div
        className="chat-messages scroll-pb-24"
        id="chat-messages"
        ref={setStaticMessagesRef}
        aria-busy="true"
        aria-live="polite"
      >
        <div className="chat-message-row chat-message-row--first">
          <div className="message-wrapper user-message-wrapper">
            <div className="user-message">
              {fullDisplayContent ? (
                <UserMessageHtml text={fullDisplayContent} />
              ) : (
                <div className="chat-launch-placeholder__title">
                  {launchingTaskName ? `「${launchingTaskName}」のチャットを準備しています` : "チャットを準備しています"}
                </div>
              )}
            </div>
            {/* 実際のメッセージと同じアクション欄を配置して高さを合わせる */}
            <div className="message-actions" style={{ visibility: "hidden", pointerEvents: "none" }}>
              <div className="copy-btn"><i className="bi bi-clipboard"></i></div>
            </div>
          </div>
        </div>

        <div className="chat-message-row">
          <div className="message-wrapper bot-message-wrapper">
            <div className="chat-launch-placeholder" style={{ margin: 0, width: "100%", maxWidth: "none", background: "none", border: "none", boxShadow: "none", padding: "0.25rem 0" }}>
              <div className="chat-launch-placeholder__meta" style={{ marginTop: 0 }}>
                <div className="chat-launch-placeholder__pulse" aria-hidden="true">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
                <div className="chat-launch-placeholder__eyebrow" style={{ marginLeft: "auto" }}>Preparing Chat</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <List
      aria-busy={isGenerating ? "true" : undefined}
      aria-live="polite"
      aria-relevant="additions text"
      aria-label="チャットメッセージ"
      className="chat-messages chat-messages--virtual scroll-pb-24"
      defaultHeight={480}
      id="chat-messages"
      listRef={setListRef}
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
