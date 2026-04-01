import type { Dispatch, KeyboardEvent as ReactKeyboardEvent, MutableRefObject, SetStateAction } from "react";

import { BotMessageHtml } from "./bot_message_html";
import { CopyActionButton } from "./copy_action_button";
import { MemoSaveActionButton } from "./memo_save_action_button";
import { ThinkingConstellation } from "./thinking_constellation";
import type { ChatRoom, UiChatMessage } from "../../lib/chat_page/types";
import { MODEL_OPTIONS, roomMenuBaseStyle, roomMenuItemBaseStyle } from "../../lib/chat_page/constants";

type ChatMainSectionProps = {
  isChatVisible: boolean;
  chatHeaderModelMenuOpen: boolean;
  selectedModel: string;
  selectedModelShortLabel: string;
  hasCurrentRoom: boolean;
  sidebarOpen: boolean;
  chatRooms: ChatRoom[];
  currentRoomId: string | null;
  openRoomActionsFor: string | null;
  historyHasMore: boolean;
  historyNextBeforeId: number | null;
  isLoadingOlder: boolean;
  messages: UiChatMessage[];
  chatInput: string;
  isGenerating: boolean;
  chatHeaderModelSelectRef: MutableRefObject<HTMLDivElement | null>;
  chatMessagesRef: MutableRefObject<HTMLDivElement | null>;
  showSetupForm: () => void;
  setChatHeaderModelMenuOpen: Dispatch<SetStateAction<boolean>>;
  setSelectedModel: Dispatch<SetStateAction<string>>;
  openShareModal: () => void;
  handleNewChat: () => void;
  switchChatRoom: (roomId: string) => void;
  setOpenRoomActionsFor: Dispatch<SetStateAction<string | null>>;
  handleRenameRoom: (roomId: string, roomTitle: string) => Promise<void>;
  handleDeleteRoom: (roomId: string, roomTitle: string) => Promise<void>;
  setSidebarOpen: Dispatch<SetStateAction<boolean>>;
  loadOlderChatHistory: () => Promise<void>;
  setChatInput: Dispatch<SetStateAction<string>>;
  handleChatInputKeyDown: (event: ReactKeyboardEvent<HTMLInputElement>) => void;
  handleSendMessage: () => void;
};

