import { useCallback, useEffect, useRef, useState } from "react";

import { useModalFocusTrap } from "../../../hooks/use_modal_focus_trap";
import { useHomePageProjectContext } from "../../../contexts/chat_page/home_page_context";
import { ModalCloseButton } from "../../ui/modal_close_button";
import { useTranslation } from "../../../contexts/locale_context";

const MAX_PROJECT_NAME_LENGTH = 255;
const MAX_PROJECT_INSTRUCTIONS_LENGTH = 20000;

// 新規プロジェクト作成モーダル。名前と（任意の）カスタム指示を入力する。
// New-project modal: enter a name and optional custom instructions.
export function NewProjectModal() {
  const { locale, t } = useTranslation();
  const {
    isProjectModalOpen,
    isSavingProject,
    createProject,
    closeNewProjectModal,
  } = useHomePageProjectContext();

  const modalRef = useRef<HTMLDivElement | null>(null);
  const [name, setName] = useState("");
  const [instructions, setInstructions] = useState("");

  // モーダルを開くたびに入力欄をリセットする。
  // Reset the fields each time the modal opens.
  useEffect(() => {
    if (isProjectModalOpen) {
      setName("");
      setInstructions("");
    }
  }, [isProjectModalOpen]);

  const getInitialFocus = useCallback(() => {
    return modalRef.current?.querySelector<HTMLElement>("#new-project-name-input") ?? null;
  }, []);

  useModalFocusTrap({
    isOpen: isProjectModalOpen,
    containerRef: modalRef,
    getInitialFocus,
    onEscape: closeNewProjectModal,
  });

  const canSubmit = name.trim().length > 0 && !isSavingProject;

  const handleSubmit = useCallback(() => {
    if (!canSubmit) return;
    void createProject(name.trim(), instructions);
  }, [canSubmit, createProject, instructions, name]);

  return (
    <div
      ref={modalRef}
      id="new-project-modal"
      className={`new-project-modal modal-base ${isProjectModalOpen ? "is-open" : ""}`.trim()}
      role="dialog"
      aria-modal="true"
      aria-hidden={isProjectModalOpen ? "false" : "true"}
      aria-labelledby="new-project-title"
      tabIndex={-1}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          closeNewProjectModal();
        }
      }}
    >
      <div className="new-project-modal__content" tabIndex={-1}>
        <ModalCloseButton
          id="new-project-close-btn"
          className="new-project-modal__close"
          label={t("chat.closeModal")}
          onClick={closeNewProjectModal}
        />

        <header className="new-project-modal__header">
          <h2 id="new-project-title">{t("chat.newProject")}</h2>
          <p className="new-project-modal__desc">
            {locale === "en" ? "Group related chats and apply shared custom instructions." : "関連するチャットをまとめ、共有のカスタム指示を設定できます。"}
          </p>
        </header>

        <div className="new-project-modal__body">
          <label className="new-project-field">
            <span className="new-project-field__label">{t("chat.projectName")}</span>
            <input
              id="new-project-name-input"
              type="text"
              className="new-project-field__input"
              placeholder={locale === "en" ? "For example: Product research" : "例: 新製品リサーチ"}
              maxLength={MAX_PROJECT_NAME_LENGTH}
              value={name}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  handleSubmit();
                }
              }}
            />
          </label>

          <label className="new-project-field">
            <span className="new-project-field__label">{locale === "en" ? "Custom instructions (optional)" : "カスタム指示（任意）"}</span>
            <textarea
              id="new-project-instructions-input"
              className="new-project-field__textarea"
              placeholder={locale === "en" ? "Instructions applied to every chat in this project (tone, role, output format, etc.)" : "このプロジェクト内の全会話に適用される指示（口調・役割・出力形式など）"}
              rows={5}
              maxLength={MAX_PROJECT_INSTRUCTIONS_LENGTH}
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
            />
          </label>
        </div>

        <div className="new-project-modal__actions">
          <button
            type="button"
            className="new-project-modal__cancel cc-press"
            onClick={closeNewProjectModal}
            disabled={isSavingProject}
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="primary-button new-project-modal__submit cc-press"
            onClick={handleSubmit}
            disabled={!canSubmit}
          >
            {isSavingProject ? t("common.saving") : t("chat.create")}
          </button>
        </div>
      </div>
    </div>
  );
}
