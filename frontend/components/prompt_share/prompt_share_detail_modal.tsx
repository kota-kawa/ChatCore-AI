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
import {
  getSkillResourceRoleLabel,
  normalizeSkillResources
} from "../../scripts/prompt_share/skill_resources";
import type { ReadingSize } from "../../scripts/prompt_share/storage";
import type { PromptRecord } from "./prompt_card";
import { usePromptReadingSize } from "./use_prompt_reading_size";
import { useTranslation } from "../../contexts/locale_context";

// 詳細モーダルが必要とするすべての状態とハンドラをまとめたProps型
// All props required by the detail modal including prompt data, comment state, and handlers
type PromptShareDetailModalProps = {
  isOpen: boolean;
  isLoggedIn: boolean;
  activeView: "detail" | "comments";
  promptDetailModalRef: RefObject<HTMLDivElement | null>;
  commentsSectionRef: RefObject<HTMLElement | null>;
  commentTextareaRef: RefObject<HTMLTextAreaElement | null>;
  detailPrompt: PromptRecord | null;
  detailComments: PromptCommentData[];
  isDetailCommentsLoading: boolean;
  isCommentSubmitting: boolean;
  commentDraft: string;
  commentActionPendingIds: Set<string>;
  promptDetailCloseButtonRef: RefObject<HTMLButtonElement | null>;
  onActiveViewChange: (view: "detail" | "comments") => void;
  onCommentDraftChange: (value: string) => void;
  onSubmitComment: () => void;
  onDeleteComment: (commentId: string | number) => void;
  onReportComment: (commentId: string | number) => void;
  onReloadComments: () => void;
  onClose: () => void;
};

type DetailMetaItemProps = {
  iconClass: string;
  label: string;
  value: string;
  id?: string;
};

// 見出し直下の署名行に並ぶ1項目。ラベルはアイコンで示し、読み上げ用にテキストも残す
// One item in the byline under the title; the icon carries the label visually, text stays for screen readers
function DetailMetaItem({ iconClass, label, value, id }: DetailMetaItemProps) {
  return (
    <div className="prompt-detail-meta__item">
      <dt>
        <i className={`bi ${iconClass}`} aria-hidden="true"></i>
        <span className="sr-only">{label}</span>
      </dt>
      <dd id={id}>{value}</dd>
    </div>
  );
}

type ReadingSizeControlProps = {
  value: ReadingSize;
  onChange: (size: ReadingSize) => void;
};

