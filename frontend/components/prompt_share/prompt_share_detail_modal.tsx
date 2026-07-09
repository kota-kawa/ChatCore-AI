import React, { type RefObject } from "react";

import MarkdownContent from "../MarkdownContent";
import { copyTextToClipboard } from "../../scripts/chat/message_utils";
import { showToast } from "../../scripts/core/toast";
import { getCategoryLabelOrFallback } from "../../scripts/prompt_share/prompt_category_registry";
import {
  formatPromptDate,
  getPromptFormatIconClass,
  getPromptFormatLabel,
  getPromptMediaIconClass,
  getPromptMediaLabel,
  normalizePromptContentFormat,
  normalizePromptMediaType
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

type DetailSummaryItemProps = {
  iconClass: string;
  label: string;
  value: string;
  id?: string;
};

function DetailSummaryItem({ iconClass, label, value, id }: DetailSummaryItemProps) {
  return (
    <div className="prompt-detail-summary__item">
      <dt>
        <i className={`bi ${iconClass}`} aria-hidden="true"></i>
        <span>{label}</span>
      </dt>
      <dd id={id}>{value}</dd>
    </div>
  );
}

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
  // promptがnullのときは安全なデフォルト値を使い、2軸表示を崩さない
  // Fall back to default axes when no prompt is loaded to keep axis-dependent rendering stable
  const detailContentFormat = detailPrompt
    ? normalizePromptContentFormat(String(detailPrompt.content_format || ""))
    : "prompt";
  const detailMediaType = detailPrompt
    ? normalizePromptMediaType(String(detailPrompt.media_type || ""))
    : "text";
  const isSkillFormat = detailContentFormat === "skill";
  const promptBody = isSkillFormat
    ? detailPrompt?.skill_markdown || ""
    : detailPrompt?.content || "";
  const promptBodyLabel = isSkillFormat ? "SKILL定義" : "プロンプト本文";
  const promptBodyHelper = isSkillFormat ? "Markdown" : "そのまま使える本文";
  const promptBodyEmptyText = detailPrompt ? "内容が登録されていません。" : "プロンプトを読み込み中です。";
  const formattedDate = formatPromptDate(detailPrompt?.created_at) || "日付未設定";
  const categoryLabel = getCategoryLabelOrFallback(detailPrompt?.category);
  const authorLabel = detailPrompt?.author || "投稿者未設定";
  const promptBodyLength = Array.from(promptBody).length;
  const hasExamples = !isSkillFormat && Boolean(detailPrompt?.input_examples || detailPrompt?.output_examples);

  const copyPromptBody = async () => {
    if (!promptBody.trim()) {
      showToast("コピーできる内容がありません。", { variant: "error" });
      return;
    }
    try {
      await copyTextToClipboard(promptBody);
      showToast("プロンプト本文をコピーしました。", { variant: "success" });
    } catch (error) {
      showToast(error instanceof Error ? error.message : "コピーに失敗しました。", { variant: "error" });
    }
  };

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
        <header className="prompt-detail-header">
          <div className="prompt-detail-heading">
            <span className="prompt-detail-heading__eyebrow">プロンプト詳細</span>
            <h2 id="modalPromptTitle">{detailPrompt?.title || "プロンプト詳細"}</h2>
          </div>
          <div className="prompt-detail-header__chips" aria-label="プロンプト属性">
            <span className="prompt-detail-chip">
              <i className={`bi ${getPromptFormatIconClass(detailContentFormat)}`} aria-hidden="true"></i>
              <span>形式</span>
              <strong id="modalPromptFormat">
                {detailPrompt ? getPromptFormatLabel(detailContentFormat) : ""}
              </strong>
            </span>
            <span className="prompt-detail-chip">
              <i className={`bi ${getPromptMediaIconClass(detailMediaType)}`} aria-hidden="true"></i>
              <span>生成</span>
              <strong id="modalPromptMediaType">
                {detailPrompt ? getPromptMediaLabel(detailMediaType) : ""}
              </strong>
            </span>
            <span className="prompt-detail-chip">
              <i className="bi bi-chat-dots" aria-hidden="true"></i>
              <span>コメント</span>
              <strong>{Number(detailPrompt?.comment_count || 0)}</strong>
            </span>
          </div>
        </header>

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
            <dl className="prompt-detail-summary" aria-label="プロンプト概要">
              <DetailSummaryItem
                iconClass="bi-hash"
                label="カテゴリ"
                value={categoryLabel}
                id="modalPromptCategory"
              />
              <DetailSummaryItem
                iconClass="bi-person"
                label="投稿者"
                value={authorLabel}
                id="modalPromptAuthor"
              />
              <DetailSummaryItem
                iconClass="bi-calendar3"
                label="投稿日"
                value={formattedDate}
              />
              {detailPrompt?.ai_model ? (
                <DetailSummaryItem
                  iconClass="bi-cpu"
                  label="使用AIモデル"
                  value={detailPrompt.ai_model}
                  id="modalAiModel"
                />
              ) : null}
            </dl>

            <div className={`prompt-detail-primary${detailPrompt?.reference_image_url ? " prompt-detail-primary--with-media" : ""}`}>
              {/* 作例メディアはURLが存在するプロンプトにのみ表示する（現状は画像プレビュー対応） */}
              {/* Reference media is only rendered when the prompt has a URL (currently image preview) */}
              {detailPrompt?.reference_image_url ? (
                <aside id="modalReferenceImageGroup" className="prompt-detail-media" aria-label="作例メディア">
                  <div className="prompt-detail-section__header">
                    <div>
                      <span className="prompt-detail-section__label">作例メディア</span>
                      <span className="prompt-detail-section__meta">参考画像</span>
                    </div>
                  </div>
                  <div className="modal-reference-image">
                    <img
                      id="modalReferenceImage"
                      src={detailPrompt.reference_image_url}
                      alt={`${detailPrompt.title} の作例画像`}
                    />
                  </div>
                </aside>
              ) : null}

              <article
                id={isSkillFormat ? "modalSkillMarkdownGroup" : undefined}
                className="prompt-detail-section prompt-detail-section--body"
              >
                <div className="prompt-detail-section__header">
                  <div>
                    <span className="prompt-detail-section__label">{promptBodyLabel}</span>
                    <span className="prompt-detail-section__meta">
                      {promptBodyLength > 0 ? `${promptBodyLength.toLocaleString("ja-JP")}文字` : promptBodyHelper}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="prompt-detail-copy-btn"
                    onClick={() => {
                      void copyPromptBody();
                    }}
                    disabled={!promptBody.trim()}
                  >
                    <i className="bi bi-clipboard" aria-hidden="true"></i>
                    <span>コピー</span>
                  </button>
                </div>
                {isSkillFormat && promptBody ? (
                  <MarkdownContent text={promptBody} className="prompt-detail-markdown md-content" />
                ) : (
                  <p id="modalPromptContent" className="prompt-detail-text-block">
                    {promptBody || promptBodyEmptyText}
                  </p>
                )}
              </article>
            </div>

            {hasExamples ? (
              <div className="prompt-detail-examples">
                {detailPrompt?.input_examples ? (
                  <article id="modalInputExamplesGroup" className="prompt-detail-section">
                    <div className="prompt-detail-section__header">
                      <div>
                        <span className="prompt-detail-section__label">入力例</span>
                        <span className="prompt-detail-section__meta">使い始めの文脈</span>
                      </div>
                    </div>
                    <p id="modalInputExamples" className="prompt-detail-text-block">
                      {detailPrompt.input_examples}
                    </p>
                  </article>
                ) : null}

                {detailPrompt?.output_examples ? (
                  <article id="modalOutputExamplesGroup" className="prompt-detail-section">
                    <div className="prompt-detail-section__header">
                      <div>
                        <span className="prompt-detail-section__label">出力例</span>
                        <span className="prompt-detail-section__meta">期待する返答</span>
                      </div>
                    </div>
                    <p id="modalOutputExamples" className="prompt-detail-text-block">
                      {detailPrompt.output_examples}
                    </p>
                  </article>
                ) : null}
              </div>
            ) : null}

            {/* Pythonスクリプトはpreタグで等幅フォント表示し、コードの可読性を保つ */}
            {/* Python script shown in a <pre> block to preserve monospace formatting */}
            {isSkillFormat && detailPrompt?.skill_python_script ? (
              <article id="modalSkillPythonScriptGroup" className="prompt-detail-section prompt-detail-section--code">
                <div className="prompt-detail-section__header">
                  <div>
                    <span className="prompt-detail-section__label">追加 Python スクリプト</span>
                    <span className="prompt-detail-section__meta">実行補助コード</span>
                  </div>
                </div>
                <pre className="prompt-detail-code">
                  <code>{detailPrompt.skill_python_script}</code>
                </pre>
              </article>
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
              <span>{categoryLabel}</span>
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
