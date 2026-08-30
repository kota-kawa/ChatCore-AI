import { useCallback, type FormEvent, type MutableRefObject } from "react";

import type { PromptStatus } from "../../../lib/chat_page/types";
import { ModalCloseButton } from "../../ui/modal_close_button";
import { ModalShell } from "../../ui/modal_shell";
import { useTranslation } from "../../../contexts/locale_context";

// 新規プロンプト作成モーダルのprops型定義
// Props type definition for the new prompt creation modal
type NewPromptModalProps = {
  isOpen: boolean;
  isPromptSubmitting: boolean;
  guardrailEnabled: boolean;
  newPromptTitle: string;
  newPromptContent: string;
  newPromptInputExample: string;
  newPromptOutputExample: string;
  newPromptStatus: PromptStatus;
  titleInputRef: MutableRefObject<HTMLInputElement | null>;
  contentInputRef: MutableRefObject<HTMLTextAreaElement | null>;
  inputExampleRef: MutableRefObject<HTMLTextAreaElement | null>;
  outputExampleRef: MutableRefObject<HTMLTextAreaElement | null>;
  newPromptAssistRootRef: MutableRefObject<HTMLDivElement | null>;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  setGuardrailEnabled: (enabled: boolean) => void;
  setNewPromptTitle: (value: string) => void;
  setNewPromptContent: (value: string) => void;
  setNewPromptInputExample: (value: string) => void;
  setNewPromptOutputExample: (value: string) => void;
};

