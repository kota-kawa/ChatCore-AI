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
      className={`skill-modal modal-base ${isOpen ? "is-open show" : ""}`.trim()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="new-user-skill-modal-title"
      aria-hidden={isOpen ? "false" : "true"}
      tabIndex={-1}
      onClick={(event) => {
        if (event.target === event.currentTarget && !isSaving) onClose();
      }}
    >
      <div className="skill-modal__content">
        <div className="skill-modal__header">
          <div>
            <p className="skill-modal__eyebrow">{locale === "en" ? "PERSONAL SKILL" : "個人Skill"}</p>
            <h2 id="new-user-skill-modal-title">{t("home.newSkill")}</h2>
          </div>
          <ModalCloseButton
            className="skill-modal__close"
            id="closeNewUserSkillModal"
            label={t("chat.closeModal")}
            onClick={onClose}
          />
        </div>

        <p className="skill-modal__lead">{t("home.newSkillDescription")}</p>

        <form className="skill-modal__form" onSubmit={onSubmit}>
          <div className="skill-modal__field">
            <label htmlFor="new-user-skill-name">{t("home.skillName")}</label>
            <input
              id="new-user-skill-name"
              type="text"
              required
              maxLength={MAX_USER_SKILL_NAME_LENGTH}
              autoComplete="off"
              placeholder={t("home.skillNamePlaceholder")}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>

          <div className="skill-modal__field">
            <label htmlFor="new-user-skill-instructions">{t("home.skillInstructions")}</label>
            <textarea
              id="new-user-skill-instructions"
              required
              rows={7}
              maxLength={MAX_USER_SKILL_INSTRUCTIONS_LENGTH}
              placeholder={t("home.skillInstructionsPlaceholder")}
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
            />
            <span className="skill-modal__counter">
              {instructions.length.toLocaleString()} / {MAX_USER_SKILL_INSTRUCTIONS_LENGTH.toLocaleString()}
            </span>
          </div>

          <p className="skill-modal__hint">{t("home.skillModalHint")}</p>

          <div className="skill-modal__actions">
            <button type="button" className="skill-modal__cancel" onClick={onClose} disabled={isSaving}>
              {t("common.cancel")}
            </button>
            <button type="submit" className="primary-button skill-modal__submit" disabled={isSaving}>
              {isSaving ? <i className="bi bi-arrow-repeat skill-modal__spinner" aria-hidden="true"></i> : <i className="bi bi-plus-lg" aria-hidden="true"></i>}
              <span>{isSaving ? t("home.skillAdding") : t("home.addSkill")}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
