import { type FormEvent } from "react";

import {
  MAX_USER_SKILL_INSTRUCTIONS_LENGTH,
  MAX_USER_SKILL_NAME_LENGTH,
} from "../../../lib/chat_page/skill_api";
import { ModalCloseButton } from "../../ui/modal_close_button";
import { ModalShell } from "../../ui/modal_shell";
import { useTranslation } from "../../../contexts/locale_context";

type NewSkillModalProps = {
  isOpen: boolean;
  isSaving: boolean;
  name: string;
  instructions: string;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  setName: (value: string) => void;
  setInstructions: (value: string) => void;
};

// 個人Skillを追加するモーダル。共通モーダル面（cc-modal）の中サイズで描き、
// フォーム部品はタスク編集と同じ custom-form-* を使う。
// Modal for adding a personal Skill, drawn on the medium shared modal surface (cc-modal);
// the form controls reuse the custom-form-* primitives shared with task editing.
export function NewSkillModal({
  isOpen,
  isSaving,
  name,
  instructions,
  onClose,
  onSubmit,
  setName,
  setInstructions,
}: NewSkillModalProps) {
  const { t } = useTranslation();

  return (
    <ModalShell
      isOpen={isOpen}
      onClose={onClose}
      id="newUserSkillModal"
      className="cc-modal skill-modal"
      labelledBy="new-user-skill-modal-title"
      dismissDisabled={isSaving}
      initialFocusSelector="#new-user-skill-name"
    >
      <div className="cc-modal__panel cc-modal__panel--md" tabIndex={-1}>
        <header className="cc-modal__header">
          <div className="cc-modal__heading">
            <h2 className="cc-modal__title" id="new-user-skill-modal-title">{t("home.newSkill")}</h2>
            <p className="cc-modal__lead">{t("home.newSkillDescription")}</p>
          </div>
          <ModalCloseButton
            id="closeNewUserSkillModal"
            label={t("chat.closeModal")}
            onClick={onClose}
            disabled={isSaving}
          />
        </header>

        <form id="newUserSkillForm" className="cc-modal__form skill-add-modal__form" onSubmit={onSubmit}>
          <div className="cc-modal__body">
            <div className="custom-form-group">
              <label className="custom-form-label" htmlFor="new-user-skill-name">{t("home.skillName")}</label>
              <input
                id="new-user-skill-name"
                className="custom-form-control"
                type="text"
                required
                maxLength={MAX_USER_SKILL_NAME_LENGTH}
                autoComplete="off"
                placeholder={t("home.skillNamePlaceholder")}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </div>

            <div className="custom-form-group">
              <label className="custom-form-label" htmlFor="new-user-skill-instructions">{t("home.skillInstructions")}</label>
              <textarea
                id="new-user-skill-instructions"
                className="custom-form-control"
                required
                rows={7}
                maxLength={MAX_USER_SKILL_INSTRUCTIONS_LENGTH}
                placeholder={t("home.skillInstructionsPlaceholder")}
                value={instructions}
                onChange={(event) => setInstructions(event.target.value)}
              />
              <span className="skill-add-modal__counter">
                {instructions.length.toLocaleString()} / {MAX_USER_SKILL_INSTRUCTIONS_LENGTH.toLocaleString()}
              </span>
            </div>

            <p className="custom-form-text skill-add-modal__hint">{t("home.skillModalHint")}</p>
          </div>

          <footer className="cc-modal__footer">
            <button type="button" className="cc-modal__btn" onClick={onClose} disabled={isSaving}>
              {t("common.cancel")}
            </button>
            <button type="submit" className="cc-modal__btn cc-modal__btn--primary" disabled={isSaving}>
              {isSaving ? <i className="bi bi-arrow-repeat skill-add-modal__spinner" aria-hidden="true"></i> : <i className="bi bi-plus-lg" aria-hidden="true"></i>}
              <span>{isSaving ? t("home.skillAdding") : t("home.addSkill")}</span>
            </button>
          </footer>
        </form>
      </div>
    </ModalShell>
  );
}
