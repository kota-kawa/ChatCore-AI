import type { FormEvent, MutableRefObject } from "react";

import type { PromptStatus } from "../../../lib/chat_page/types";

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
  return (
    <div
      id="newPromptModal"
      className={`new-prompt-modal modal-base ${isOpen ? "is-open show" : ""}`.trim()}
      aria-hidden={isOpen ? "false" : "true"}
      onClick={(event) => {
        if (event.target === event.currentTarget && !isPromptSubmitting) {
          onClose();
        }
      }}
    >
      <div className="new-prompt-modal-content">
        <button
          type="button"
          className="new-modal-close-btn"
          id="newModalCloseBtn"
          aria-label="モーダルを閉じる"
          onClick={() => {
            if (isPromptSubmitting) return;
            onClose();
          }}
        >
          &times;
        </button>

        <div className="new-prompt-modal__hero">
          <div className="new-prompt-modal__hero-copy">
            <p className="new-prompt-modal__eyebrow">Prompt Composer</p>
            <h2>新しいプロンプトを追加</h2>
            <p className="new-prompt-modal__lead">AI 補助を使いながら、短時間で実用的なタスクに整えられます。</p>
          </div>
          <div className="new-prompt-modal__hero-badges" aria-hidden="true">
            <span>Draft</span>
            <span>Polish</span>
            <span>Examples</span>
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
                placeholder="例: 夏休みの思い出をテーマにした短いエッセイを書いてください。"
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
                placeholder="例: 夏休みのある日、私は家族と一緒に海辺へ出かけました..."
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
