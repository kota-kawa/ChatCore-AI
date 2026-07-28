import { useCallback, useEffect, useRef, useState } from "react";

import {
  useHomePageChatContext,
  useHomePageProjectContext,
} from "../../contexts/chat_page/home_page_context";
import { useBodyScrollLock } from "../../hooks/use_body_scroll_lock";
import { useModalFocusTrap } from "../../hooks/use_modal_focus_trap";
import { InlineLoading } from "../ui/inline_loading";
import { ModalCloseButton } from "../ui/modal_close_button";
import { useTranslation } from "../../contexts/locale_context";

// プロジェクト詳細オーバーレイ。指示・所属チャットを管理する。
// Project detail overlay: manage instructions and member chats.
export function ProjectSection() {
  const { locale, t } = useTranslation();
  const {
    activeProjectId,
    activeProjectDetail,
    isProjectDetailLoading,
    isSavingProject,
    closeProject,
    updateProject,
    deleteProject,
    setNewChatProject,
  } = useHomePageProjectContext();
  const { switchChatRoom, handleNewChat } = useHomePageChatContext();

  const modalRef = useRef<HTMLDivElement | null>(null);
  const [name, setName] = useState("");
  const [instructions, setInstructions] = useState("");

  // 詳細が読み込まれたら編集フォームへ反映する。
  // Seed the edit form whenever the loaded detail changes.
  useEffect(() => {
    if (activeProjectDetail) {
      setName(activeProjectDetail.name);
      setInstructions(activeProjectDetail.instructions);
    }
  }, [activeProjectDetail]);

  const isOpen = activeProjectId !== null;

  const getInitialFocus = useCallback(() => {
    return modalRef.current?.querySelector<HTMLElement>("#project-detail-close-btn") ?? null;
  }, []);

  useModalFocusTrap({
    isOpen,
    containerRef: modalRef,
    getInitialFocus,
    onEscape: closeProject,
  });

  useBodyScrollLock(isOpen);

  const handleSaveDetails = useCallback(() => {
    if (activeProjectId === null) return;
    void updateProject(activeProjectId, { name: name.trim() || t("chat.newProject"), instructions });
  }, [activeProjectId, instructions, name, t, updateProject]);

  const handleStartChatInProject = useCallback(() => {
    if (activeProjectId === null) return;
    // 通常の新規チャット状態にリセットしてからプロジェクト紐づけを設定する。
    // Reset to a fresh new-chat state, then set the project association.
    handleNewChat();
    setNewChatProject(activeProjectId);
    closeProject();
  }, [activeProjectId, closeProject, handleNewChat, setNewChatProject]);

  if (!isOpen) return null;

  const detail = activeProjectDetail;
  const hasUnsavedChanges =
    detail !== null && (name !== detail.name || instructions !== detail.instructions);

  return (
    <div
      ref={modalRef}
      className="project-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="project-detail-title"
      tabIndex={-1}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          closeProject();
        }
      }}
    >
      <div className="project-overlay__panel" tabIndex={-1}>
        <header className="project-overlay__header">
          <ModalCloseButton
            id="project-detail-close-btn"
            className="project-overlay__close icon-button cc-press"
            label={t("chat.closeModal")}
            onClick={closeProject}
          />
          <span id="project-detail-title" className="project-overlay__title">
            <i className="bi bi-folder2-open" aria-hidden="true"></i>
            {locale === "en" ? "Project" : "プロジェクト"}
          </span>
          {detail !== null && (
            <button
              type="button"
              className="project-overlay__delete cc-press"
              onClick={() => {
                void deleteProject(detail.id, detail.name);
              }}
            >
              <i className="bi bi-trash" aria-hidden="true"></i>
              <span>{t("common.delete")}</span>
            </button>
          )}
        </header>

        {isProjectDetailLoading && detail === null ? (
          <div className="project-overlay__loading">
            <InlineLoading label={t("common.loading")} />
          </div>
        ) : detail === null ? (
          <div className="project-overlay__loading">{locale === "en" ? "Could not load the project." : "プロジェクトを読み込めませんでした。"}</div>
        ) : (
          <div className="project-overlay__body">
            {/* 基本情報・カスタム指示 / Basic info and custom instructions */}
            <section className="project-section-block">
              <label className="project-field">
                <span className="project-field__label">{t("chat.projectName")}</span>
                <input
                  id="project-name-input"
                  type="text"
                  className="project-field__input"
                  value={name}
                  maxLength={255}
                  onChange={(event) => setName(event.target.value)}
                />
              </label>
              <label className="project-field">
                <span className="project-field__label">{locale === "en" ? "Custom instructions" : "カスタム指示"}</span>
                <textarea
                  className="project-field__textarea"
                  rows={6}
                  maxLength={20000}
                  placeholder={locale === "en" ? "Instructions applied to every chat in this project (tone, role, output format, etc.)" : "このプロジェクト内の全会話に適用される指示（口調・役割・出力形式など）"}
                  value={instructions}
                  onChange={(event) => setInstructions(event.target.value)}
                />
              </label>
              <div className="project-section-block__actions">
                <button
                  type="button"
                  className="primary-button cc-press"
                  disabled={!hasUnsavedChanges || isSavingProject}
                  onClick={handleSaveDetails}
                >
                  {isSavingProject ? t("common.saving") : (locale === "en" ? "Save instructions" : "指示を保存")}
                </button>
              </div>
            </section>

            {/* 所属チャット / Member chats */}
            <section className="project-section-block">
              <div className="project-section-block__heading">
                <h3 className="project-section-block__title">
                  <i className="bi bi-chat-left-text" aria-hidden="true"></i> {t("nav.chat")}
                </h3>
                <button type="button" className="project-newchat-btn cc-press" onClick={handleStartChatInProject}>
                  <i className="bi bi-plus-lg" aria-hidden="true"></i>
                  {locale === "en" ? "New chat in this project" : "このプロジェクトで新規チャット"}
                </button>
              </div>
              {detail.rooms.length === 0 ? (
                <p className="project-chats__empty">{locale === "en" ? "This project has no chats yet." : "このプロジェクトにはまだチャットがありません。"}</p>
              ) : (
                <ul className="project-chats__list">
                  {detail.rooms.map((room) => (
                    <li key={room.id}>
                      <button
                        type="button"
                        className="project-chats__item cc-press"
                        onClick={() => {
                          switchChatRoom(room.id, room.mode);
                          closeProject();
                        }}
                      >
                        <i className="bi bi-chat-dots project-chats__item-icon" aria-hidden="true"></i>
                        <span className="project-chats__item-title">{room.title || t("chat.new")}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