// 新しいプロンプトを作成して投稿するためのモーダルコンポーネント
// Modal component for creating and submitting a new prompt
export function NewPromptModal({
  isOpen,
  isPromptSubmitting,
  guardrailEnabled,
  newPromptTitle,
  newPromptContent,
  newPromptInputExample,
  newPromptOutputExample,
  newPromptStatus,
  titleInputRef,
  contentInputRef,
  inputExampleRef,
  outputExampleRef,
  newPromptAssistRootRef,
  onClose,
  onSubmit,
  setGuardrailEnabled,
  setNewPromptTitle,
  setNewPromptContent,
  setNewPromptInputExample,
  setNewPromptOutputExample,
}: NewPromptModalProps) {
  const { locale, t } = useTranslation();

  // 初期フォーカスをタイトル入力欄に設定する（null のときはフォーカストラップが
  // 最初のフォーカス可能要素へフォールバックする）
  // Set initial focus to the title input (the focus trap falls back to the first
  // focusable element when this returns null)
  const getInitialFocus = useCallback(() => titleInputRef.current, [titleInputRef]);

  return (
    <ModalShell
      isOpen={isOpen}
      onClose={onClose}
      id="newPromptModal"
      className="new-prompt-modal"
      labelledBy="new-prompt-modal-title"
      dismissDisabled={isPromptSubmitting}
      getInitialFocus={getInitialFocus}
    >
      <div className="new-prompt-modal-content">
        <ModalCloseButton
          className="new-modal-close-btn"
          id="newModalCloseBtn"
          label={t("chat.closeModal")}
          onClick={() => {
            if (isPromptSubmitting) return;
            onClose();
          }}
        />

        <div className="new-prompt-modal-body">
          {/* モーダルのヘッダー（説明文付き）/ Modal header with description */}
          <div className="new-prompt-modal__hero">
            <div className="new-prompt-modal__hero-copy">
              <p className="new-prompt-modal__eyebrow">{locale === "en" ? "CREATE A PROMPT" : "プロンプト作成"}</p>
              <h2 id="new-prompt-modal-title">{t("chat.newPrompt")}</h2>
              <p className="new-prompt-modal__lead">{locale === "en" ? "Add a title and instructions, or use AI assistance to prepare a draft." : "タイトルと内容を書いて投稿します。下のAI補助で下書きを作ることもできます。"}</p>
            </div>
            <div className="new-prompt-modal__hero-badges" aria-hidden="true">
              <span>{locale === "en" ? "Draft" : "下書き"}</span>
              <span>{locale === "en" ? "Edit" : "編集"}</span>
              <span>{locale === "en" ? "Post" : "投稿"}</span>
            </div>
          </div>

          {/* プロンプト作成フォーム / Prompt creation form */}
          <form
            className="new-post-form"
            id="newPostForm"
            onSubmit={(event) => {
              onSubmit(event);
            }}
          >
          <div className="form-group">
            <label htmlFor="new-prompt-title">{t("chat.promptTitle")}</label>
            <input
              ref={titleInputRef}
              type="text"
              id="new-prompt-title"
              placeholder={locale === "en" ? "Enter a prompt title" : "プロンプトのタイトルを入力"}
              required
              value={newPromptTitle}
              onChange={(event) => {
                setNewPromptTitle(event.target.value);
              }}
            />
          </div>

          <div className="form-group">
            <label htmlFor="new-prompt-content">{t("chat.promptContent")}</label>
            <textarea
              ref={contentInputRef}
              id="new-prompt-content"
              rows={5}
              placeholder={locale === "en" ? "Enter detailed prompt instructions" : "具体的なプロンプト内容を入力"}
              required
              value={newPromptContent}
              onChange={(event) => {
                setNewPromptContent(event.target.value);
              }}
            ></textarea>
          </div>

          {/* AI補助機能のルートノード（JSで動的に内容を注入する）/ Root node for AI assist feature (content injected dynamically) */}
          <div id="newPromptAssistRoot" ref={newPromptAssistRootRef}></div>
          {/* エラー時のみ文言を可視表示し、送信中/成功はボタン自体のビジュアル（スピナー→チェック）で伝える。
              読み上げ用のテキストはスクリーンリーダー向けに残す（視覚的には非表示）。 */}
          {/* Only errors show visible text; submitting/success states are conveyed by the button's
              own visuals (spinner → checkmark). The message stays for screen readers but is visually hidden otherwise. */}
          <p
            id="newPromptSubmitStatus"
            className={`composer-status${newPromptStatus.variant === "error" ? "" : " composer-status--visually-hidden"}`}
            hidden={!newPromptStatus.message}
            data-variant={newPromptStatus.variant}
            role={newPromptStatus.variant === "error" ? "alert" : "status"}
            aria-live={newPromptStatus.variant === "error" ? "assertive" : "polite"}
            aria-atomic="true"
          >
            {newPromptStatus.variant === "error" ? (
              <i className="bi bi-exclamation-triangle-fill" aria-hidden="true"></i>
            ) : null}
            {newPromptStatus.message}
          </p>

          {/* 入出力例の追加オプション（AIの再現性を高めるための設定）/ Option to add input/output examples (improves AI reproducibility) */}
          <div className="form-group form-group--toggle">
            <label className="composer-toggle" htmlFor="new-guardrail-checkbox">
              <input
                type="checkbox"
                id="new-guardrail-checkbox"
                checked={guardrailEnabled}
                onChange={(event) => {
                  setGuardrailEnabled(event.target.checked);
                }}
              />
              <span className="composer-toggle__copy">
                <strong>{locale === "en" ? "Add input and output examples" : "入出力例を追加する"}</strong>
                <small>{locale === "en" ? "Examples help make AI suggestions more repeatable." : "AI 提案の再現性を高めるための例を持たせます。"}</small>
              </span>
            </label>
          </div>

          {/* 入出力例の入力欄（チェックボックスがONの場合のみ表示）/ Input/output example fields (shown only when checkbox is checked) */}
          <div id="new-guardrail-fields" hidden={!guardrailEnabled}>
            <div className="form-group">
              <label htmlFor="new-prompt-input-example">{locale === "en" ? "Input example (keep this separate from the prompt instructions)" : "入力例（プロンプト内容とは別にしてください）"}</label>
              <textarea
                ref={inputExampleRef}
                id="new-prompt-input-example"
                rows={3}
                placeholder={locale === "en" ? "For example: Task name\\nPrompt template\\nResponse rules\\nOutput template" : "例: タスク名\\nプロンプトテンプレート\\n回答ルール\\n出力テンプレート"}
                value={newPromptInputExample}
                onChange={(event) => {
                  setNewPromptInputExample(event.target.value);
                }}
              ></textarea>
            </div>
            <div className="form-group">
              <label htmlFor="new-prompt-output-example">{locale === "en" ? "Output example" : "出力例"}</label>
              <textarea
                ref={outputExampleRef}
                id="new-prompt-output-example"
                rows={3}
                placeholder={
                  locale === "en" ? "For example: ## Section\\n- Item\\n\\n## Steps\\n### Step 1\\n- Action" : "例: ## セクション名\\n- 項目\\n\\n## ステップ\\n### ステップ1\\n- 実施内容"
                }
                value={newPromptOutputExample}
                onChange={(event) => {
                  setNewPromptOutputExample(event.target.value);
                }}
              ></textarea>
            </div>
          </div>

          {/* 投稿ボタン（送信中はアイコンのみのスピナー、成功時はチェックマークで状態を伝える）*/}
          {/* Submit button (an icon-only spinner conveys submitting; a checkmark conveys success) */}
          <button
            type="submit"
            className={`primary-button new-prompt-submit-btn${isPromptSubmitting ? " is-loading" : ""}${
              newPromptStatus.variant === "success" ? " is-success" : ""
            }`}
            disabled={isPromptSubmitting}
          >
            <i
              className={`bi ${
                newPromptStatus.variant === "success"
                  ? "bi-check-lg"
                  : isPromptSubmitting
                    ? "bi-arrow-repeat new-prompt-submit-btn__spinner"
                    : "bi-upload"
              }`}
              aria-hidden="true"
            ></i>
            <span className="new-prompt-submit-btn__label">
              {newPromptStatus.variant === "success"
                ? (locale === "en" ? "Posted" : "投稿しました")
                : isPromptSubmitting
                  ? (locale === "en" ? "Preparing with AI…" : "AIと投稿を準備中...")
                  : (locale === "en" ? "Post prompt" : "投稿する")}
            </span>
          </button>
        </form>
        </div>
      </div>
    </ModalShell>
  );
}
