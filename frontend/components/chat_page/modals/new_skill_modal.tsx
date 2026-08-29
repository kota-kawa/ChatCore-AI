import { useCallback, useRef, type FormEvent } from "react";

import { useModalFocusTrap } from "../../../hooks/use_modal_focus_trap";
import {
  MAX_USER_SKILL_INSTRUCTIONS_LENGTH,
  MAX_USER_SKILL_NAME_LENGTH,
} from "../../../lib/chat_page/skill_api";
import { ModalCloseButton } from "../../ui/modal_close_button";
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
  const { locale, t } = useTranslation();
  const modalRef = useRef<HTMLDivElement | null>(null);

  const getInitialFocus = useCallback(
    () => modalRef.current?.querySelector<HTMLElement>("#new-user-skill-name") ?? modalRef.current,
    [],
  );

  useModalFocusTrap({
    isOpen,
    containerRef: modalRef,
    getInitialFocus,
    onEscape: onClose,
  });

  return (
    <div
      ref={modalRef}
      id="newUserSkillModal"
      className={`skill-modal custom-modal modal-base ${isOpen ? "is-open" : ""}`.trim()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="new-user-skill-modal-title"
      aria-hidden={isOpen ? "false" : "true"}
      tabIndex={-1}
      onClick={(event) => {
        if (event.target === event.currentTarget && !isSaving) onClose();
      }}
    >
      <div className="custom-modal-dialog">
        <div className="custom-modal-content">
          <header className="custom-modal-header">
            <div>
              <p className="task-detail-modal-eyebrow">{locale === "en" ? "PERSONAL SKILL" : "個人Skill"}</p>
              <h2 className="custom-modal-title" id="new-user-skill-modal-title">{t("home.newSkill")}</h2>
            </div>
            <ModalCloseButton
              className="custom-modal-close"
              id="closeNewUserSkillModal"
              label={t("chat.closeModal")}
              onClick={onClose}
            />
          </header>

          <div className="custom-modal-body">
            <form id="newUserSkillForm" className="skill-add-modal__form" onSubmit={onSubmit}>
              <p className="custom-form-text skill-add-modal__lead">{t("home.newSkillDescription")}</p>

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
            </form>
          </div>

          <footer className="custom-modal-footer">
            <button type="button" className="custom-btn-secondary cc-press" onClick={onClose} disabled={isSaving}>
              {t("common.cancel")}
            </button>
            <button type="submit" form="newUserSkillForm" className="primary-button cc-press" disabled={isSaving}>
              {isSaving ? <i className="bi bi-arrow-repeat skill-add-modal__spinner" aria-hidden="true"></i> : <i className="bi bi-plus-lg" aria-hidden="true"></i>}
              <span>{isSaving ? t("home.skillAdding") : t("home.addSkill")}</span>
            </button>
          </footer>
        </div>
      </div>
    </div>
  );
}