// 本文の文字サイズを3段階で切り替える。選択はlocalStorageに残り次回以降も適用される
// Switches the body text between three sizes; the choice persists in localStorage
function ReadingSizeControl({ value, onChange }: ReadingSizeControlProps) {
  const { t } = useTranslation();
  const options: { value: ReadingSize; mark: string; label: string }[] = [
    { value: "compact", mark: t("promptShare.sizeMarkSmall"), label: t("promptShare.sizeSmall") },
    { value: "default", mark: t("promptShare.sizeMarkDefault"), label: t("promptShare.sizeDefault") },
    { value: "large", mark: t("promptShare.sizeMarkLarge"), label: t("promptShare.sizeLarge") }
  ];
  return (
    <div className="prompt-detail-readsize" role="group" aria-label={t("promptShare.readingSize")}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={`prompt-detail-readsize__button${value === option.value ? " is-active" : ""}`}
          aria-pressed={value === option.value}
          title={option.label}
          onClick={() => {
            onChange(option.value);
          }}
        >
          <span aria-hidden="true">{option.mark}</span>
          <span className="sr-only">{option.label}</span>
        </button>
      ))}
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
  const { locale, t } = useTranslation();
  const { readingSize, changeReadingSize } = usePromptReadingSize();
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
  const promptBodyLabel = isSkillFormat ? t("promptShare.skillDefinition") : t("promptShare.body");
  const promptBodyHelper = isSkillFormat ? "Markdown" : t("promptShare.readyBody");
  const promptBodyEmptyText = detailPrompt ? t("promptShare.contentMissing") : t("promptShare.loadingPrompt");
  const formattedDate = formatPromptDate(detailPrompt?.created_at) || t("promptShare.dateUnavailable");
  const categoryLabel = getCategoryLabelOrFallback(detailPrompt?.category, undefined, locale);
  const authorLabel = detailPrompt?.author || t("promptShare.authorMissing");
  const promptBodyLength = Array.from(promptBody).length;
  const hasExamples = !isSkillFormat && Boolean(detailPrompt?.input_examples || detailPrompt?.output_examples);
  const skillResources = isSkillFormat
    ? normalizeSkillResources(detailPrompt?.resources, detailPrompt?.skill_python_script || "")
    : [];

  const copyPromptBody = async () => {
    if (!promptBody.trim()) {
      showToast(t("promptShare.nothingToCopy"), { variant: "error" });
      return;
    }
    try {
      await copyTextToClipboard(promptBody);
      showToast(t("promptShare.bodyCopied"), { variant: "success" });
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("promptShare.copyFailed"), { variant: "error" });
    }
  };

  const copyResource = async (path: string, content: string) => {
    try {
      await copyTextToClipboard(content);
      showToast(t("promptShare.resourceCopied", { path }), { variant: "success" });
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("promptShare.copyFailed"), { variant: "error" });
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
      <div
        className="post-modal-content post-modal-content--detail"
        data-reading-size={readingSize}
        tabIndex={-1}
      >
        <button
          type="button"
          className="close-btn"
          id="closePromptDetailModal"
          aria-label={t("promptShare.closeModal")}
          ref={promptDetailCloseButtonRef}
          onClick={onClose}
        >
          &times;
        </button>
        {/* 見出し・署名・タブはスクロールさせず、本文だけが動く枠として固定する */}
        {/* Title, byline, and tabs stay put; only the reading area below scrolls */}
        <header className="prompt-detail-header">
          <h2 id="modalPromptTitle">{detailPrompt?.title || t("promptShare.detailsTitle")}</h2>

          <dl className="prompt-detail-meta" aria-label={t("promptShare.summary")}>
            <div className="prompt-detail-meta__item prompt-detail-meta__item--chip">
              <dt>
                <i className={`bi ${getPromptFormatIconClass(detailContentFormat)}`} aria-hidden="true"></i>
                <span className="sr-only">{t("promptShare.format")}</span>
              </dt>
              <dd id="modalPromptFormat">
                {detailPrompt ? getPromptFormatLabel(detailContentFormat, locale) : ""}
              </dd>
            </div>
            <div className="prompt-detail-meta__item prompt-detail-meta__item--chip">
              <dt>
                <i className={`bi ${getPromptMediaIconClass(detailMediaType)}`} aria-hidden="true"></i>
                <span className="sr-only">{t("promptShare.media")}</span>
              </dt>
              <dd id="modalPromptMediaType">
                {detailPrompt ? getPromptMediaLabel(detailMediaType, locale) : ""}
              </dd>
            </div>
            <DetailMetaItem
              iconClass="bi-hash"
              label={t("promptShare.category")}
              value={categoryLabel}
              id="modalPromptCategory"
            />
            <DetailMetaItem
              iconClass="bi-person"
              label={t("promptShare.author")}
              value={authorLabel}
              id="modalPromptAuthor"
            />
            <DetailMetaItem iconClass="bi-calendar3" label={t("promptShare.publishedAt")} value={formattedDate} />
            {detailPrompt?.ai_model ? (
              <DetailMetaItem
                iconClass="bi-cpu"
                label={t("promptShare.aiModel")}
                value={detailPrompt.ai_model}
                id="modalAiModel"
              />
            ) : null}
          </dl>

          {/* タブでdetail/commentsビューを切り替え、aria属性でスクリーンリーダーに対応する */}
          {/* Tab list for switching views; aria-selected and aria-controls satisfy ARIA tablist pattern */}
          <div className="prompt-detail-tabs" role="tablist" aria-label={t("promptShare.detailView")}>
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
              {t("promptShare.details")}
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
              {t("promptShare.comments")}
              <span>{Number(detailPrompt?.comment_count || 0)}</span>
            </button>
          </div>
        </header>

        {/* モーダル内のスクロールはこの1箇所だけに集約し、本文の入れ子スクロールをなくす */}
        {/* The single scroll container in the modal, so the body no longer scrolls inside a scroller */}
        <div className="modal-content-body prompt-detail-scroll">
          {/* 詳細パネル: hidden属性でDOM上は残しつつ非表示にする */}
          {/* Detail panel: kept in DOM via hidden attribute for fast tab switching */}
          <section
            id="promptDetailPanel"
            role="tabpanel"
            aria-labelledby="promptDetailTab"
            hidden={activeView !== "detail"}
            className="prompt-detail-panel"
          >
            <div className="prompt-detail-primary">
              {/* 作例メディアはURLが存在するプロンプトにのみ表示する（現状は画像プレビュー対応） */}
              {/* Reference media is only rendered when the prompt has a URL (currently image preview) */}
              {detailPrompt?.reference_image_url ? (
                <aside id="modalReferenceImageGroup" className="prompt-detail-media" aria-label={t("promptShare.exampleMedia")}>
                  <div className="prompt-detail-section__header">
                    <div>
                      <span className="prompt-detail-section__label">{t("promptShare.exampleMedia")}</span>
                      <span className="prompt-detail-section__meta">{t("promptShare.referenceImage")}</span>
                    </div>
                  </div>
                  <div className="modal-reference-image">
                    <img
                      id="modalReferenceImage"
                      src={detailPrompt.reference_image_url}
                      alt={t("promptShare.exampleImageAlt", { title: detailPrompt.title })}
                    />
                  </div>
                </aside>
              ) : null}

              <article
                id={isSkillFormat ? "modalSkillMarkdownGroup" : undefined}
                className="prompt-detail-section prompt-detail-section--body"
              >
                {/* 本文が長くてもコピーと文字サイズに手が届くよう、見出し行をスクロール内で固定する */}
                {/* Sticky within the scroller so copy and text size stay reachable through a long body */}
                <div className="prompt-detail-section__header prompt-detail-section__header--sticky">
                  <div>
                    <span className="prompt-detail-section__label">{promptBodyLabel}</span>
                    <span className="prompt-detail-section__meta">
                      {promptBodyLength > 0 ? t("promptShare.characters", { count: promptBodyLength.toLocaleString(locale === "ja" ? "ja-JP" : "en-US") }) : promptBodyHelper}
                    </span>
                  </div>
                  <div className="prompt-detail-section__actions">
                    <ReadingSizeControl value={readingSize} onChange={changeReadingSize} />
                    <button
                      type="button"
                      className="prompt-detail-copy-btn"
                      onClick={() => {
                        void copyPromptBody();
                      }}
                      disabled={!promptBody.trim()}
                    >
                      <i className="bi bi-clipboard" aria-hidden="true"></i>
                      <span>{t("common.copy")}</span>
                    </button>
                  </div>
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
                        <span className="prompt-detail-section__label">{t("promptShare.inputExample")}</span>
                        <span className="prompt-detail-section__meta">{t("promptShare.inputContext")}</span>
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
                        <span className="prompt-detail-section__label">{t("promptShare.outputExample")}</span>
                        <span className="prompt-detail-section__meta">{t("promptShare.expectedResponse")}</span>
                      </div>
                    </div>
                    <p id="modalOutputExamples" className="prompt-detail-text-block">
                      {detailPrompt.output_examples}
                    </p>
                  </article>
                ) : null}
              </div>
            ) : null}

            {skillResources.length > 0 ? (
              <section className="prompt-detail-resources" aria-labelledby="modalSkillResourcesTitle">
                <div className="prompt-detail-resources__heading">
                  <div>
                    <span className="prompt-detail-section__label" id="modalSkillResourcesTitle">
                      {t("promptShare.additionalResources")}
                    </span>
                    <span className="prompt-detail-section__meta">
                      {t("promptShare.filesCount", { count: skillResources.length })}
                    </span>
                  </div>
                </div>
                <div className="prompt-detail-resources__list">
                  {skillResources.map((resource, index) => (
                    <article
                      className="prompt-detail-section prompt-detail-section--code"
                      key={`${resource.path}-${index}`}
                    >
                      <div className="prompt-detail-section__header">
                        <div>
                          <span className="prompt-detail-section__label">{resource.path}</span>
                          <span className="prompt-detail-section__meta">
                            {getSkillResourceRoleLabel(resource.role, locale)}
                            {resource.language ? ` · ${resource.language}` : ""}
                          </span>
                        </div>
                        <button
                          type="button"
                          className="prompt-detail-copy-btn"
                          onClick={() => {
                            void copyResource(resource.path, resource.content);
                          }}
                        >
                          <i className="bi bi-clipboard" aria-hidden="true"></i>
                          <span>{t("common.copy")}</span>
                        </button>
                      </div>
                      <pre className="prompt-detail-code">
                        <code>{resource.content}</code>
                      </pre>
                    </article>
                  ))}
                </div>
              </section>
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
            {/* タイトルと概要はヘッダーに固定表示されるため、ここでは繰り返さない */}
            {/* The title and byline stay pinned in the header, so they are not repeated here */}
            <div className="prompt-detail-comments__header">
              <h3>{t("promptShare.comments")}</h3>
              {/* 読み込み中はボタンを無効化して重複フェッチを防ぐ */}
              {/* Disable reload while loading to prevent duplicate fetch requests */}
              <button
                type="button"
                className="prompt-detail-comments__reload"
                onClick={onReloadComments}
                disabled={isDetailCommentsLoading}
              >
                {isDetailCommentsLoading ? t("promptShare.refreshing") : t("promptShare.refresh")}
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
                  placeholder={t("promptShare.commentPlaceholder")}
                  onChange={(event) => {
                    onCommentDraftChange(event.target.value);
                  }}
                />
                <button type="submit" disabled={isCommentSubmitting}>
                  {isCommentSubmitting ? t("promptShare.postingComment") : t("promptShare.postComment")}
                </button>
              </form>
            ) : (
              <p className="prompt-detail-comments__login-note">{t("promptShare.loginToComment")}</p>
            )}

            {isDetailCommentsLoading ? (
              <p className="prompt-detail-comments__status">{t("promptShare.loadingComments")}</p>
            ) : detailComments.length === 0 ? (
              <p className="prompt-detail-comments__status">{t("promptShare.noComments")}</p>
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
                        <strong>{comment.author_name || t("promptShare.user")}</strong>
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
                            {t("common.delete")}
                          </button>
                        ) : (
                          <button
                            type="button"
                            disabled={isPending}
                            onClick={() => {
                              onReportComment(comment.id);
                            }}
                          >
                            {t("promptShare.report")}
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
