// サイドバーのチャットルーム1件分のカードと操作メニュー（名前変更・ピン留め・複数選択・プロジェクト追加・削除）。chat_main_section.tsx から使われる。
// One chat room card in the sidebar with its action menu (rename, pin, multi-select, add to project, delete); used by chat_main_section.tsx.
import { useRef, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useHomePageChatContext, useHomePageProjectContext } from "../../contexts/chat_page/home_page_context";
import { useTranslation } from "../../contexts/locale_context";
import { useDismissOnEscape } from "../../hooks/use_dismiss_on_escape";
import { useDismissOnOutsidePress } from "../../hooks/use_dismiss_on_outside_press";
import type { ChatRoom } from "../../lib/chat_page/types";

type ChatRoomCardProps = {
  room: ChatRoom;
};

// サイドバーのチャット1件分のカードと操作メニュー。ピン留めと最近の両区画で同じカードを使う。
// One sidebar chat card with its actions menu, shared by the pinned and recent sections.
export function ChatRoomCard({ room }: ChatRoomCardProps) {
  const { locale, t } = useTranslation();
  const english = locale === "en";
  const { projects, isProjectsLoading, openNewProjectModal, assignRoomToProject } = useHomePageProjectContext();
  const {
    currentRoomId,
    openRoomActionsFor,
    isRoomSelectionMode,
    selectedRoomIds,
    switchChatRoom,
    setOpenRoomActionsFor,
    handleRenameRoom,
    handleToggleRoomPin,
    handleDeleteRoom,
    enterRoomSelectionMode,
    toggleRoomSelection,
  } = useHomePageChatContext();

  // チャットルームカードのキーボード操作（Enter/Space）で選択またはルーム切替を行う。
  // Handle keyboard activation (Enter/Space) on room cards for selection or navigation.
  const handleRoomCardKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    if (isRoomSelectionMode) {
      toggleRoomSelection(room.id);
      return;
    }
    switchChatRoom(room.id, room.mode);
  };

  const roomMenuOpen = openRoomActionsFor === room.id;
  // 開いたメニューの外の押下は閉じるだけにする。ほかのルームの「⋮」も外側として扱う
  // A press outside the open menu only closes it; another room's "⋮" counts as outside too
  const actionsRef = useRef<HTMLDivElement | null>(null);
  const actionsTriggerRef = useRef<HTMLButtonElement | null>(null);
  const closeRoomMenu = () => setOpenRoomActionsFor(null);
  useDismissOnOutsidePress(roomMenuOpen, (target) => Boolean(actionsRef.current?.contains(target)), closeRoomMenu);
  // Escape でも閉じて「⋮」へフォーカスを戻す / Escape closes it too and returns focus to the "⋮"
  useDismissOnEscape(roomMenuOpen, closeRoomMenu, actionsTriggerRef);
  // タイトルが空の場合は「新規チャット」をフォールバック表示する。
  // Fall back to "新規チャット" when the room has no title yet.
  const roomTitle = room.title || t("chat.new");
  const roomMenuId = `room-actions-menu-${room.id}`;
  const roomSelected = selectedRoomIds.has(room.id);
  // ピン留めは通常チャットだけが対象で、未保存（temporary）のルームにはメニュー項目を出さない（下の room.mode === "normal" 判定）
  // Only normal chats can be pinned or added to a project; temporary rooms get no such menu items (see the room.mode === "normal" checks below)
  const roomPinned = Boolean(room.pinnedAt);

  return (
    <div
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
        handleRoomCardKeyDown(event);
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
            <span className="chat-room-card__mode-badge">{english ? "Temporary" : "未保存"}</span>
          )}
        </span>
      </div>

      {!isRoomSelectionMode && (
        // ルームカード右端の縦三点メニュー。名前変更・ピン留め・複数選択・削除を提供する。
        // Three-dot context menu on each room card for rename, pin, multi-select, and delete.
        <div
          ref={actionsRef}
          className="chat-room-card-actions"
          onClick={(event) => {
            event.stopPropagation();
          }}
        >
          <button
            ref={actionsTriggerRef}
            type="button"
            className="room-actions-icon cc-press"
            aria-label={english ? `Open actions for ${roomTitle}` : `${roomTitle} の操作メニューを開く`}
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
              <i className="bi bi-pencil-square menu-item__icon"></i> {english ? "Rename" : "名前変更"}
            </button>

            {room.mode === "normal" && (
              <button
                type="button"
                className="menu-item menu-item--pin cc-press"
                role="menuitem"
                onClick={(event) => {
                  event.stopPropagation();
                  void handleToggleRoomPin(room.id, !roomPinned);
                }}
              >
                <i className={`bi ${roomPinned ? "bi-pin-angle-fill" : "bi-pin-angle"} menu-item__icon`}></i>{" "}
                {roomPinned ? (english ? "Unpin" : "ピン留めを外す") : (english ? "Pin" : "ピン留め")}
              </button>
            )}

            <button
              type="button"
              className="menu-item menu-item--select cc-press"
              role="menuitem"
              onClick={(event) => {
                event.stopPropagation();
                enterRoomSelectionMode(room.id);
              }}
            >
              <i className="bi bi-check2-square menu-item__icon"></i> {english ? "Select multiple" : "複数選択"}
            </button>

            {room.mode === "normal" && (
              <div className="room-actions-menu__section" role="none">
                <div className="room-actions-menu__label" role="presentation">
                  <i className="bi bi-folder-plus menu-item__icon" aria-hidden="true"></i>
                  {english ? "Add to project" : "プロジェクトへ追加"}
                </div>
                {isProjectsLoading ? (
                  <button
                    type="button"
                    className="menu-item menu-item--project is-disabled"
                    role="menuitem"
                    disabled
                  >
                    {t("common.loading")}
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
                    {english ? "Create a project" : "新規プロジェクトを作成"}
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
              <i className="bi bi-trash menu-item__icon"></i> {t("common.delete")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
