import type { RefObject } from "react";

import MarkdownContent from "../MarkdownContent";
import {
  formatPromptDate,
  getPromptTypeLabel,
  normalizePromptType
} from "../../scripts/prompt_share/formatters";
import type { PromptCommentData } from "../../scripts/prompt_share/types";
import type { PromptRecord } from "./prompt_card";

// 詳細モーダルが必要とするすべての状態とハンドラをまとめたProps型
// All props required by the detail modal including prompt data, comment state, and handlers
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

// プロンプト詳細とコメントを切り替えて表示するモーダルコンポーネント
// Modal that switches between prompt detail view and comments view via tabs
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
  // promptがnullのときは安全なデフォルト値を使い、タイプ表示を崩さない
  // Fall back to "text" when no prompt is loaded to keep type-dependent rendering stable
  const detailPromptType = detailPrompt ? normalizePromptType(detailPrompt.prompt_type) : "text";

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
        // オーバーレイ背景クリックでモーダルを閉じる（内部クリックは無視する）
        // Close when clicking the backdrop; ignore clicks on modal content itself
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
          {/* タブでdetail/commentsビューを切り替え、aria属性でスクリーンリーダーに対応する */}
          {/* Tab list for switching views; aria-selected and aria-controls satisfy ARIA tablist pattern */}
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

          {/* 詳細パネル: hidden属性でDOM上は残しつつ非表示にする */}
          {/* Detail panel: kept in DOM via hidden attribute for fast tab switching */}
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
                {detailPrompt ? getPromptTypeLabel(detailPromptType) : ""}
              </p>
            </div>

            {/* 作例画像はURLが存在するプロンプトにのみ表示する */}
            {/* Reference image is only rendered when the prompt has an image URL */}
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

            {/* SKILLタイプはcontent欄がなく代わりにMarkdownで定義を表示するため除外する */}
            {/* SKILL prompts use skill_markdown instead of content, so content field is skipped */}
            {detailPromptType !== "skill" ? (
              <div className="form-group">
                <label>
                  <strong>内容:</strong>
                </label>
                <p id="modalPromptContent">{detailPrompt?.content || ""}</p>
              </div>
            ) : null}

            <div className="form-group">
              <label>
                <strong>投稿者:</strong>
              </label>
              <p id="modalPromptAuthor">{detailPrompt?.author || ""}</p>
            </div>

            {/* AIモデルが設定されているときのみ表示し、再現性情報を提供する */}
            {/* Show AI model only when set, to help users reproduce the same results */}
            {detailPrompt?.ai_model ? (
              <div id="modalAiModelGroup" className="form-group" style={{ display: "block" }}>
                <label>
                  <strong>使用AIモデル:</strong>
                </label>
                <p id="modalAiModel">{detailPrompt.ai_model}</p>
              </div>
            ) : null}

            {detailPromptType !== "skill" && detailPrompt?.input_examples ? (
              <div id="modalInputExamplesGroup" className="form-group" style={{ display: "block" }}>
                <label>
                  <strong>入力例:</strong>
                </label>
                <p id="modalInputExamples">{detailPrompt.input_examples}</p>
              </div>
            ) : null}

            {detailPromptType !== "skill" && detailPrompt?.output_examples ? (
              <div id="modalOutputExamplesGroup" className="form-group" style={{ display: "block" }}>
                <label>
                  <strong>出力例:</strong>
                </label>
                <p id="modalOutputExamples">{detailPrompt.output_examples}</p>
              </div>
            ) : null}

            {/* SKILLのMarkdown定義はMarkdownContentコンポーネントでレンダリングする */}
            {/* Render SKILL Markdown definition with the shared MarkdownContent renderer */}
            {detailPromptType === "skill" && detailPrompt?.skill_markdown ? (
              <div id="modalSkillMarkdownGroup" className="form-group" style={{ display: "block" }}>
                <label>
                  <strong>SKILL定義 (Markdown):</strong>
                </label>
                <MarkdownContent text={detailPrompt.skill_markdown} className="prompt-detail-markdown md-content" />
              </div>
            ) : null}

            {/* Pythonスクリプトはpreタグで等幅フォント表示し、コードの可読性を保つ */}
            {/* Python script shown in a <pre> block to preserve monospace formatting */}
            {detailPromptType === "skill" && detailPrompt?.skill_python_script ? (
              <div id="modalSkillPythonScriptGroup" className="form-group" style={{ display: "block" }}>
                <label>
                  <strong>追加 Python スクリプト:</strong>
                </label>
                <pre className="prompt-detail-code">
                  <code>{detailPrompt.skill_python_script}</code>
                </pre>
              </div>
            ) : null}
          </section>

          {/* コメントパネル: aria-liveで更新時にスクリーンリーダーへ通知する */}
          {/* Comments panel: aria-live announces updates to screen readers */}
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
              {/* 読み込み中はボタンを無効化して重複フェッチを防ぐ */}
              {/* Disable reload while loading to prevent duplicate fetch requests */}
              <button
                type="button"
                className="prompt-detail-comments__reload"
                onClick={onReloadComments}
                disabled={isDetailCommentsLoading}
              >
                {isDetailCommentsLoading ? "読み込み中..." : "更新"}
              </button>
            </div>

            {/* 未ログインユーザーにはフォームの代わりにログイン案内を表示する */}
            {/* Show login prompt instead of composer for unauthenticated users */}
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
                  // pendingIdsにIDが含まれる間はアクションボタンを無効化する
                  // Disable action buttons while a delete/report request is in flight for this comment
                  const isPending = commentActionPendingIds.has(commentId);
                  return (
                    <li key={commentId} className="prompt-detail-comments__item">
                      <div className="prompt-detail-comments__meta">
                        <strong>{comment.author_name || "ユーザー"}</strong>
                        <span>{formatPromptDate(comment.created_at) || ""}</span>
                      </div>
                      <p>{comment.content || ""}</p>
                      <div className="prompt-detail-comments__actions">
                        {/* 自分のコメントは削除でき、他人のコメントは報告できる */}
                        {/* Own comments show delete; others' comments show report */}
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
