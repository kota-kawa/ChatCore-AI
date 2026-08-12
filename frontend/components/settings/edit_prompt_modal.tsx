import type { ChangeEvent, FormEvent } from "react";

import type { EditPromptFormState } from "../../scripts/user/settings/page_types";
import { useTranslation } from "../../contexts/locale_context";
import { PromptCategorySelect } from "./prompt_category_select";

// プロンプト編集用のモーダルダイアログ — 保存中は全フォームを無効化する
// Modal dialog for editing a prompt — disables all form controls while saving
export function EditPromptModal({
  formState,
  saving,
  onClose,
  onCategoryChange,
  onChange,
  onSubmit
}: {
  formState: EditPromptFormState;
  saving: boolean;
  onClose: () => void;
  onCategoryChange: (value: string) => void;
  onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const { t, locale } = useTranslation();
  const isSkill = formState.contentFormat === "skill";
  const showExamples = !isSkill && formState.mediaType === "text";
  return (
    <div
      id="editModal"
      className="edit-prompt-modal"
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-labelledby="editPromptModalTitle"
      onClick={(event) => {
        // モーダル背景クリックでも閉じられるが、保存中は誤操作を防ぐためブロックする
        // Allow closing by clicking the backdrop, but block it during save to prevent accidental dismissal
        if (event.target === event.currentTarget && !saving) {
          onClose();
        }
      }}
    >
      <div className="edit-prompt-modal__dialog" role="document">
        <div className="edit-prompt-modal__surface">
          <header className="edit-prompt-modal__header">
            <div className="edit-prompt-modal__heading">
              <span className="edit-prompt-modal__icon" aria-hidden="true">
                <i className="bi bi-pencil-square"></i>
              </span>
              <div>
                <p className="edit-prompt-modal__eyebrow">{t("settings.prompts")}</p>
                <h2 id="editPromptModalTitle">
                  {locale === "en" ? "Edit prompt" : "プロンプトを編集"}
                </h2>
                <p className="edit-prompt-modal__lead">{t("promptShare.editLead")}</p>
              </div>
            </div>
            <button
              type="button"
              className="edit-prompt-modal__close"
              aria-label={t("common.close")}
              onClick={onClose}
              disabled={saving}
            >
              <i className="bi bi-x-lg" aria-hidden="true"></i>
            </button>
          </header>

          <form id="editForm" className="edit-prompt-modal__form" onSubmit={onSubmit}>
            <div className="edit-prompt-modal__body">
              {/* 編集対象のプロンプト ID を hidden フィールドで保持する / Hold the target prompt ID in a hidden field for form submission */}
              <input type="hidden" id="editPromptId" value={formState.id} readOnly />

              <section className="edit-prompt-modal__section" aria-labelledby="editPromptBasicsTitle">
                <div className="edit-prompt-modal__section-heading">
                  <div>
                    <p className="edit-prompt-modal__section-kicker">{t("promptShare.basicInfo")}</p>
                    <h3 id="editPromptBasicsTitle">{t("promptShare.improveDiscovery")}</h3>
                  </div>
                </div>
                <div className="edit-prompt-modal__grid">
                  <div className="edit-prompt-modal__field">
                    <label htmlFor="editTitle">{t("promptShare.titleLabel")} <span aria-hidden="true">*</span></label>
                    <p className="edit-prompt-modal__field-help">{t("promptShare.titleHelp")}</p>
                    <input
                      type="text"
                      className="edit-prompt-modal__input"
                      id="editTitle"
                      name="title"
                      required
                      value={formState.title}
                      onChange={onChange}
                      disabled={saving}
                    />
                  </div>

                  <div className="edit-prompt-modal__field">
                    <label htmlFor="editCategory">{t("promptShare.category")} <span>{t("common.optional")}</span></label>
                    <p className="edit-prompt-modal__field-help">{t("promptShare.categoryHelp")}</p>
                    <PromptCategorySelect
                      selectId="editCategory"
                      value={formState.category}
                      disabled={saving}
                      onChange={onCategoryChange}
                    />
                  </div>
                </div>
              </section>

              <section className="edit-prompt-modal__section" aria-labelledby="editPromptContentTitle">
                <div className="edit-prompt-modal__section-heading">
                  <div>
                    <p className="edit-prompt-modal__section-kicker">{t("promptShare.body")}</p>
                    <h3 id="editPromptContentTitle">
                      {isSkill
                        ? (locale === "en" ? "SKILL definition" : "SKILL 定義")
                        : (locale === "en" ? "Instructions for AI" : "AI に伝えたい内容")}
                    </h3>
                  </div>
                  <span className="edit-prompt-modal__required">{t("settings.required")}</span>
                </div>
                <div className="edit-prompt-modal__field">
                  <label htmlFor="editContent" className="sr-only">{t("promptShare.contentLabel")}</label>
                  <textarea
                    className="edit-prompt-modal__input edit-prompt-modal__textarea edit-prompt-modal__textarea--content"
                    id="editContent"
                    name="content"
                    rows={5}
                    required
                    value={formState.content}
                    onChange={onChange}
                    disabled={saving}
                  ></textarea>
                </div>
              </section>

              {showExamples ? (
              <section className="edit-prompt-modal__section edit-prompt-modal__section--examples" aria-labelledby="editPromptExamplesTitle">
                <div className="edit-prompt-modal__section-heading">
                  <div>
                    <p className="edit-prompt-modal__section-kicker">{t("promptShare.examples")}</p>
                    <h3 id="editPromptExamplesTitle">{t("promptShare.examplesHelp")}</h3>
                  </div>
                  <span className="edit-prompt-modal__optional">{t("common.optional")}</span>
                </div>
                <div className="edit-prompt-modal__grid">
                  <div className="edit-prompt-modal__field">
                    <label htmlFor="editInputExamples">{t("promptShare.inputExample")}</label>
                    <textarea
                      className="edit-prompt-modal__input edit-prompt-modal__textarea"
                      id="editInputExamples"
                      name="inputExamples"
                      rows={3}
                      value={formState.inputExamples}
                      onChange={onChange}
                      disabled={saving}
                    ></textarea>
                  </div>

                  <div className="edit-prompt-modal__field">
                    <label htmlFor="editOutputExamples">{t("promptShare.outputExample")}</label>
                    <textarea
                      className="edit-prompt-modal__input edit-prompt-modal__textarea"
                      id="editOutputExamples"
                      name="outputExamples"
                      rows={3}
                      value={formState.outputExamples}
                      onChange={onChange}
                      disabled={saving}
                    ></textarea>
                  </div>
                </div>
              </section>
              ) : null}
            </div>

            <footer className="edit-prompt-modal__footer">
              <button
                type="button"
                className="edit-prompt-modal__button edit-prompt-modal__button--secondary"
                onClick={onClose}
                disabled={saving}
              >
                {t("common.close")}
              </button>
              <button
                type="submit"
                className="edit-prompt-modal__button edit-prompt-modal__button--primary"
                disabled={saving}
              >
                <i className="bi bi-save" aria-hidden="true"></i>
                {saving ? t("common.saving") : t("settings.saveChanges")}
              </button>
            </footer>
          </form>
        </div>
      </div>
    </div>
  );
}
