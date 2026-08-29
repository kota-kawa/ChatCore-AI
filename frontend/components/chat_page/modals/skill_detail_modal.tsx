import { useCallback, useRef } from "react";

import { useModalFocusTrap } from "../../../hooks/use_modal_focus_trap";
import type { UserSkill } from "../../../lib/chat_page/skill_api";
import { useTranslation } from "../../../contexts/locale_context";
import { ModalCloseButton } from "../../ui/modal_close_button";

type SkillDetailModalProps = {
  skill: UserSkill | null;
  onClose: () => void;
};

// トップページのSkill本文を確認する閲覧専用モーダル
// Read-only modal for reviewing the full Skill instructions from the home page
export function SkillDetailModal({ skill, onClose }: SkillDetailModalProps) {
  const { t } = useTranslation();
  const modalRef = useRef<HTMLDivElement | null>(null);
  const isOpen = Boolean(skill);

  const getInitialFocus = useCallback(() => {
    return modalRef.current?.querySelector<HTMLElement>("[data-close-skill-detail]") ?? null;
  }, []);

  useModalFocusTrap({
    isOpen,
    containerRef: modalRef,
    getInitialFocus,
    onEscape: onClose,
  });

  return (
    <div
      ref={modalRef}
      id="skillDetailModal"
      className={`skill-detail-modal custom-modal modal-base ${isOpen ? "is-open" : ""}`.trim()}
      role="dialog"
      aria-modal="true"
      aria-hidden={isOpen ? "false" : "true"}
      aria-labelledby="skill-detail-modal-title"
      tabIndex={-1}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      {skill ? (
        <div className="custom-modal-dialog">
          <div className="custom-modal-content">
            <header className="custom-modal-header skill-detail-modal__header">
              <div className="skill-detail-modal__heading">
                <p className="task-detail-modal-eyebrow">
                  {skill.is_default ? t("home.skillDefault") : t("home.skillDetails")}
                </p>
                <h2 className="custom-modal-title" id="skill-detail-modal-title">{skill.name}</h2>
                <div className="skill-detail-modal__meta" aria-label={t("home.skillDetailsMeta")}>
                  <span>
                    <i className={`bi ${skill.is_enabled ? "bi-toggle-on" : "bi-toggle-off"}`} aria-hidden="true"></i>
                    {skill.is_enabled ? t("home.skillOn") : t("home.skillOff")}
                  </span>
                  {skill.is_default ? (
                    <span>
                      <i className="bi bi-lock-fill" aria-hidden="true"></i>
                      {t("home.skillDefault")}
                    </span>
                  ) : null}
                </div>
              </div>
              <ModalCloseButton
                className="custom-modal-close"
                data-close-skill-detail
                label={t("chat.closeModal")}
                onClick={onClose}
              />
            </header>

            <div className="custom-modal-body skill-detail-modal__body">
              <p className="custom-form-text skill-detail-modal__lead">{t("home.skillDetailsDescription")}</p>

              <section className="task-detail-section" aria-labelledby="skill-detail-instructions-title">
                <div className="skill-detail-modal__section-heading">
                  <h3 className="task-detail-section-title" id="skill-detail-instructions-title">{t("home.skillInstructions")}</h3>
                  <span>{t("home.skillCharacterCount", { count: skill.instructions.length.toLocaleString() })}</span>
                </div>
                <pre className="task-detail-section-body skill-detail-modal__instructions">{skill.instructions}</pre>
              </section>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
