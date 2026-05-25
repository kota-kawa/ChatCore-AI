import { memo, useCallback, useEffect, useMemo, useRef, type ChangeEvent } from "react";
import { ChatMessageList } from "./chat_message_list";
import { InlineLoading } from "../ui/inline_loading";
import { useHomePageChatContext, useHomePageTaskContext, useHomePageUiContext } from "../../contexts/chat_page/home_page_context";
import { MAX_CHAT_MESSAGE_LENGTH, MODEL_OPTIONS } from "../../lib/chat_page/constants";
import {
  CHAT_ATTACHMENT_ACCEPT,
  getAttachmentIconClass,
  mergeChatAttachments,
  readSelectedChatAttachments,
} from "../../lib/chat_page/file_attachments";
import { extractUrlsFromText, getUrlDomain } from "../../lib/chat_page/url_utils";

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
    chatRoomsHasMore,
    isLoadingMoreChatRooms,
    currentRoomId,
    currentRoomMode,
    openRoomActionsFor,
    isRoomSelectionMode,
    selectedRoomIds,
    isBulkDeletingRooms,
    chatMessageListResetKey,
    historyHasMore,
    historyNextBeforeId,
    isLoadingOlder,
    messages,
    chatMessagesRef,
    chatInput,
    attachedFiles,
    setAttachedFiles,
    isGenerating,
    openShareModal,
    handleNewChat,
    switchChatRoom,
    setOpenRoomActionsFor,
    handleRenameRoom,
    handleDeleteRoom,
    handleBulkDeleteRooms,
    enterRoomSelectionMode,
    toggleRoomSelection,
    cancelRoomSelection,
    setSidebarOpen,
    loadMoreChatRooms,
    loadOlderChatHistory,
    setChatInput,
    handleChatInputKeyDown,
    handleSendMessage,
    handleRegenerateMessage,
    handleEditAndRegenerateMessage,
    handleSwitchBranch,
  } = useHomePageChatContext();

  const chatInputRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const sidebarRef = useRef<HTMLDivElement | null>(null);
  const chatRoomsLoadMoreRef = useRef<HTMLDivElement | null>(null);
  const canShareCurrentRoom = hasCurrentRoom && !isChatLaunching && currentRoomMode !== "temporary";
  const selectedRoomCount = selectedRoomIds.size;
  const hasSelectedRooms = selectedRoomCount > 0;
  const canSendChatMessage =
    hasCurrentRoom &&
    !isChatLaunching &&
    chatInput.trim().length > 0 &&
    chatInput.length <= MAX_CHAT_MESSAGE_LENGTH;

  const detectedUrls = useMemo(() => extractUrlsFromText(chatInput), [chatInput]);

  const notifyAttachmentError = useCallback((message: string) => {
    import("../../scripts/core/toast").then(({ showToast }) => {
      showToast(message, { variant: "error" });
    });
  }, []);

  const handleFileInputChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const files = event.target.files;
      if (!files || files.length === 0) return;

      void readSelectedChatAttachments(Array.from(files), attachedFiles, notifyAttachmentError).then(
        (selectedFiles) => {
          if (selectedFiles.length === 0) return;
          setAttachedFiles((prev) => mergeChatAttachments(prev, selectedFiles));
        },
      );

      if (event.target) {
        event.target.value = "";
      }
    },
    [attachedFiles, notifyAttachmentError, setAttachedFiles],
  );

  const handleRemoveAttachedFile = useCallback(
    (fileId: string) => {
      setAttachedFiles((prev) => prev.filter((f) => f.id !== fileId));
    },
    [setAttachedFiles],
  );

  const handleRoomCardKeyDown = (
    event: React.KeyboardEvent<HTMLDivElement>,
    roomId: string,
    roomMode: "normal" | "temporary",
  ) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    if (isRoomSelectionMode) {
      toggleRoomSelection(roomId);
      return;
    }
    switchChatRoom(roomId, roomMode);
  };

  const handleSidebarScroll = useCallback(
    (event: React.UIEvent<HTMLDivElement>) => {
      if (!chatRoomsHasMore || isLoadingMoreChatRooms) return;
      const target = event.currentTarget;
      const remaining = target.scrollHeight - target.scrollTop - target.clientHeight;
      if (remaining > 160) return;
      void loadMoreChatRooms();
    },
    [chatRoomsHasMore, isLoadingMoreChatRooms, loadMoreChatRooms],
  );

  useEffect(() => {
    const sidebar = sidebarRef.current;
    const sentinel = chatRoomsLoadMoreRef.current;
    if (!sidebar || !sentinel || !chatRoomsHasMore) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        void loadMoreChatRooms();
      },
      {
        root: sidebar,
        rootMargin: "160px 0px",
        threshold: 0,
      },
    );

    observer.observe(sentinel);
    return () => {
      observer.disconnect();
    };
  }, [chatRooms.length, chatRoomsHasMore, loadMoreChatRooms]);

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

  // モバイルでテキスト入力欄にフォーカスした際、最新メッセージを画面下端に貼り付け、
  // ヘッダー・入力欄が常に見える状態を保証する。
  const handleChatInputFocus = () => {
    const list = chatMessagesRef.current;
    if (!list) return;
    // visualViewport.resize が走るまでわずかに待ってからスクロール位置を補正する。
    window.setTimeout(() => {
      const node = chatMessagesRef.current;
      if (!node) return;
      node.scrollTop = node.scrollHeight;
    }, 220);
  };

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

      <div className={`chat-main ${sidebarOpen ? "chat-main--sidebar-open" : "chat-main--sidebar-closed"}`.trim()}>
        <div
          ref={sidebarRef}
          className={`sidebar ${sidebarOpen ? "open" : ""}`.trim()}
          id="chat-room-sidebar"
          aria-hidden={sidebarOpen ? "false" : "true"}
          onScroll={handleSidebarScroll}
        >
          {isRoomSelectionMode ? (
            <div className="room-selection-bar" aria-live="polite">
              <span className="room-selection-bar__count">{selectedRoomCount}件選択中</span>
              <button
                type="button"
                className="room-selection-bar__button room-selection-bar__button--danger"
                disabled={!hasSelectedRooms || isBulkDeletingRooms}
                onClick={() => {
                  void handleBulkDeleteRooms();
                }}
              >
                <i className="bi bi-trash" aria-hidden="true"></i>
                <span>{isBulkDeletingRooms ? "削除中..." : "削除"}</span>
              </button>
              <button
                type="button"
                className="room-selection-bar__button"
                disabled={isBulkDeletingRooms}
                onClick={() => {
                  cancelRoomSelection();
                }}
              >
                キャンセル
              </button>
            </div>
          ) : (
            <button
              id="new-chat-btn"
              className="new-chat-btn"
              onClick={() => {
                handleNewChat();
              }}
            >
              <i className="bi bi-plus-lg"></i> 新規チャット
            </button>
          )}

          <div id="chat-room-list" aria-busy={isLoadingMoreChatRooms ? "true" : "false"}>
            {chatRooms.map((room) => {
              const roomMenuOpen = openRoomActionsFor === room.id;
              const roomTitle = room.title || "新規チャット";
              const roomMenuId = `room-actions-menu-${room.id}`;
              const roomSelected = selectedRoomIds.has(room.id);

              return (
                <div
                  key={room.id}
                  className={`chat-room-card ${currentRoomId === room.id ? "active" : ""} ${isRoomSelectionMode ? "chat-room-card--selectable" : ""} ${roomSelected ? "chat-room-card--selected" : ""}`.trim()}
                  role={isRoomSelectionMode ? "checkbox" : "button"}
                  tabIndex={0}
                  aria-current={currentRoomId === room.id ? "page" : undefined}
                  aria-checked={isRoomSelectionMode ? (roomSelected ? "true" : "false") : undefined}
                  onClick={() => {
                    if (isRoomSelectionMode) {
                      toggleRoomSelection(room.id);
                      return;
                    }
                    switchChatRoom(room.id, room.mode);
                  }}
                  onKeyDown={(event) => {
                    handleRoomCardKeyDown(event, room.id, room.mode);
                  }}
                >
                  {isRoomSelectionMode && (
                    <span className="chat-room-card__check" aria-hidden="true">
                      <i className={`bi ${roomSelected ? "bi-check-lg" : "bi-circle"}`}></i>
                    </span>
                  )}

                  <div className="chat-room-card__trigger">
                    <span className="chat-room-card__title-row">
                      <span>{roomTitle}</span>
                      {room.mode === "temporary" && (
                        <span className="chat-room-card__mode-badge">未保存</span>
                      )}
                    </span>
                  </div>

                  {!isRoomSelectionMode && (
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
                          className="menu-item menu-item--select"
                          role="menuitem"
                          onClick={(event) => {
                            event.stopPropagation();
                            enterRoomSelectionMode(room.id);
                          }}
                        >
                          <i className="bi bi-check2-square menu-item__icon"></i> 複数選択
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
                  )}
                </div>
              );
            })}
            {isLoadingMoreChatRooms && (
              <div className="chat-room-list__loading" role="status" aria-live="polite">
                <InlineLoading label="読み込み中" />
              </div>
            )}
            <div ref={chatRoomsLoadMoreRef} className="chat-room-list__sentinel" aria-hidden="true" />
          </div>
        </div>

        <div className="chat-area">
          <button
            id="sidebar-toggle"
            className="icon-button sidebar-toggle chat-sidebar-toggle"
            aria-label={sidebarOpen ? "チャット履歴を閉じる" : "チャット履歴を開く"}
            aria-controls="chat-room-sidebar"
            data-tooltip={sidebarOpen ? "チャット履歴を閉じる" : "チャット履歴を開く"}
            data-tooltip-placement="left"
            aria-expanded={sidebarOpen ? "true" : "false"}
            onClick={(event) => {
              event.stopPropagation();
              setSidebarOpen((previous) => !previous);
            }}
          >
            <i className={`bi ${sidebarOpen ? "bi-x-lg" : "bi-layout-sidebar-inset"}`}></i>
          </button>

          <ChatMessageList
            key={`chat-message-list:${chatMessageListResetKey}`}
            chatMessagesRef={chatMessagesRef}
            currentRoomId={currentRoomId}
            setupInfo={setupInfo}
            historyHasMore={historyHasMore}
            historyNextBeforeId={historyNextBeforeId}
            isChatLaunching={isChatLaunching}
            isGenerating={isGenerating}
            isLoadingOlder={isLoadingOlder}
            launchingTaskName={launchingTaskName}
            loadOlderChatHistory={loadOlderChatHistory}
            messages={messages}
            onRegenerate={handleRegenerateMessage}
            onEditAndRegenerate={handleEditAndRegenerateMessage}
            onSwitchBranch={handleSwitchBranch}
          />

          <div className="input-container supports-[backdrop-filter]:backdrop-blur-xl">
            {detectedUrls.length > 0 && (
              <div className="chat-detected-urls" aria-label="送信時にAIが読み取るURL">
                {detectedUrls.map((url) => (
                  <div key={url} className="chat-detected-url-chip" title={url}>
                    <i className="bi bi-globe2 chat-detected-url-chip__icon" aria-hidden="true"></i>
                    <span className="chat-detected-url-chip__domain">{getUrlDomain(url)}</span>
                    <span className="chat-detected-url-chip__label">AIが読み取り</span>
                  </div>
                ))}
              </div>
            )}
            {attachedFiles.length > 0 && (
              <div className="chat-attached-files">
                {attachedFiles.map((file) => (
                  <div key={file.id} className="chat-attached-file-chip">
                    <i
                      className={`bi ${getAttachmentIconClass(file.name)} chat-attached-file-chip__icon`}
                      aria-hidden="true"
                    ></i>
                    <span className="chat-attached-file-chip__name" title={file.name}>{file.name}</span>
                    <span className="chat-attached-file-chip__size">
                      {file.size < 1024
                        ? `${file.size}B`
                        : file.size < 1_048_576
                        ? `${(file.size / 1024).toFixed(1)}KB`
                        : `${(file.size / 1_048_576).toFixed(1)}MB`}
                    </span>
                    <button
                      type="button"
                      className="chat-attached-file-chip__remove"
                      aria-label={`${file.name}を削除`}
                      onClick={() => handleRemoveAttachedFile(file.id)}
                    >
                      <i className="bi bi-x" aria-hidden="true"></i>
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="input-wrapper">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={CHAT_ATTACHMENT_ACCEPT}
                className="chat-file-input-hidden"
                aria-hidden="true"
                tabIndex={-1}
                onChange={handleFileInputChange}
              />
              <button
                type="button"
                className="chat-attach-btn"
                aria-label="ファイルを添付"
                data-tooltip="ファイルを添付"
                data-tooltip-placement="top"
                disabled={isChatLaunching || attachedFiles.length >= 5}
                onClick={() => fileInputRef.current?.click()}
              >
                <i className="bi bi-paperclip" aria-hidden="true"></i>
              </button>
              <textarea
                ref={chatInputRef}
                id="user-input"
                rows={1}
                placeholder={isChatLaunching ? "チャットを準備しています..." : "メッセージを入力..."}
                value={chatInput}
                disabled={isChatLaunching}
                enterKeyHint="send"
                autoCorrect="off"
                autoCapitalize="sentences"
                onChange={(event) => {
                  setChatInput(event.target.value);
                  adjustChatInputHeight(event.currentTarget);
                }}
                onFocus={handleChatInputFocus}
                onKeyDown={handleChatInputKeyDown}
              ></textarea>
              <button
                type="button"
                id="send-btn"
                className={isGenerating ? "send-btn--stop" : ""}
                aria-label={isGenerating ? "停止" : "送信"}
                data-tooltip={isGenerating ? "生成を停止" : "メッセージを送信"}
                data-tooltip-placement="top"
                disabled={isChatLaunching || (!isGenerating && !canSendChatMessage)}
                onClick={() => {
                  if (!isGenerating && !canSendChatMessage) return;
                  handleSendMessage();
                }}
              >
                <i className={`bi ${isGenerating ? "bi-stop-fill" : "bi-send"}`}></i>
                <div className="send-btn-spinner"></div>
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
