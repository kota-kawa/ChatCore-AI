import type { RefObject } from "react";

import { getPromptTypeLabel, normalizePromptType } from "../../scripts/prompt_share/formatters";
import type { PromptRecord } from "./prompt_card";

type PromptShareDetailModalProps = {
  isOpen: boolean;
  promptDetailModalRef: RefObject<HTMLDivElement>;
  detailPrompt: PromptRecord | null;
  promptDetailCloseButtonRef: RefObject<HTMLButtonElement>;
  onClose: () => void;
};

export function PromptShareDetailModal({
  isOpen,
  promptDetailModalRef,
  detailPrompt,
  promptDetailCloseButtonRef,
  onClose
}: PromptShareDetailModalProps) {
  return (
    <div
      id="promptDetailModal"
      className={`post-modal${isOpen ? " show" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-labelledby="modalPromptTitle"
      aria-hidden={isOpen ? "false" : "true"}
      ref={promptDetailModalRef}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="post-modal-content post-modal-content--detail" tabIndex={-1}>
        <button
          type="button"
          className="close-btn"
          id="closePromptDetailModal"
          aria-label="詳細モーダルを閉じる"
          ref={promptDetailCloseButtonRef}
          onClick={onClose}
        >
          &times;
        </button>
        <h2 id="modalPromptTitle">{detailPrompt?.title || "プロンプト詳細"}</h2>

        <div className="modal-content-body">
          <div className="form-group">
            <label>
              <strong>タイプ:</strong>
            </label>
            <p id="modalPromptType">
              {detailPrompt ? getPromptTypeLabel(normalizePromptType(detailPrompt.prompt_type)) : ""}
            </p>
          </div>

          {detailPrompt?.reference_image_url ? (
            <div id="modalReferenceImageGroup" className="form-group" style={{ display: "block" }}>
              <label>
                <strong>作例画像:</strong>
              </label>
              <div className="modal-reference-image">
                <img
                  id="modalReferenceImage"
                  src={detailPrompt.reference_image_url}
                  alt={`${detailPrompt.title} の作例画像`}
                />
              </div>
            </div>
          ) : null}

          <div className="form-group">
            <label>
              <strong>カテゴリ:</strong>
            </label>
            <p id="modalPromptCategory">{detailPrompt?.category || ""}</p>
          </div>

          <div className="form-group">
            <label>
              <strong>内容:</strong>
            </label>
            <p id="modalPromptContent">{detailPrompt?.content || ""}</p>
          </div>

          <div className="form-group">
            <label>
              <strong>投稿者:</strong>
            </label>
            <p id="modalPromptAuthor">{detailPrompt?.author || ""}</p>
          </div>

          {detailPrompt?.ai_model ? (
            <div id="modalAiModelGroup" className="form-group" style={{ display: "block" }}>
              <label>
                <strong>使用AIモデル:</strong>
              </label>
              <p id="modalAiModel">{detailPrompt.ai_model}</p>
            </div>
          ) : null}

          {detailPrompt?.input_examples ? (
            <div id="modalInputExamplesGroup" className="form-group" style={{ display: "block" }}>
              <label>
                <strong>入力例:</strong>
              </label>
              <p id="modalInputExamples">{detailPrompt.input_examples}</p>
            </div>
          ) : null}

          {detailPrompt?.output_examples ? (
            <div id="modalOutputExamplesGroup" className="form-group" style={{ display: "block" }}>
              <label>
                <strong>出力例:</strong>
              </label>
              <p id="modalOutputExamples">{detailPrompt.output_examples}</p>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
