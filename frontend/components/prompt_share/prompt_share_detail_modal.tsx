import React, { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import MarkdownContent from "../MarkdownContent";
import { copyTextToClipboard } from "../../scripts/core/clipboard";
import { showToast } from "../../scripts/core/toast";
import { DEFAULT_AUTHOR_AVATAR_URL } from "../../scripts/prompt_share/constants";
import { getCategoryLabelOrFallback } from "../../scripts/prompt_share/prompt_category_registry";
import { DEFAULT_CONTENT_FORMAT, DEFAULT_MEDIA_TYPE } from "../../scripts/prompt_share/prompt_type_registry";
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
import type { PromptRecord } from "./prompt_card";
import { PromptShareDetailImage } from "./prompt_share_detail_image";
import { CopyButton } from "../ui/copy_button";
import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";
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
  onOpenAuthorProfile: (authorUserId: number, authorName: string) => void;
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

type AuthorMetaItemProps = {
  name: string;
  avatarUrl: string;
  authorUserId: number;
  onOpenProfile: (authorUserId: number, authorName: string) => void;
};

// 投稿者の署名項目。アバター画像付きで、ユーザーIDがある場合のみプロフィールへ遷移できる
// The author byline item; shows an avatar and links to the profile when a user ID is present
function AuthorMetaItem({ name, avatarUrl, authorUserId, onOpenProfile }: AuthorMetaItemProps) {
  const { t } = useTranslation();
  const [hasImageError, setHasImageError] = useState(false);
  const resolvedAvatarUrl = hasImageError || !avatarUrl ? DEFAULT_AUTHOR_AVATAR_URL : avatarUrl;
  const avatarImage = (
    <img
      className="prompt-detail-author__avatar"
      src={resolvedAvatarUrl}
      alt={t("promptShare.authorAvatarAlt", { name })}
      loading="lazy"
      decoding="async"
      onError={() => {
        setHasImageError(true);
      }}
    />
  );

  return (
    <div className="prompt-detail-meta__item">
      {/* アバター画像が視覚的なアイコンを兼ねるため、他項目と違いdtアイコンは出さない */}
      {/* The avatar already carries the visual icon role, so this dt skips the usual bi-* icon */}
      <dt>
        <span className="sr-only">{t("promptShare.author")}</span>
      </dt>
      <dd id="modalPromptAuthor">
        {authorUserId > 0 ? (
          <button
            type="button"
            className="prompt-detail-author"
            onClick={() => {
              onOpenProfile(authorUserId, name);
            }}
          >
            {avatarImage}
            <span>{name}</span>
          </button>
        ) : (
          <span className="prompt-detail-author prompt-detail-author--static">
            {avatarImage}
            <span>{name}</span>
          </span>
        )}
      </dd>
    </div>
  );
}

// モーダルの中身（パネル）。外殻の ModalShell とは分け、静的マークアップのテストでも描けるようにする
// The modal's panel; kept apart from the ModalShell shell so static-markup tests can render it
export function PromptShareDetailModalPanel({
  isLoggedIn,
  activeView,
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
  onClose,
  onOpenAuthorProfile
}: Omit<PromptShareDetailModalProps, "isOpen" | "promptDetailModalRef">) {
  const { locale, t } = useTranslation();

  // promptがnullのときは安全なデフォルト値を使い、2軸表示を崩さない
  // Fall back to default axes when no prompt is loaded to keep axis-dependent rendering stable
  const detailContentFormat = detailPrompt
    ? normalizePromptContentFormat(String(detailPrompt.content_format || ""))
    : "prompt";
  const detailMediaType = detailPrompt
    ? normalizePromptMediaType(String(detailPrompt.media_type || ""))
    : "text";
  const isSkillFormat = detailContentFormat === "skill";
  // 既定の組み合わせ（プロンプト×テキスト）のチップは情報量がないので出さない
  // The default combination (prompt x text) carries no information, so those chips are hidden
  const isDefaultFormat = detailContentFormat === DEFAULT_CONTENT_FORMAT;
  const isDefaultMedia = detailMediaType === DEFAULT_MEDIA_TYPE;
  const promptBody = isSkillFormat
    ? detailPrompt?.skill_markdown || ""
    : detailPrompt?.content || "";
  const promptBodyLabel = isSkillFormat ? t("promptShare.skillDefinition") : t("promptShare.body");
  const promptBodyHelper = isSkillFormat ? "Markdown" : t("promptShare.readyBody");
  const promptBodyEmptyText = detailPrompt ? t("promptShare.contentMissing") : t("promptShare.loadingPrompt");
  const formattedDate = formatPromptDate(detailPrompt?.created_at) || t("promptShare.dateUnavailable");
  const categoryLabel = getCategoryLabelOrFallback(detailPrompt?.category, undefined, locale);
  const authorLabel = detailPrompt?.author || t("promptShare.authorMissing");
  const authorUserId = Number(detailPrompt?.author_user_id || 0);
  const authorAvatarUrl = detailPrompt?.author_avatar_url || "";
  const promptBodyLength = Array.from(promptBody).length;
  const hasExamples = !isSkillFormat && Boolean(detailPrompt?.input_examples || detailPrompt?.output_examples);
  const skillResources = isSkillFormat
    ? normalizeSkillResources(detailPrompt?.resources, detailPrompt?.skill_python_script || "")
    : [];

  const copyPromptBody = async (): Promise<boolean> => {
    if (!promptBody.trim()) {
      showToast(t("promptShare.nothingToCopy"), { variant: "error" });
      return false;
    }
    try {
      await copyTextToClipboard(promptBody);
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("promptShare.copyFailed"), { variant: "error" });
      return false;
    }
  };

  const copyResource = async (content: string): Promise<boolean> => {
    try {
      await copyTextToClipboard(content);
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("promptShare.copyFailed"), { variant: "error" });
      return false;
    }
  };

  return (
    <>
      <div className="cc-modal__panel cc-modal__panel--xl cc-modal__panel--reader" tabIndex={-1}>
        {/* 上に固定するのはタブと閉じるボタンの1行だけ。見出しは本文と一緒にスクロールさせる */}
        {/* Only the tab row and the close button are pinned; the title scrolls with the body */}
        <header className="cc-modal__header cc-modal__header--compact">
          <div className="cc-modal__tabs prompt-detail-tabs" role="tablist" aria-label={t("promptShare.detailView")}>
            <button
              type="button"
              role="tab"
              id="promptDetailTab"
              aria-selected={activeView === "detail" ? "true" : "false"}
              aria-controls="promptDetailPanel"
              className={`cc-modal__tab prompt-detail-tabs__button${activeView === "detail" ? " is-active" : ""}`}
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
              className={`cc-modal__tab prompt-detail-tabs__button${activeView === "comments" ? " is-active" : ""}`}
              onClick={() => {
                onActiveViewChange("comments");
              }}
            >
              {t("promptShare.comments")}
              <span className="cc-modal__tab-count">{Number(detailPrompt?.comment_count || 0)}</span>
            </button>
          </div>
          <ModalCloseButton
            id="closePromptDetailModal"
            label={t("promptShare.closeModal")}
            ref={promptDetailCloseButtonRef}
            onClick={onClose}
          />
        </header>

        {/* モーダル内のスクロールはこの1箇所だけに集約し、本文の入れ子スクロールをなくす */}
        {/* The single scroll container in the modal, so the body never scrolls inside a scroller */}
        <div className="cc-modal__body prompt-detail-scroll">
          <div className="prompt-detail-header">
            <h2 className="cc-modal__title prompt-detail-title" id="modalPromptTitle">
              {detailPrompt?.title || t("promptShare.loadingPrompt")}
            </h2>

            <dl className="cc-modal__meta prompt-detail-meta" aria-label={t("promptShare.summary")}>
              {/* カードと同じ読み順に合わせ、投稿者を先頭に置いてタグをその後ろに並べる */}
              {/* Matching the card's reading order: the author comes first, the tags follow */}
              <AuthorMetaItem
                name={authorLabel}
                avatarUrl={authorAvatarUrl}
                authorUserId={authorUserId}
                onOpenProfile={onOpenAuthorProfile}
              />
              <DetailMetaItem
                iconClass="bi-hash"
                label={t("promptShare.category")}
                value={categoryLabel}
                id="modalPromptCategory"
              />
              {/* カードと同じく、既定値（プロンプト / テキスト）のチップは並べずに情報のあるものだけ残す */}
              {/* Like the card, the default chips (prompt / text) are dropped so only informative ones remain */}
              {isDefaultFormat ? null : (
                <div className="prompt-detail-meta__item prompt-detail-meta__item--chip">
                  <dt>
                    <i className={`bi ${getPromptFormatIconClass(detailContentFormat)}`} aria-hidden="true"></i>
                    <span className="sr-only">{t("promptShare.format")}</span>
                  </dt>
                  <dd id="modalPromptFormat">
                    {detailPrompt ? getPromptFormatLabel(detailContentFormat, locale) : ""}
                  </dd>
                </div>
              )}
              {isDefaultMedia ? null : (
                <div className="prompt-detail-meta__item prompt-detail-meta__item--chip">
                  <dt>
                    <i className={`bi ${getPromptMediaIconClass(detailMediaType)}`} aria-hidden="true"></i>
                    <span className="sr-only">{t("promptShare.media")}</span>
                  </dt>
                  <dd id="modalPromptMediaType">
                    {detailPrompt ? getPromptMediaLabel(detailMediaType, locale) : ""}
                  </dd>
                </div>
              )}
              {detailPrompt?.ai_model ? (
                <DetailMetaItem
                  iconClass="bi-cpu"
                  label={t("promptShare.aiModel")}
                  value={detailPrompt.ai_model}
                  id="modalAiModel"
                />
              ) : null}
              <DetailMetaItem
                iconClass="bi-calendar3"
                label={t("promptShare.publishedAt")}
                value={formattedDate}
              />
            </dl>
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
            {detailPrompt?.description?.trim() ? (
              <section className="cc-modal__section prompt-detail-section prompt-detail-section--description" aria-labelledby="modalPromptDescriptionTitle">
                <div className="cc-modal__section-head">
                  <span className="cc-modal__section-title" id="modalPromptDescriptionTitle">
                    {t("promptShare.description")}
                  </span>
                </div>
                <p className="prompt-detail-description">{detailPrompt.description}</p>
              </section>
            ) : null}

            {/* 作例メディアはURLが存在するプロンプトにのみ表示する（現状は画像プレビュー対応） */}
            {/* Reference media is only rendered when the prompt has a URL (currently image preview) */}
            {detailPrompt?.reference_image_url ? (
              <PromptShareDetailImage
                imageUrl={detailPrompt.reference_image_url}
                title={detailPrompt.title}
                mediaLabel={t("promptShare.exampleMedia")}
              />
            ) : null}

            <article
              id={isSkillFormat ? "modalSkillMarkdownGroup" : undefined}
              className="cc-modal__section prompt-detail-section prompt-detail-section--body"
            >
              <div className="cc-modal__section-head">
                <span className="cc-modal__section-title">{promptBodyLabel}</span>
                {/* フッターを廃止したので、本文コピーはこの見出し行の右端に置く */}
                {/* The footer is gone, so the body copy button lives at the right of this heading row */}
                <div className="prompt-detail-body-head__actions">
                  <span className="cc-modal__section-meta">
                    {promptBodyLength > 0 ? t("promptShare.characters", { count: promptBodyLength.toLocaleString(locale === "ja" ? "ja-JP" : "en-US") }) : promptBodyHelper}
                  </span>
                  <CopyButton
                    onCopy={copyPromptBody}
                    label={t("common.copy")}
                    copiedLabel={t("common.copied")}
                    className="cc-modal__btn cc-modal__btn--sm cc-modal__btn--icon"
                    disabled={!promptBody.trim()}
                  />
                </div>
              </div>
              {/* 本文はMarkdown記法を含む可能性があるため、フォーマット軸に関わらず常にMarkdownとして整形する */}
              {/* The body may contain Markdown syntax, so it is always rendered as Markdown regardless of the format axis */}
              {promptBody ? (
                <MarkdownContent id="modalPromptContent" text={promptBody} className="cc-modal__prose prompt-detail-markdown md-content" />
              ) : (
                <p id="modalPromptContent" className="prompt-detail-text-block">
                  {promptBodyEmptyText}
                </p>
              )}
            </article>

            {/* 入出力例は本文の後に2列で並べる（設定画面の閲覧モーダルと同じ組み） */}
            {/* Input/output examples follow the body in two columns, as in the settings preview modal */}
            {hasExamples ? (
              <section className="cc-modal__section prompt-detail-examples" aria-labelledby="modalExamplesTitle">
                <div className="cc-modal__section-head">
                  <span className="cc-modal__section-title" id="modalExamplesTitle">
                    {t("promptShare.examples")}
                  </span>
                  <span className="cc-modal__section-meta">{t("promptShare.supplemental")}</span>
                </div>
                <div className="cc-modal__example-grid prompt-detail-examples__grid">
                  {detailPrompt?.input_examples ? (
                    <article id="modalInputExamplesGroup" className="cc-modal__example prompt-detail-example">
                      <h3>
                        <i className="bi bi-box-arrow-in-right" aria-hidden="true"></i>
                        {t("promptShare.inputExample")}
                      </h3>
                      <p id="modalInputExamples">{detailPrompt.input_examples}</p>
                    </article>
                  ) : null}

                  {detailPrompt?.output_examples ? (
                    <article id="modalOutputExamplesGroup" className="cc-modal__example prompt-detail-example">
                      <h3>
                        <i className="bi bi-box-arrow-right" aria-hidden="true"></i>
                        {t("promptShare.outputExample")}
                      </h3>
                      <p id="modalOutputExamples">{detailPrompt.output_examples}</p>
                    </article>
                  ) : null}
                </div>
              </section>
            ) : null}

            {skillResources.length > 0 ? (
              <section className="cc-modal__section prompt-detail-resources" aria-labelledby="modalSkillResourcesTitle">
                <div className="cc-modal__section-head">
                  <span className="cc-modal__section-title" id="modalSkillResourcesTitle">
                    {t("promptShare.additionalResources")}
                  </span>
                  <span className="cc-modal__section-meta">
                    {t("promptShare.filesCount", { count: skillResources.length })}
                  </span>
                </div>
                <div className="prompt-detail-resources__list">
                  {skillResources.map((resource, index) => (
                    <article className="prompt-detail-resource" key={`${resource.path}-${index}`}>
                      <div className="prompt-detail-resource__head">
                        <div>
                          <span className="prompt-detail-resource__path">{resource.path}</span>
                          <span className="cc-modal__section-meta">
                            {getSkillResourceRoleLabel(resource.role, locale)}
                            {resource.language ? ` · ${resource.language}` : ""}
                          </span>
                        </div>
                        <CopyButton
                          onCopy={() => copyResource(resource.content)}
                          label={t("common.copy")}
                          copiedLabel={t("common.copied")}
                          className="cc-modal__btn cc-modal__btn--sm prompt-detail-resource__copy"
                        />
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
            <div className="cc-modal__section-head prompt-detail-comments__header">
              <h3 className="cc-modal__section-title">{t("promptShare.comments")}</h3>
              {/* 読み込み中はボタンを無効化して重複フェッチを防ぐ */}
              {/* Disable reload while loading to prevent duplicate fetch requests */}
              <button
                type="button"
                className="cc-modal__btn cc-modal__btn--sm prompt-detail-comments__reload"
                onClick={onReloadComments}
                disabled={isDetailCommentsLoading}
              >
                <i className="bi bi-arrow-clockwise" aria-hidden="true"></i>
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
                <button type="submit" className="cc-modal__btn cc-modal__btn--primary" disabled={isCommentSubmitting}>
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
                            className="cc-modal__btn cc-modal__btn--sm cc-modal__btn--danger"
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
                            className="cc-modal__btn cc-modal__btn--sm cc-modal__btn--ghost"
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
    </>
  );
}

// プロンプト詳細とコメントを切り替えて表示するモーダルコンポーネント（外殻）
// Modal that switches between prompt detail view and comments view via tabs (the shell)
export function PromptShareDetailModal(props: PromptShareDetailModalProps) {
  const { isOpen, onClose, activeView, promptDetailModalRef, commentTextareaRef, commentsSectionRef, promptDetailCloseButtonRef } = props;

  // 開いたときの初期フォーカス先。コメントから開いた場合は入力欄、それ以外は閉じるボタン。
  // activeView は ref に写してから読むので、タブ切り替えでフォーカスが奪われることはない。
  // Initial focus on open: the comment box when opened on comments, otherwise the close button.
  // activeView is mirrored into a ref so switching tabs never re-runs the focus.
  const activeViewRef = useRef(activeView);
  useEffect(() => {
    activeViewRef.current = activeView;
  }, [activeView]);
  const getInitialFocus = useCallback(() => {
    if (activeViewRef.current === "comments") {
      return commentTextareaRef.current || commentsSectionRef.current;
    }
    return promptDetailCloseButtonRef.current;
  }, [commentTextareaRef, commentsSectionRef, promptDetailCloseButtonRef]);

  return (
    <ModalShell
      isOpen={isOpen}
      onClose={onClose}
      id="promptDetailModal"
      className="cc-modal prompt-share-modal prompt-detail-modal"
      labelledBy="modalPromptTitle"
      overlayRef={promptDetailModalRef}
      getInitialFocus={getInitialFocus}
    >
      <PromptShareDetailModalPanel {...props} />
    </ModalShell>
  );
}
