import type { ChangeEvent, FormEvent } from "react";

import type { EditPromptFormState } from "../../scripts/user/settings/page_types";
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
                <p className="edit-prompt-modal__eyebrow">投稿したプロンプト</p>
                <h2 id="editPromptModalTitle">
                  プロンプトを編集
                </h2>
                <p className="edit-prompt-modal__lead">公開中の内容を更新します。変更は保存後すぐに反映されます。</p>
              </div>
            </div>
            <button
              type="button"
              className="edit-prompt-modal__close"
              aria-label="閉じる"
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
                    <p className="edit-prompt-modal__section-kicker">基本情報</p>
                    <h3 id="editPromptBasicsTitle">見つけやすい情報を整える</h3>
                  </div>
                </div>
                <div className="edit-prompt-modal__grid">
                  <div className="edit-prompt-modal__field">
                    <label htmlFor="editTitle">タイトル <span aria-hidden="true">*</span></label>
                    <p className="edit-prompt-modal__field-help">一覧で表示される名前です。</p>
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
                    <label htmlFor="editCategory">カテゴリ <span aria-hidden="true">*</span></label>
                    <p className="edit-prompt-modal__field-help">探している人に届きやすくなります。</p>
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
                    <p className="edit-prompt-modal__section-kicker">プロンプト本文</p>
                    <h3 id="editPromptContentTitle">AI に伝えたい内容</h3>
                  </div>
                  <span className="edit-prompt-modal__required">必須</span>
                </div>
                <div className="edit-prompt-modal__field">
                  <label htmlFor="editContent" className="sr-only">内容</label>
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

              <section className="edit-prompt-modal__section edit-prompt-modal__section--examples" aria-labelledby="editPromptExamplesTitle">
                <div className="edit-prompt-modal__section-heading">
                  <div>
                    <p className="edit-prompt-modal__section-kicker">入出力例</p>
                    <h3 id="editPromptExamplesTitle">使い方を補足する</h3>
                  </div>
                  <span className="edit-prompt-modal__optional">任意</span>
                </div>
                <div className="edit-prompt-modal__grid">
                  <div className="edit-prompt-modal__field">
                    <label htmlFor="editInputExamples">入力例</label>
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
                    <label htmlFor="editOutputExamples">出力例</label>
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
            </div>

            <footer className="edit-prompt-modal__footer">
              <button
                type="button"
                className="edit-prompt-modal__button edit-prompt-modal__button--secondary"
                onClick={onClose}
                disabled={saving}
              >
                閉じる
              </button>
              <button
                type="submit"
                className="edit-prompt-modal__button edit-prompt-modal__button--primary"
                disabled={saving}
              >
                <i className="bi bi-save" aria-hidden="true"></i>
                {saving ? "保存中..." : "変更を保存"}
              </button>
            </footer>
          </form>
        </div>
      </div>
    </div>
  );
}
