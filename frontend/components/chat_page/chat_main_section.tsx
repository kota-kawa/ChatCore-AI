import { memo, useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { ChatMessageList } from "./chat_message_list";
import { ChatRoomSearch } from "./chat_room_search";
import { InlineLoading } from "../ui/inline_loading";
import { Skeleton } from "../ui/skeleton";
import { useHomePageChatContext, useHomePageProjectContext, useHomePageTaskContext, useHomePageUiContext } from "../../contexts/chat_page/home_page_context";
import { MAX_CHAT_MESSAGE_LENGTH, MODEL_OPTIONS } from "../../lib/chat_page/constants";
import {
  CHAT_ATTACHMENT_ACCEPT,
  MAX_ATTACHED_FILES,
  getAttachmentIconClass,
} from "../../lib/chat_page/file_attachments";
import { useChatAttachmentDropzone } from "../../hooks/chat_page/use_chat_attachment_dropzone";
import { extractUrlsFromText, getUrlDomain } from "../../lib/chat_page/url_utils";

// チャット画面の中央ペイン全体（サイドバー・メッセージリスト・入力欄）を管理するコンポーネント。
// Component managing the entire chat center pane: sidebar, message list, and input area.
function ChatMainSectionComponent() {
  // UI 状態（ページビュー、モデル選択メニュー、セットアップフォーム表示など）を Context から取得する。
  // Retrieve UI state (page view, model selection menu, setup form visibility) from context.
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

  const { launchingTaskName, tasks } = useHomePageTaskContext();

  // プロジェクト一覧と操作（サイドバーのプロジェクトセクション用）。
  // Project list and actions for the sidebar's project section.
  const { projects, isProjectsLoading, openProject, openNewProjectModal, assignRoomToProject } = useHomePageProjectContext();

  // チャット操作に関するすべての状態とハンドラーを Context から取得する。
  // Obtain all chat operation state and handlers from context.
  const {
    hasCurrentRoom,
    sidebarOpen,
    chatRooms,
    chatRoomsHasMore,
    isChatRoomsInitialLoading,
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

  // DOM 要素への直接参照。入力欄のフォーカス・高さ調整、ファイル選択ダイアログ、
  // サイドバースクロールセンチネルなどで使用する。
  // Direct DOM refs used for: textarea focus/resize, file picker, sidebar scroll sentinel.
  const chatInputRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const sidebarRef = useRef<HTMLDivElement | null>(null);
  const chatRoomsLoadMoreRef = useRef<HTMLDivElement | null>(null);

  // 未保存チャット・起動中は共有できない。これらの条件をまとめて UI の有効/無効に使う。
  // Sharing is unavailable for temporary rooms or while chat is launching.
  const canShareCurrentRoom = hasCurrentRoom && !isChatLaunching && currentRoomMode !== "temporary";
  const selectedRoomCount = selectedRoomIds.size;
  const hasSelectedRooms = selectedRoomCount > 0;
  // 入力欄が空・文字数超過・起動中・ルーム未選択の場合は送信を禁止する。
  // Block sending when input is empty, over limit, launching, or no room is active.
  const canSendChatMessage =
    hasCurrentRoom &&
    !isChatLaunching &&
    chatInput.trim().length > 0 &&
    chatInput.length <= MAX_CHAT_MESSAGE_LENGTH;

  // 入力テキストに含まれる URL を検出し、AI が参照するページとしてチップ表示する。
  // Detect URLs in the chat input to show as "AI will read" chips before sending.
  const detectedUrls = useMemo(() => extractUrlsFromText(chatInput), [chatInput]);

  // サイドバーのチャット検索クエリ。読み込み済みルームをタイトルで絞り込むために使う。
  // Sidebar chat search query; filters the loaded rooms by title.
  const [roomSearchQuery, setRoomSearchQuery] = useState("");
  const normalizedRoomSearchQuery = roomSearchQuery.trim().toLowerCase();
  const isRoomSearchActive = normalizedRoomSearchQuery.length > 0;

  // クエリに前方一致・部分一致するルームのみを表示する（大文字小文字を無視）。
  // Show only rooms whose title matches the query (case-insensitive substring).
  const filteredChatRooms = useMemo(() => {
    if (!isRoomSearchActive) return chatRooms;
    return chatRooms.filter((room) =>
      (room.title || "新規チャット").toLowerCase().includes(normalizedRoomSearchQuery),
    );
  }, [chatRooms, isRoomSearchActive, normalizedRoomSearchQuery]);

  // 検索中に絞り込み結果が空でも、未読み込みのルームがあれば末尾センチネルで
  // 追加読み込みが走り、全ルームを横断して検索できる。読み込み完了かつ 0 件なら
  // 「該当なし」を表示する。
  // While searching, if the filtered list is empty but more rooms remain unloaded,
  // the bottom sentinel keeps fetching so the search spans all rooms. Show the
  // "no results" state only once everything is loaded and nothing matched.
  const showRoomSearchEmptyState =
    isRoomSearchActive && filteredChatRooms.length === 0 && !chatRoomsHasMore && !isChatRoomsInitialLoading;

  // 添付エラー通知は動的インポートで toast モジュールを遅延読み込みする。
  // Lazy-import the toast module to show attachment error notifications.
  const notifyAttachmentError = useCallback((message: string) => {
    import("../../scripts/core/toast").then(({ showToast }) => {
      showToast(message, { variant: "error" });
    });
  }, []);

  // ドラッグ＆ドロップによるファイル添付機能を提供するフック。
  // Hook providing drag-and-drop file attachment capabilities for the input area.
  const {
    attachSelectedFiles,
    isAttachmentDropActive,
    attachmentDropzoneProps,
  } = useChatAttachmentDropzone({
    attachedFiles,
    setAttachedFiles,
    isAttachmentDisabled: isChatLaunching,
    focusTargetRef: chatInputRef,
    notifyAttachmentError,
  });

  // ファイル選択ダイアログ経由のファイル追加処理。選択後に input の値をリセットして
  // 同じファイルを再度選択できるようにする。
  // Handle files chosen via the file picker dialog; reset input value to allow re-selection.
  const handleFileInputChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const files = event.target.files;
      if (!files || files.length === 0) return;

      attachSelectedFiles(Array.from(files));

      if (event.target) {
        event.target.value = "";
      }
    },
    [attachSelectedFiles],
  );

  // 添付ファイルチップの削除ボタンで特定ファイルを除去する。
  // Remove a specific attached file when its chip remove button is clicked.
  const handleRemoveAttachedFile = useCallback(
    (fileId: string) => {
      setAttachedFiles((prev) => prev.filter((f) => f.id !== fileId));
    },
    [setAttachedFiles],
  );

  // チャットルームカードのキーボード操作（Enter/Space）で選択またはルーム切替を行う。
  // Handle keyboard activation (Enter/Space) on room cards for selection or navigation.
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

  // サイドバーをスクロールしたとき、下端に近づいたら追加のチャットルームを読み込む。
  // Load more chat rooms when the sidebar is scrolled near the bottom (within 160px).
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

  // IntersectionObserver でセンチネル要素の可視性を監視し、サイドバー末尾に
  // 達したときに追加チャットルームを自動読み込みする。
  // Use IntersectionObserver on the sentinel element to auto-load more rooms
  // when the bottom of the sidebar list scrolls into view.
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

  // テキストエリアの高さを内容量に合わせて自動調整する（最大 6 行分）。
  // Auto-resize the chat textarea to fit its content, capped at 6 lines.
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

  // chatInput が変わるたびに入力欄の高さを再計算する。
  // Recalculate textarea height whenever the chat input value changes.
  useEffect(() => {
    adjustChatInputHeight(chatInputRef.current);
  }, [chatInput]);

  // モバイルでテキスト入力欄にフォーカスした際、最新メッセージを画面下端に貼り付け、
  // ヘッダー・入力欄が常に見える状態を保証する。
  // On mobile, re-anchor the message list to the bottom when the textarea is focused
  // so the input area stays visible after the virtual keyboard resizes the viewport.
  const handleChatInputFocus = () => {
    const list = chatMessagesRef.current;
    if (!list) return;
    // visualViewport.resize が走るまでわずかに待ってからスクロール位置を補正する。
    // Wait briefly for visualViewport resize to complete before correcting scroll position.
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
      {/* チャットヘッダー：タスク選択への戻るボタン、モデル選択、共有ボタンを含む */}
      {/* Chat header: back-to-setup button, model selector, and share button */}
      <div className="chat-header">
        <div className="header-left">
          <button
            id="back-to-setup"
            className="icon-button cc-press"
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
          {/* AI モデルをその場で切り替えられるドロップダウンメニュー */}
          {/* Dropdown menu to switch the AI model without leaving the chat */}
          <div
            ref={chatHeaderModelSelectRef}
            className={`chat-header-model-select ${chatHeaderModelMenuOpen ? "is-open" : ""}`.trim()}
          >
            <button
              type="button"
              className="chat-header-model-trigger cc-press"
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
                  className={`chat-header-model-option cc-press ${selectedModel === option.value ? "is-selected" : ""}`.trim()}
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

          {/* 未保存チャットや起動中は共有できないため、状態に応じてツールチップも変える */}
          {/* Share button disabled for temporary rooms or during launch; tooltip reflects reason */}
          <button
            id="share-chat-btn"
            className={`icon-button chat-share-btn cc-press ${canShareCurrentRoom ? "" : "chat-share-btn--disabled"}`.trim()}
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
        {/* チャットルーム一覧サイドバー。選択モード時は一括削除バーを表示する。 */}
        {/* Chat room list sidebar. Shows bulk-delete bar when room selection mode is active. */}
        <div
          ref={sidebarRef}
          className={`sidebar ${sidebarOpen ? "open" : ""}`.trim()}
          id="chat-room-sidebar"
          aria-hidden={sidebarOpen ? "false" : "true"}
          onScroll={handleSidebarScroll}
        >
          {/* プロジェクトセクション。関連チャットをまとめるワークスペース一覧を表示する。 */}
          {/* Projects section: workspaces that group related chats. */}
          {!isRoomSelectionMode && (
            <div className="sidebar-projects">
              <div className="sidebar-projects__header">
                <span className="sidebar-projects__title">
                  <i className="bi bi-folder2" aria-hidden="true"></i> プロジェクト
                </span>
                <button
                  type="button"
                  className="sidebar-projects__add cc-press"
                  aria-label="新規プロジェクトを作成"
                  data-tooltip="新規プロジェクト"
                  data-tooltip-placement="bottom"
                  onClick={() => {
                    openNewProjectModal();
                  }}
                >
                  <i className="bi bi-plus-lg" aria-hidden="true"></i>
                </button>
              </div>
              {projects.length > 0 && (
                <div className="sidebar-projects__list">
                  {projects.map((project) => (
                    <button
                      key={project.id}
                      type="button"
                      className="sidebar-project-card cc-press"
                      onClick={() => {
                        openProject(project.id);
                      }}
                    >
                      <i className="bi bi-folder2-open sidebar-project-card__icon" aria-hidden="true"></i>
                      <span className="sidebar-project-card__name" title={project.name}>
                        {project.name}
                      </span>
                      {typeof project.chatCount === "number" && project.chatCount > 0 && (
                        <span className="sidebar-project-card__count">{project.chatCount}</span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {isRoomSelectionMode ? (
            // 複数選択モード中は選択件数と一括削除ボタンを表示する。
            // In selection mode, show the selection count and bulk-delete controls.
            <div className="room-selection-bar" aria-live="polite">
              <span className="room-selection-bar__count">{selectedRoomCount}件選択中</span>
              <button
                type="button"
                className="room-selection-bar__button room-selection-bar__button--danger cc-press"
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
                className="room-selection-bar__button cc-press"
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
              className="new-chat-btn cc-press"
              onClick={() => {
                handleNewChat();
              }}
            >
              <i className="bi bi-plus-lg"></i> 新規チャット
            </button>
          )}

          {/* チャット検索ボックス。選択モード中は一括操作に集中するため非表示にする。 */}
          {/* Chat search box; hidden during selection mode to keep focus on bulk actions. */}
          {!isRoomSelectionMode && (
            <ChatRoomSearch
              value={roomSearchQuery}
              onChange={setRoomSearchQuery}
              onClear={() => setRoomSearchQuery("")}
            />
          )}

          <div id="chat-room-list" aria-busy={isChatRoomsInitialLoading || isLoadingMoreChatRooms ? "true" : "false"}>
            {isChatRoomsInitialLoading && (
              <div className="chat-room-list__skeleton" role="status" aria-live="polite" aria-label="チャット履歴を読み込み中">
                {Array.from({ length: 6 }).map((_, index) => (
                  <div key={index} className="chat-room-card chat-room-card--skeleton">
                    <Skeleton variant="text" width={index === 0 ? "72%" : "88%"} />
                  </div>
                ))}
              </div>
            )}
            {filteredChatRooms.map((room) => {
              const roomMenuOpen = openRoomActionsFor === room.id;
              // タイトルが空の場合は「新規チャット」をフォールバック表示する。
              // Fall back to "新規チャット" when the room has no title yet.
              const roomTitle = room.title || "新規チャット";
              const roomMenuId = `room-actions-menu-${room.id}`;
              const roomSelected = selectedRoomIds.has(room.id);

              return (
                <div
                  key={room.id}
                  className={`chat-room-card cc-press ${currentRoomId === room.id ? "active" : ""} ${isRoomSelectionMode ? "chat-room-card--selectable" : ""} ${roomSelected ? "chat-room-card--selected" : ""} ${roomMenuOpen ? "chat-room-card--menu-open" : ""}`.trim()}
                  // 選択モード時は checkbox、通常時は button として扱い、アクセシビリティを確保する。
                  // Use checkbox role in selection mode, button role otherwise for accessibility.
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
                    // ルームカード右端の縦三点メニュー。名前変更・複数選択・削除を提供する。
                    // Three-dot context menu on each room card for rename, multi-select, and delete.
                    <div
                      className="chat-room-card-actions"
                      onClick={(event) => {
                        event.stopPropagation();
                      }}
                    >
                      <button
                        type="button"
                        className="room-actions-icon cc-press"
                        aria-label={`${roomTitle} の操作メニューを開く`}
                        aria-haspopup="menu"
                        aria-expanded={roomMenuOpen ? "true" : "false"}
                        aria-controls={roomMenuId}
                        onClick={(event) => {
                          // カードのクリックイベントへの伝播を止めてルーム切替を防ぐ。
                          // Stop propagation to prevent triggering room switch on card click.
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
                          className="menu-item menu-item--rename cc-press"
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
                          className="menu-item menu-item--select cc-press"
                          role="menuitem"
                          onClick={(event) => {
                            event.stopPropagation();
                            enterRoomSelectionMode(room.id);
                          }}
                        >
                          <i className="bi bi-check2-square menu-item__icon"></i> 複数選択
                        </button>

                        {room.mode === "normal" && (
                          <div className="room-actions-menu__section" role="none">
                            <div className="room-actions-menu__label" role="presentation">
                              <i className="bi bi-folder-plus menu-item__icon" aria-hidden="true"></i>
                              プロジェクトへ追加
                            </div>
                            {isProjectsLoading ? (
                              <button
                                type="button"
                                className="menu-item menu-item--project is-disabled"
                                role="menuitem"
                                disabled
                              >
                                読み込み中
                              </button>
                            ) : projects.length > 0 ? (
                              projects.map((project) => (
                                <button
                                  key={project.id}
                                  type="button"
                                  className="menu-item menu-item--project cc-press"
                                  role="menuitem"
                                  title={project.name}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    setOpenRoomActionsFor(null);
                                    void assignRoomToProject(room.id, project.id, project.name);
                                  }}
                                >
                                  <span className="menu-item__project-name">{project.name}</span>
                                </button>
                              ))
                            ) : (
                              <button
                                type="button"
                                className="menu-item menu-item--project cc-press"
                                role="menuitem"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setOpenRoomActionsFor(null);
                                  openNewProjectModal();
                                }}
                              >
                                新規プロジェクトを作成
                              </button>
                            )}
                          </div>
                        )}

                        <button
                          type="button"
                          className="menu-item menu-item--delete cc-press"
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
            {showRoomSearchEmptyState && (
              // 検索クエリに一致するチャットが 1 件も無いことを伝える空状態。
              // Empty state shown when no chat matches the search query.
              <div className="chat-room-search-empty" role="status" aria-live="polite">
                <i className="bi bi-search chat-room-search-empty__icon" aria-hidden="true"></i>
                <span className="chat-room-search-empty__text">「{roomSearchQuery.trim()}」に一致するチャットはありません</span>
              </div>
            )}
            {isRoomSearchActive && filteredChatRooms.length === 0 && chatRoomsHasMore && (
              // 未読み込みのルームを横断検索するため追加読み込み中であることを示す。
              // Indicate that more rooms are being loaded to search across all of them.
              <div className="chat-room-list__loading" role="status" aria-live="polite">
                <InlineLoading label="検索中" />
              </div>
            )}
            {isLoadingMoreChatRooms && (
              <div className="chat-room-list__loading" role="status" aria-live="polite">
                <InlineLoading label="読み込み中" />
              </div>
            )}
            {/* IntersectionObserver がこのセンチネルを監視し、末尾到達時に追加読み込みを発火する。 */}
            {/* IntersectionObserver watches this sentinel to trigger more-room loading on scroll. */}
            <div ref={chatRoomsLoadMoreRef} className="chat-room-list__sentinel" aria-hidden="true" />
          </div>
        </div>

        <div className="chat-area">
          {/* サイドバーの開閉トグルボタン。aria-expanded でアクセシブルに状態を伝える。 */}
          {/* Sidebar toggle button; aria-expanded communicates open/closed state accessibly. */}
          <button
            id="sidebar-toggle"
            className="icon-button sidebar-toggle chat-sidebar-toggle cc-press"
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

          {/* chatMessageListResetKey が変わるとリストをアンマウント/再マウントして初期スクロール位置をリセットする。 */}
          {/* Changing chatMessageListResetKey unmounts and remounts the list to reset scroll position. */}
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
            tasks={tasks}
          />

          {/* 入力コンテナ：ドロップゾーン・URL チップ・添付ファイルチップ・テキストエリア・送信ボタンを含む */}
          {/* Input container: dropzone overlay, URL chips, attachment chips, textarea, send button */}
          <div
            className={`input-container chat-attachment-dropzone supports-[backdrop-filter]:backdrop-blur-xl ${
              isAttachmentDropActive ? "chat-attachment-dropzone--active" : ""
            }`.trim()}
            {...attachmentDropzoneProps}
          >
            {/* ドラッグ中に全面に表示されるドロップ受付オーバーレイ。 */}
            {/* Full-area overlay shown while dragging files over the input zone. */}
            <div className="chat-attachment-drop-overlay" aria-hidden="true">
              <span className="chat-attachment-drop-overlay__icon">
                <i className="bi bi-cloud-arrow-up" aria-hidden="true"></i>
              </span>
              <span className="chat-attachment-drop-overlay__text">ファイルをドロップして添付</span>
              <span className="chat-attachment-drop-overlay__hint">PDF / Office / テキスト</span>
            </div>
            {detectedUrls.length > 0 && (
              // 入力テキストから検出した URL を送信前にチップとして表示し、AI が読み取ることを知らせる。
              // Show chips for detected URLs so users know the AI will fetch them on send.
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
              // 添付済みファイルをチップとして表示し、ファイル名・サイズ・削除ボタンを提供する。
              // Render attached files as chips showing name, size, and a remove button.
              <div className="chat-attached-files">
                {attachedFiles.map((file) => (
                  <div key={file.id} className="chat-attached-file-chip">
                    <i
                      className={`bi ${getAttachmentIconClass(file.name)} chat-attached-file-chip__icon`}
                      aria-hidden="true"
                    ></i>
                    <span className="chat-attached-file-chip__name" title={file.name}>{file.name}</span>
                    {/* ファイルサイズを B / KB / MB で単位自動変換して表示する。 */}
                    {/* Display file size with automatic unit conversion (B / KB / MB). */}
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
              {/* 実際のファイル選択 input は非表示にし、クリップアイコンボタン経由で開く。 */}
              {/* Hidden file input triggered programmatically by the paperclip button. */}
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
                className="chat-attach-btn cc-press"
                aria-label="ファイルを添付"
                data-tooltip="ファイルを添付"
                data-tooltip-placement="top"
                disabled={isChatLaunching || attachedFiles.length >= MAX_ATTACHED_FILES}
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
              {/* 生成中は停止ボタン、それ以外は送信ボタンとして機能する。 */}
              {/* Acts as a stop button while generating, and a send button otherwise. */}
              <button
                type="button"
                id="send-btn"
                className={`cc-press ${isGenerating ? "send-btn--stop" : ""}`.trim()}
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
              // 文字数カウンターを表示し、上限超過時は赤色でエラー状態を知らせる。
              // Show character counter; turns red to warn when the limit is exceeded.
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

// 不要な再レンダリングを防ぐため memo でラップしてエクスポートする。
// Wrap in memo to prevent re-renders when parent re-renders with unchanged props.
export const ChatMainSection = memo(ChatMainSectionComponent);
ChatMainSection.displayName = "ChatMainSection";
