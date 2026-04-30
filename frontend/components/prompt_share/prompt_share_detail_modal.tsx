import type { RefObject } from "react";

import {
  formatPromptDate,
  getPromptTypeLabel,
  normalizePromptType
} from "../../scripts/prompt_share/formatters";
import type { PromptCommentData } from "../../scripts/prompt_share/types";
import type { PromptRecord } from "./prompt_card";

type PromptShareDetailModalProps = {
  isOpen: boolean;
  isLoggedIn: boolean;
  activeView: "detail" | "comments";
  promptDetailModalRef: RefObject<HTMLDivElement>;
  commentsSectionRef: RefObject<HTMLElement>;
  commentTextareaRef: RefObject<HTMLTextAreaElement>;
  detailPrompt: PromptRecord | null;
  detailComments: PromptCommentData[];
  isDetailCommentsLoading: boolean;
  isCommentSubmitting: boolean;
  commentDraft: string;
  commentActionPendingIds: Set<string>;
  promptDetailCloseButtonRef: RefObject<HTMLButtonElement>;
  onActiveViewChange: (view: "detail" | "comments") => void;
  onCommentDraftChange: (value: string) => void;
  onSubmitComment: () => void;
  onDeleteComment: (commentId: string | number) => void;
  onReportComment: (commentId: string | number) => void;
  onReloadComments: () => void;
  onClose: () => void;
};

export function PromptShareDetailModal({
  isOpen,
  isLoggedIn,
  activeView,
  promptDetailModalRef,
  commentsSectionRef,
  commentTextareaRef,
  detailPrompt,
  detailComments,
  isDetailCommentsLoading,
  isCommentSubmitting,
  commentDraft,
  commentActionPendingIds,
  promptDetailCloseButtonRef,
  onActiveViewChange,
  onCommentDraftChange,
  onSubmitComment,
  onDeleteComment,
  onReportComment,
  onReloadComments,
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
          <div className="prompt-detail-tabs" role="tablist" aria-label="プロンプト詳細表示">
            <button
              type="button"
              role="tab"
              id="promptDetailTab"
              aria-selected={activeView === "detail" ? "true" : "false"}
              aria-controls="promptDetailPanel"
              className={`prompt-detail-tabs__button${activeView === "detail" ? " is-active" : ""}`}
              onClick={() => {
                onActiveViewChange("detail");
              }}
            >
              詳細
            </button>
            <button
              type="button"
              role="tab"
              id="promptCommentsTab"
              aria-selected={activeView === "comments" ? "true" : "false"}
              aria-controls="promptCommentsPanel"
              className={`prompt-detail-tabs__button${activeView === "comments" ? " is-active" : ""}`}
              onClick={() => {
                onActiveViewChange("comments");
              }}
            >
              コメント
              <span>{Number(detailPrompt?.comment_count || 0)}</span>
            </button>
          </div>

          <section
            id="promptDetailPanel"
            role="tabpanel"
            aria-labelledby="promptDetailTab"
            hidden={activeView !== "detail"}
            className="prompt-detail-panel"
          >
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
          </section>

          <section
            id="promptCommentsPanel"
            role="tabpanel"
            aria-labelledby="promptCommentsTab"
            hidden={activeView !== "comments"}
            className="prompt-detail-comments"
            aria-live="polite"
            ref={commentsSectionRef}
            tabIndex={-1}
          >
            <div className="prompt-detail-comments__summary">
              <span>{detailPrompt?.category || "未分類"}</span>
              <strong>{detailPrompt?.title || "プロンプト"}</strong>
            </div>
            <div className="prompt-detail-comments__header">
              <h3>コメント</h3>
              <button
                type="button"
                className="prompt-detail-comments__reload"
                onClick={onReloadComments}
                disabled={isDetailCommentsLoading}
              >
                {isDetailCommentsLoading ? "読み込み中..." : "更新"}
              </button>
            </div>

            {isLoggedIn ? (
              <form
                className="prompt-detail-comments__composer"
                onSubmit={(event) => {
                  event.preventDefault();
                  void onSubmitComment();
                }}
              >
                <textarea
                  ref={commentTextareaRef}
                  value={commentDraft}
                  maxLength={1000}
                  placeholder="使ってみた感想や改善ポイントを書いてください"
                  onChange={(event) => {
                    onCommentDraftChange(event.target.value);
                  }}
                />
                <button type="submit" disabled={isCommentSubmitting}>
                  {isCommentSubmitting ? "投稿中..." : "コメントを投稿"}
                </button>
              </form>
            ) : (
              <p className="prompt-detail-comments__login-note">コメントするにはログインが必要です。</p>
            )}

            {isDetailCommentsLoading ? (
              <p className="prompt-detail-comments__status">コメントを読み込み中...</p>
            ) : detailComments.length === 0 ? (
              <p className="prompt-detail-comments__status">まだコメントはありません。</p>
            ) : (
              <ul className="prompt-detail-comments__list">
                {detailComments.map((comment) => {
                  const commentId = String(comment.id);
                  const isPending = commentActionPendingIds.has(commentId);
                  return (
                    <li key={commentId} className="prompt-detail-comments__item">
                      <div className="prompt-detail-comments__meta">
                        <strong>{comment.author_name || "ユーザー"}</strong>
                        <span>{formatPromptDate(comment.created_at) || ""}</span>
                      </div>
                      <p>{comment.content || ""}</p>
                      <div className="prompt-detail-comments__actions">
                        {comment.can_delete ? (
                          <button
                            type="button"
                            disabled={isPending}
                            onClick={() => {
                              onDeleteComment(comment.id);
                            }}
                          >
                            削除
                          </button>
                        ) : (
                          <button
                            type="button"
                            disabled={isPending}
                            onClick={() => {
                              onReportComment(comment.id);
                            }}
                          >
                            報告
                          </button>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