export function ChatMainSection({
  isChatVisible,
  chatHeaderModelMenuOpen,
  selectedModel,
  selectedModelShortLabel,
  hasCurrentRoom,
  sidebarOpen,
  chatRooms,
  currentRoomId,
  openRoomActionsFor,
  historyHasMore,
  historyNextBeforeId,
  isLoadingOlder,
  messages,
  chatInput,
  isGenerating,
  chatHeaderModelSelectRef,
  chatMessagesRef,
  showSetupForm,
  setChatHeaderModelMenuOpen,
  setSelectedModel,
  openShareModal,
  handleNewChat,
  switchChatRoom,
  setOpenRoomActionsFor,
  handleRenameRoom,
  handleDeleteRoom,
  setSidebarOpen,
  loadOlderChatHistory,
  setChatInput,
  handleChatInputKeyDown,
  handleSendMessage,
}: ChatMainSectionProps) {
  return (
    <div id="chat-container" style={{ display: isChatVisible ? "flex" : "none" }}>
      <div className="chat-header">
        <div className="header-left">
          <button
            id="back-to-setup"
            className="icon-button"
            data-tooltip="タスク選択に戻る"
            data-tooltip-placement="bottom"
            onClick={() => {
              showSetupForm();
            }}
          >
            <i className="bi bi-arrow-left"></i>
          </button>
          <span>Chat Core</span>
        </div>
        <div className="header-right">
          <div
            ref={chatHeaderModelSelectRef}
            className={`chat-header-model-select ${chatHeaderModelMenuOpen ? "is-open" : ""}`.trim()}
          >
            <button
              type="button"
              className="chat-header-model-trigger"
              aria-haspopup="listbox"
              aria-expanded={chatHeaderModelMenuOpen ? "true" : "false"}
              onClick={() => {
                setChatHeaderModelMenuOpen((previous) => !previous);
              }}
            >
              <i className="bi bi-cpu"></i>
              <span>{selectedModelShortLabel}</span>
              <i className="bi bi-chevron-down chat-header-model-chevron"></i>
            </button>
            <div className="chat-header-model-menu" role="listbox">
              {MODEL_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={`chat-header-model-option ${selectedModel === option.value ? "is-selected" : ""}`.trim()}
                  role="option"
                  aria-selected={selectedModel === option.value ? "true" : "false"}
                  onClick={() => {
                    setSelectedModel(option.value);
                    setChatHeaderModelMenuOpen(false);
                  }}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <button
            id="share-chat-btn"
            className={`icon-button chat-share-btn ${hasCurrentRoom ? "" : "chat-share-btn--disabled"}`.trim()}
            type="button"
            data-tooltip="このチャットを共有"
            data-tooltip-placement="bottom"
            disabled={!hasCurrentRoom}
            aria-disabled={hasCurrentRoom ? "false" : "true"}
            onClick={() => {
              if (!hasCurrentRoom) return;
              openShareModal();
            }}
          >
            <i className="bi bi-share"></i>
          </button>
        </div>
      </div>

      <div className="chat-main">
        <div className={`sidebar ${sidebarOpen ? "open" : ""}`.trim()} id="chat-room-sidebar">
          <button
            id="new-chat-btn"
            className="new-chat-btn"
            onClick={() => {
              handleNewChat();
            }}
          >
            <i className="bi bi-plus-lg"></i> 新規チャット
          </button>

          <div id="chat-room-list">
            {chatRooms.map((room) => {
              const roomMenuOpen = openRoomActionsFor === room.id;

              return (
                <div
                  key={room.id}
                  className={`chat-room-card ${currentRoomId === room.id ? "active" : ""}`.trim()}
                  onClick={(event) => {
                    const target = event.target as Element;
                    if (target.closest(".room-actions-icon") || target.closest(".room-actions-menu")) {
                      return;
                    }
                    switchChatRoom(room.id);
                  }}
                >
                  <span>{room.title || "新規チャット"}</span>

                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      position: "relative",
                      marginLeft: "auto",
                    }}
                  >
                    <i
                      className="bi bi-three-dots-vertical room-actions-icon"
                      style={{ cursor: "pointer", fontSize: "18px" }}
                      onClick={(event) => {
                        event.stopPropagation();
                        setOpenRoomActionsFor((previous) => (previous === room.id ? null : room.id));
                      }}
                    ></i>

                    <div className="room-actions-menu" style={{ ...roomMenuBaseStyle, display: roomMenuOpen ? "block" : "none" }}>
                      <div
                        className="menu-item"
                        style={{ ...roomMenuItemBaseStyle, color: "#007bff", background: "#f9f9f9" }}
                        onMouseEnter={(event) => {
                          (event.currentTarget as HTMLDivElement).style.backgroundColor = "#e6f0ff";
                        }}
                        onMouseLeave={(event) => {
                          (event.currentTarget as HTMLDivElement).style.backgroundColor = "#f9f9f9";
                        }}
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleRenameRoom(room.id, room.title);
                        }}
                      >
                        <i className="bi bi-pencil-square" style={{ marginRight: "6px" }}></i> 名前変更
                      </div>

                      <div
                        className="menu-item"
                        style={{
                          ...roomMenuItemBaseStyle,
                          color: "#dc3545",
                          background: "#f9f9f9",
                          borderBottom: "none",
                        }}
                        onMouseEnter={(event) => {
                          (event.currentTarget as HTMLDivElement).style.backgroundColor = "#ffe6e6";
                        }}
                        onMouseLeave={(event) => {
                          (event.currentTarget as HTMLDivElement).style.backgroundColor = "#f9f9f9";
                        }}
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleDeleteRoom(room.id, room.title);
                        }}
                      >
                        <i className="bi bi-trash" style={{ marginRight: "6px" }}></i> 削除
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="chat-area">
          <button
            id="sidebar-toggle"
            className="icon-button sidebar-toggle chat-sidebar-toggle"
            data-tooltip="チャット一覧を表示"
            data-tooltip-placement="left"
            aria-expanded={sidebarOpen ? "true" : "false"}
            onClick={(event) => {
              event.stopPropagation();
              setSidebarOpen((previous) => !previous);
            }}
          >
            <i className="bi bi-arrow-bar-right"></i>
          </button>

          <div className="chat-messages" id="chat-messages" ref={chatMessagesRef} aria-busy={isGenerating ? "true" : undefined}>
            {historyHasMore && historyNextBeforeId !== null && (
              <button
                type="button"
                className="chat-history-load-more-btn"
                disabled={isLoadingOlder}
                onClick={() => {
                  void loadOlderChatHistory();
                }}
              >
                {isLoadingOlder ? "読み込み中..." : "過去のメッセージを読み込む"}
              </button>
            )}

            {messages.map((message) => {
              if (message.sender === "thinking") {
                return (
                  <div key={message.id} className="message-wrapper bot-message-wrapper thinking-message-wrapper">
                    <div className="thinking-message" role="status" aria-live="polite" aria-label="AIが応答を準備しています">
                      <ThinkingConstellation />
                    </div>
                  </div>
                );
              }

              if (message.sender === "user") {
                return (
                  <div key={message.id} className="message-wrapper user-message-wrapper">
                    <div className="user-message" style={{ whiteSpace: "pre-wrap" }}>
                      {message.text}
                    </div>
                    <div className="message-actions">
                      <CopyActionButton
                        getText={() => {
                          return message.text;
                        }}
                      />
                    </div>
                  </div>
                );
              }

              return (
                <div
                  key={message.id}
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
              );
            })}
          </div>

          <div className="input-container">
            <div className="input-wrapper">
              <input
                type="text"
                id="user-input"
                placeholder="メッセージを入力..."
                value={chatInput}
                onChange={(event) => {
                  setChatInput(event.target.value);
                }}
                onKeyDown={handleChatInputKeyDown}
              />
              <button
                type="button"
                id="send-btn"
                className={isGenerating ? "send-btn--stop" : ""}
                aria-label={isGenerating ? "停止" : "送信"}
                data-tooltip={isGenerating ? "生成を停止" : "メッセージを送信"}
                data-tooltip-placement="top"
                onClick={() => {
                  handleSendMessage();
                }}
              >
                <i className={`bi ${isGenerating ? "bi-stop-fill" : "bi-send"}`}></i>
              </button>
            </div>
          </div>

          <chat-action-menu></chat-action-menu>
        </div>
      </div>
    </div>
  );
}
