import type { UserSkill } from "../../../lib/chat_page/skill_api";
import { useTranslation } from "../../../contexts/locale_context";
import MarkdownContent from "../../MarkdownContent";
import { ModalCloseButton } from "../../ui/modal_close_button";
import { ModalShell } from "../../ui/modal_shell";

type SkillDetailModalProps = {
  skill: UserSkill | null;
  onClose: () => void;
};

// トップページのSkill本文を確認する閲覧専用モーダル。共通モーダル面（cc-modal）の中サイズで描き、
// 本文は cc-modal__prose で組む。
// Read-only modal for reviewing the full Skill instructions from the home page, drawn on the
// medium shared modal surface (cc-modal); the Markdown body uses cc-modal__prose.
export function SkillDetailModal({ skill, onClose }: SkillDetailModalProps) {
  const { t } = useTranslation();

  return (
    <ModalShell
      isOpen={Boolean(skill)}
      onClose={onClose}
      id="skillDetailModal"
      className="cc-modal skill-detail-modal"
      labelledBy="skill-detail-modal-title"
      initialFocusSelector="[data-close-skill-detail]"
    >
      {skill ? (
        <div className="cc-modal__panel cc-modal__panel--md" tabIndex={-1}>
          <header className="cc-modal__header">
            <div className="cc-modal__heading">
              <h2 className="cc-modal__title" id="skill-detail-modal-title">{skill.name}</h2>
              <p className="cc-modal__lead">{t("home.skillDetailsDescription")}</p>
              <div className="cc-modal__meta" aria-label={t("home.skillDetailsMeta")}>
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
            <ModalCloseButton data-close-skill-detail label={t("chat.closeModal")} onClick={onClose} />
          </header>

          <div className="cc-modal__body">
            <section className="cc-modal__section" aria-labelledby="skill-detail-instructions-title">
              <div className="cc-modal__section-head">
                <h3 className="cc-modal__section-title" id="skill-detail-instructions-title">{t("home.skillInstructions")}</h3>
                <span className="cc-modal__section-meta">
                  {t("home.skillCharacterCount", { count: skill.instructions.length.toLocaleString() })}
                </span>
              </div>
              <MarkdownContent text={skill.instructions} className="cc-modal__prose skill-detail-modal__markdown" />
            </section>
          </div>
        </div>
      ) : null}
    </ModalShell>
  );
}
