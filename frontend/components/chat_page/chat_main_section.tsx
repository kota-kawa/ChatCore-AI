import { memo, useEffect, useRef } from "react";
import { BotMessageHtml } from "./bot_message_html";
import { UserMessageHtml } from "./user_message_html";
import { CopyActionButton } from "./copy_action_button";
import { MemoSaveActionButton } from "./memo_save_action_button";
import { ThinkingConstellation } from "./thinking_constellation";
import { useHomePageChatContext, useHomePageTaskContext, useHomePageUiContext } from "../../contexts/chat_page/home_page_context";
import { MAX_CHAT_MESSAGE_LENGTH, MODEL_OPTIONS } from "../../lib/chat_page/constants";

function ChatMainSectionComponent() {
  const {
    pageViewState,
    isChatVisible,
    isChatLaunching,
    setupInfo,
    chatHeaderModelMenuOpen,
    selectedModel,
    selectedModelShortLabel,
    chatHeaderModelSelectRef,
    showSetupForm,
    setChatHeaderModelMenuOpen,
    setSelectedModel,
  } = useHomePageUiContext();

  const { launchingTaskName } = useHomePageTaskContext();

  const {
    hasCurrentRoom,
    sidebarOpen,
    chatRooms,
    currentRoomId,
    currentRoomMode,
    openRoomActionsFor,
    historyHasMore,
    historyNextBeforeId,
    isLoadingOlder,
    messages,
    chatMessagesRef,
    chatInput,
    isGenerating,
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
  } = useHomePageChatContext();

  const chatInputRef = useRef<HTMLTextAreaElement | null>(null);
  const hasLaunchSetupInfo = setupInfo.trim().length > 0;
  const canShareCurrentRoom = hasCurrentRoom && !isChatLaunching && currentRoomMode !== "temporary";

  const handleRoomCardKeyDown = (
    event: React.KeyboardEvent<HTMLDivElement>,
    roomId: string,
    roomMode: "normal" | "temporary",
  ) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    switchChatRoom(roomId, roomMode);
  };

  const adjustChatInputHeight = (element: HTMLTextAreaElement | null) => {
    if (!element) return;

    const computed = window.getComputedStyle(element);
    const lineHeight = Number.parseFloat(computed.lineHeight) || 24;
    const verticalPadding = Number.parseFloat(computed.paddingTop) + Number.parseFloat(computed.paddingBottom);
    const verticalBorder = Number.parseFloat(computed.borderTopWidth) + Number.parseFloat(computed.borderBottomWidth);
    const maxHeight = lineHeight * 6 + verticalPadding + verticalBorder;

    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, maxHeight)}px`;
    element.style.overflowY = element.scrollHeight > maxHeight ? "auto" : "hidden";
  };

  useEffect(() => {
    adjustChatInputHeight(chatInputRef.current);
  }, [chatInput]);

  return (
    <div
      id="chat-container"
      data-view={pageViewState}
      data-launching={isChatLaunching ? "true" : "false"}
      aria-hidden={isChatVisible ? "false" : "true"}
    >
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
          {currentRoomMode === "temporary" && (
            <span className="chat-room-mode-badge">未保存</span>
          )}
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
            className={`icon-button chat-share-btn ${canShareCurrentRoom ? "" : "chat-share-btn--disabled"}`.trim()}
            type="button"
            data-tooltip={currentRoomMode === "temporary" ? "未保存チャットは共有できません" : "このチャットを共有"}
            data-tooltip-placement="bottom"
            disabled={!canShareCurrentRoom}
            onClick={() => {
              if (!canShareCurrentRoom) return;
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
              const roomTitle = room.title || "新規チャット";
              const roomMenuId = `room-actions-menu-${room.id}`;

              return (
                <div
                  key={room.id}
                  className={`chat-room-card ${currentRoomId === room.id ? "active" : ""}`.trim()}
                  role="button"
                  tabIndex={0}
                  aria-current={currentRoomId === room.id ? "page" : undefined}
                  onClick={() => {
                    switchChatRoom(room.id, room.mode);
                  }}
                  onKeyDown={(event) => {
                    handleRoomCardKeyDown(event, room.id, room.mode);
                  }}
                >
                  <div className="chat-room-card__trigger">
                    <span className="chat-room-card__title-row">
                      <span>{roomTitle}</span>
                      {room.mode === "temporary" && (
                        <span className="chat-room-card__mode-badge">未保存</span>
                      )}
                    </span>
                  </div>

                  <div className="chat-room-card-actions">
                    <button
                      type="button"
                      className="room-actions-icon"
                      aria-label={`${roomTitle} の操作メニューを開く`}
                      aria-haspopup="menu"
                      aria-expanded={roomMenuOpen ? "true" : "false"}
                      aria-controls={roomMenuId}
                      onClick={(event) => {
                        event.stopPropagation();
                        setOpenRoomActionsFor((previous) => (previous === room.id ? null : room.id));
                      }}
                    >
                      <i className="bi bi-three-dots-vertical" aria-hidden="true"></i>
                    </button>

                    <div
                      id={roomMenuId}
                      className={`room-actions-menu ${roomMenuOpen ? "is-open" : ""}`.trim()}
                      role="menu"
                      aria-hidden={roomMenuOpen ? "false" : "true"}
                    >
                      <button
                        type="button"
                        className="menu-item menu-item--rename"
                        role="menuitem"
                        onClick={(event) => {
                          event.stopPropagation();
                          setOpenRoomActionsFor(null);
                          void handleRenameRoom(room.id, room.title);
                        }}
                      >
                        <i className="bi bi-pencil-square menu-item__icon"></i> 名前変更
                      </button>

                      <button
                        type="button"
                        className="menu-item menu-item--delete"
                        role="menuitem"
                        onClick={(event) => {
                          event.stopPropagation();
                          setOpenRoomActionsFor(null);
                          void handleDeleteRoom(room.id, room.title);
                        }}
                      >
                        <i className="bi bi-trash menu-item__icon"></i> 削除
                      </button>
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

          <div
            className="chat-messages scroll-pb-24"
            id="chat-messages"
            ref={chatMessagesRef}
            aria-busy={isGenerating || isChatLaunching ? "true" : undefined}
          >
            {isChatLaunching ? (
              <div className="chat-launch-placeholder" role="status" aria-live="polite">
                <div className="chat-launch-placeholder__eyebrow">Preparing chat</div>
                <div className="chat-launch-placeholder__title">
                  {launchingTaskName ? `「${launchingTaskName}」のチャットを準備しています` : "チャットを準備しています"}
                </div>
                {hasLaunchSetupInfo && (
                  <p className="chat-launch-placeholder__summary">入力内容をチャットに反映しています。</p>
                )}
                <div className="chat-launch-placeholder__meta">
                  {launchingTaskName && <span className="chat-launch-placeholder__task-pill">Task selected</span>}
                  <div className="chat-launch-placeholder__pulse" aria-hidden="true">
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                </div>
              </div>
            ) : (
              <>
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
              </>
            )}
          </div>

          <div className="input-container supports-[backdrop-filter]:backdrop-blur-xl">
            <div className="input-wrapper">
              <textarea
                ref={chatInputRef}
                id="user-input"
                rows={1}
                placeholder={isChatLaunching ? "チャットを準備しています..." : "メッセージを入力..."}
                value={chatInput}
                disabled={isChatLaunching}
                onChange={(event) => {
                  setChatInput(event.target.value);
                  adjustChatInputHeight(event.currentTarget);
                }}
                onKeyDown={handleChatInputKeyDown}
              ></textarea>
              <button
                type="button"
                id="send-btn"
                className={isGenerating ? "send-btn--stop" : ""}
                aria-label={isGenerating ? "停止" : "送信"}
                data-tooltip={isGenerating ? "生成を停止" : "メッセージを送信"}
                data-tooltip-placement="top"
                disabled={isChatLaunching}
                onClick={() => {
                  handleSendMessage();
                }}
              >
                <i className={`bi ${isGenerating ? "bi-stop-fill" : "bi-send"}`}></i>
              </button>
            </div>
            {chatInput.length > 0 && (
              <div className={`chat-input-counter${chatInput.length > MAX_CHAT_MESSAGE_LENGTH ? " chat-input-counter--over" : ""}`}>
                {chatInput.length > MAX_CHAT_MESSAGE_LENGTH
                  ? `文字数制限を超えています（${chatInput.length.toLocaleString()} / ${MAX_CHAT_MESSAGE_LENGTH.toLocaleString()}文字）`
                  : `${chatInput.length.toLocaleString()} / ${MAX_CHAT_MESSAGE_LENGTH.toLocaleString()}文字`}
              </div>
            )}
          </div>

          <chat-action-menu></chat-action-menu>
        </div>
      </div>
    </div>
  );
}

export const ChatMainSection = memo(ChatMainSectionComponent);
ChatMainSection.displayName = "ChatMainSection";
