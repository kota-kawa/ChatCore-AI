import { useCallback, useRef, type FormEvent, type MutableRefObject } from "react";

import { useModalFocusTrap } from "../../../hooks/use_modal_focus_trap";
import type { PromptStatus } from "../../../lib/chat_page/types";
import { ModalCloseButton } from "../../ui/modal_close_button";

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
  const modalRef = useRef<HTMLDivElement | null>(null);
  const getInitialFocus = useCallback(() => titleInputRef.current ?? modalRef.current, [titleInputRef]);
  const closeWithEscape = useCallback(() => {
    if (isPromptSubmitting) return;
    onClose();
  }, [isPromptSubmitting, onClose]);

  useModalFocusTrap({
    isOpen,
    containerRef: modalRef,
    getInitialFocus,
    onEscape: closeWithEscape,
  });

  return (
    <div
      ref={modalRef}
      id="newPromptModal"
      className={`new-prompt-modal modal-base ${isOpen ? "is-open show" : ""}`.trim()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="new-prompt-modal-title"
      aria-hidden={isOpen ? "false" : "true"}
      tabIndex={-1}
      onClick={(event) => {
        if (event.target === event.currentTarget && !isPromptSubmitting) {
          onClose();
        }
      }}
    >
      <div className="new-prompt-modal-content">
        <ModalCloseButton
          className="new-modal-close-btn"
          id="newModalCloseBtn"
          label="モーダルを閉じる"
          onClick={() => {
            if (isPromptSubmitting) return;
            onClose();
          }}
        />

        <div className="new-prompt-modal__hero">
          <div className="new-prompt-modal__hero-copy">
            <p className="new-prompt-modal__eyebrow">プロンプト作成</p>
            <h2 id="new-prompt-modal-title">新しいプロンプトを作成</h2>
            <p className="new-prompt-modal__lead">AI 補助を使いながら、短時間で実用的なタスクに整えられます。</p>
          </div>
          <div className="new-prompt-modal__hero-badges" aria-hidden="true">
            <span>下書き</span>
            <span>調整</span>
            <span>例</span>
          </div>
        </div>

        <form
          className="new-post-form"
          id="newPostForm"
          onSubmit={(event) => {
            onSubmit(event);
          }}
        >
          <div className="form-group">
            <label htmlFor="new-prompt-title">タイトル</label>
            <input
              ref={titleInputRef}
              type="text"
              id="new-prompt-title"
              placeholder="プロンプトのタイトルを入力"
              required
              value={newPromptTitle}
              onChange={(event) => {
                setNewPromptTitle(event.target.value);
              }}
            />
          </div>

          <div className="form-group">
            <label htmlFor="new-prompt-content">プロンプト内容</label>
            <textarea
              ref={contentInputRef}
              id="new-prompt-content"
              rows={5}
              placeholder="具体的なプロンプト内容を入力"
              required
              value={newPromptContent}
              onChange={(event) => {
                setNewPromptContent(event.target.value);
              }}
            ></textarea>
          </div>

          <div id="newPromptAssistRoot" ref={newPromptAssistRootRef}></div>
          <p
            id="newPromptSubmitStatus"
            className="composer-status"
            hidden={!newPromptStatus.message}
            data-variant={newPromptStatus.variant}
          >
            {newPromptStatus.message}
          </p>

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
                <strong>入出力例を追加する</strong>
                <small>AI 提案の再現性を高めるための例を持たせます。</small>
              </span>
            </label>
          </div>

          <div id="new-guardrail-fields" hidden={!guardrailEnabled}>
            <div className="form-group">
              <label htmlFor="new-prompt-input-example">入力例（プロンプト内容とは別にしてください）</label>
              <textarea
                ref={inputExampleRef}
                id="new-prompt-input-example"
                rows={3}
                placeholder={"例: タスク名\\nプロンプトテンプレート\\n回答ルール\\n出力テンプレート"}
                value={newPromptInputExample}
                onChange={(event) => {
                  setNewPromptInputExample(event.target.value);
                }}
              ></textarea>
            </div>
            <div className="form-group">
              <label htmlFor="new-prompt-output-example">出力例</label>
              <textarea
                ref={outputExampleRef}
                id="new-prompt-output-example"
                rows={3}
                placeholder={
                  "例: ## セクション名\\n- 項目\\n\\n## ステップ\\n### ステップ1\\n- 実施内容"
                }
                value={newPromptOutputExample}
                onChange={(event) => {
                  setNewPromptOutputExample(event.target.value);
                }}
              ></textarea>
            </div>
          </div>

          <button type="submit" className="primary-button new-prompt-submit-btn" disabled={isPromptSubmitting}>
            {isPromptSubmitting ? (
              <>
                <i className="bi bi-stars"></i> AIと投稿を準備中...
              </>
            ) : (
              <>
                <i className="bi bi-upload"></i> 投稿する
              </>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
