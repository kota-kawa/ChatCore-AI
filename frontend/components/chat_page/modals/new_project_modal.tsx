import { useCallback, useEffect, useState } from "react";

import { useHomePageProjectContext } from "../../../contexts/chat_page/home_page_context";
import { ModalCloseButton } from "../../ui/modal_close_button";
import { ModalShell } from "../../ui/modal_shell";
import { useTranslation } from "../../../contexts/locale_context";

const MAX_PROJECT_NAME_LENGTH = 255;
const MAX_PROJECT_INSTRUCTIONS_LENGTH = 20000;

// 新規プロジェクト作成モーダル。名前と（任意の）カスタム指示を入力する。
// 共通モーダル面（cc-modal）の小サイズで描く。
// New-project modal: enter a name and optional custom instructions,
// drawn on the small shared modal surface (cc-modal).
export function NewProjectModal() {
  const { locale, t } = useTranslation();
  const {
    isProjectModalOpen,
    isSavingProject,
    createProject,
    closeNewProjectModal,
  } = useHomePageProjectContext();

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

  const canSubmit = name.trim().length > 0 && !isSavingProject;

  const handleSubmit = useCallback(() => {
    if (!canSubmit) return;
    void createProject(name.trim(), instructions);
  }, [canSubmit, createProject, instructions, name]);

  return (
    <ModalShell
      isOpen={isProjectModalOpen}
      onClose={closeNewProjectModal}
      id="new-project-modal"
      className="cc-modal new-project-modal"
      labelledBy="new-project-title"
      dismissDisabled={isSavingProject}
      initialFocusSelector="#new-project-name-input"
    >
      <div className="cc-modal__panel cc-modal__panel--sm" tabIndex={-1}>
        <header className="cc-modal__header">
          <div className="cc-modal__heading">
            <h2 className="cc-modal__title" id="new-project-title">{t("chat.newProject")}</h2>
            <p className="cc-modal__lead">
              {locale === "en" ? "Group related chats and apply shared custom instructions." : "関連するチャットをまとめ、共有のカスタム指示を設定できます。"}
            </p>
          </div>
          <ModalCloseButton
            id="new-project-close-btn"
            label={t("chat.closeModal")}
            onClick={closeNewProjectModal}
            disabled={isSavingProject}
          />
        </header>

        <div className="cc-modal__body new-project-modal__body">
          <label className="project-field">
            <span className="project-field__label">{t("chat.projectName")}</span>
            <input
              id="new-project-name-input"
              type="text"
              className="project-field__input"
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

          <label className="project-field">
            <span className="project-field__label">{locale === "en" ? "Custom instructions (optional)" : "カスタム指示（任意）"}</span>
            <textarea
              id="new-project-instructions-input"
              className="project-field__textarea"
              placeholder={locale === "en" ? "Instructions applied to every chat in this project (tone, role, output format, etc.)" : "このプロジェクト内の全会話に適用される指示（口調・役割・出力形式など）"}
              rows={5}
              maxLength={MAX_PROJECT_INSTRUCTIONS_LENGTH}
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
            />
          </label>
        </div>

        <footer className="cc-modal__footer">
          <button
            type="button"
            className="cc-modal__btn"
            onClick={closeNewProjectModal}
            disabled={isSavingProject}
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="cc-modal__btn cc-modal__btn--primary"
            onClick={handleSubmit}
            disabled={!canSubmit}
          >
            {isSavingProject ? t("common.saving") : t("chat.create")}
          </button>
        </footer>
      </div>
    </ModalShell>
  );
}
