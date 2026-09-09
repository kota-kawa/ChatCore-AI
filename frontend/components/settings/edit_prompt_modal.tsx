import type { ChangeEvent, FormEvent, MutableRefObject } from "react";

import type { EditPromptFormState } from "../../scripts/user/settings/page_types";
import { useTranslation } from "../../contexts/locale_context";
import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";
import { PromptCategorySelect } from "./prompt_category_select";

// プロンプト編集用のモーダルダイアログ — 保存中は全フォームを無効化する
// 共通モーダル面（cc-modal）で描き、設定画面とプロンプト共有画面の両方から使う。
// Modal dialog for editing a prompt — disables all form controls while saving.
// Drawn on the shared modal surface (cc-modal) and used by both the settings and prompt share pages.
export function EditPromptModal({
  formState,
  saving,
  onClose,
  onCategoryChange,
  onChange,
  onSubmit,
  modalRef,
  className
}: {
  formState: EditPromptFormState;
  saving: boolean;
  onClose: () => void;
  onCategoryChange: (value: string) => void;
  onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  modalRef?: MutableRefObject<HTMLDivElement | null>;
  // 呼び出し元ページのスコープ用クラス（配色の差し替えなど） / Page-scope classes from the caller (e.g. accent palette)
  className?: string;
}) {
  const { t, locale } = useTranslation();
  const isSkill = formState.contentFormat === "skill";
  const showExamples = !isSkill && formState.mediaType === "text";
  return (
    <ModalShell
      isOpen
      onClose={onClose}
      id="editModal"
      className={`cc-modal edit-prompt-modal${className ? ` ${className}` : ""}`}
      labelledBy="editPromptModalTitle"
      overlayRef={modalRef}
      dismissDisabled={saving}
      initialFocusSelector="#editTitle"
    >
      <div className="cc-modal__panel cc-modal__panel--lg edit-prompt-modal__dialog" tabIndex={-1}>
        <header className="cc-modal__header edit-prompt-modal__header">
          <div className="cc-modal__heading">
            <h2 className="cc-modal__title" id="editPromptModalTitle">
              {locale === "en" ? "Edit prompt" : "プロンプトを編集"}
            </h2>
            <p className="cc-modal__lead edit-prompt-modal__lead">{t("promptShare.editLead")}</p>
          </div>
          <ModalCloseButton label={t("common.close")} onClick={onClose} disabled={saving} />
        </header>

          <form id="editForm" className="cc-modal__form edit-prompt-modal__form" onSubmit={onSubmit}>
            <div className="cc-modal__body edit-prompt-modal__body">
              {/* 編集対象のプロンプト ID を hidden フィールドで保持する / Hold the target prompt ID in a hidden field for form submission */}
              <input type="hidden" id="editPromptId" value={formState.id} readOnly />

              <section className="cc-modal__section edit-prompt-modal__section" aria-labelledby="editPromptBasicsTitle">
                <div className="cc-modal__section-head">
                  <h3 className="cc-modal__section-title" id="editPromptBasicsTitle">{t("promptShare.basicInfo")}</h3>
                  <span className="cc-modal__section-meta">{t("promptShare.improveDiscovery")}</span>
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
                <div className="edit-prompt-modal__field">
                  <label htmlFor="editDescription">{t("promptShare.descriptionLabel")}</label>
                  <p className="edit-prompt-modal__field-help">{t("promptShare.descriptionPlaceholder")}</p>
                  <textarea
                    className="edit-prompt-modal__input edit-prompt-modal__textarea"
                    id="editDescription"
                    name="description"
                    rows={3}
                    maxLength={300}
                    value={formState.description}
                    onChange={onChange}
                    disabled={saving}
                  ></textarea>
                </div>
              </section>

              <section className="cc-modal__section edit-prompt-modal__section" aria-labelledby="editPromptContentTitle">
                <div className="cc-modal__section-head">
                  <h3 className="cc-modal__section-title" id="editPromptContentTitle">
                    {isSkill
                      ? (locale === "en" ? "SKILL definition" : "SKILL 定義")
                      : t("promptShare.body")}
                  </h3>
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
              <section className="cc-modal__section edit-prompt-modal__section edit-prompt-modal__section--examples" aria-labelledby="editPromptExamplesTitle">
                <div className="cc-modal__section-head">
                  <h3 className="cc-modal__section-title" id="editPromptExamplesTitle">{t("promptShare.examples")}</h3>
                  <span className="cc-modal__section-meta">{t("promptShare.examplesHelp")}</span>
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

            <footer className="cc-modal__footer edit-prompt-modal__footer">
              <button
                type="button"
                className="cc-modal__btn edit-prompt-modal__button edit-prompt-modal__button--secondary"
                onClick={onClose}
                disabled={saving}
              >
                {t("common.close")}
              </button>
              <button
                type="submit"
                className="cc-modal__btn cc-modal__btn--primary edit-prompt-modal__button edit-prompt-modal__button--primary"
                disabled={saving}
              >
                {saving ? t("common.saving") : t("settings.saveChanges")}
              </button>
            </footer>
          </form>
      </div>
    </ModalShell>
  );
}
