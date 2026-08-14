import { memo, useState, type MouseEvent } from "react";

import MarkdownContent from "../MarkdownContent";
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
  normalizePromptMediaType,
  truncateContent,
  truncateTitle,
} from "../../scripts/prompt_share/formatters";
import type { PromptData } from "../../scripts/prompt_share/types";
import { useTranslation } from "../../contexts/locale_context";

// サーバーから受け取ったPromptDataに、クライアント専用の状態を追加した拡張型
// Extends server-side PromptData with client-only state (local ID and action status)
export type PromptRecord = PromptData & {
  clientId: string;
  liked: boolean;
  used_in_chat: boolean;
};

// カードが受け取るすべての操作ハンドラと状態をまとめたProps型
// All action handlers and UI state props passed into the card component
type PromptCardProps = {
  prompt: PromptRecord;
  isDropdownOpen: boolean;
  isLikePending: boolean;
  isLikeEffectActive: boolean;
  isAddAsTaskPending: boolean;
  isUseInChatEffectActive: boolean;
  onOpenDetail: (prompt: PromptRecord) => void;
  onOpenComments: (prompt: PromptRecord) => void;
  onOpenShare: (prompt: PromptRecord, event: MouseEvent<HTMLButtonElement>) => void;
  onToggleDropdown: (promptId: string) => void;
  onCloseDropdown: () => void;
  onAddAsTask: (prompt: PromptRecord) => void;
  onToggleLike: (prompt: PromptRecord) => void;
  onOpenAuthorProfile: (authorUserId: number, authorName: string) => void;
};

// アバター画像の読み込みに失敗した場合、デフォルト画像へ差し替える
// Falls back to the default image when the avatar fails to load
function AuthorAvatarImage({ src, alt }: { src: string; alt: string }) {
  const [hasError, setHasError] = useState(false);
  return (
    <img
      className="prompt-card__author-avatar"
      src={hasError || !src ? DEFAULT_AUTHOR_AVATAR_URL : src}
      alt={alt}
      loading="lazy"
      decoding="async"
      onError={() => {
        setHasError(true);
      }}
    />
  );
}

function PromptCardComponent({
  prompt,
  isDropdownOpen,
  isLikePending,
  isLikeEffectActive,
  isAddAsTaskPending,
  isUseInChatEffectActive,
  onOpenDetail,
  onOpenComments,
  onOpenShare,
  onToggleDropdown,
  onCloseDropdown,
  onAddAsTask,
  onToggleLike,
  onOpenAuthorProfile,
}: PromptCardProps) {
  const { locale, t } = useTranslation();
  // サーバー値を正規化し、未設定時のフォールバックを確保する
  // Normalize server values and set safe fallbacks for missing fields
  const contentFormatValue = normalizePromptContentFormat(String(prompt.content_format || ""));
  const mediaTypeValue = normalizePromptMediaType(String(prompt.media_type || ""));
  // 既定の組み合わせ（プロンプト×テキスト）はカードから読み取れる情報なので、バッジを省いてカテゴリ名に幅を譲る
  // The default combination (prompt x text) is already obvious from the card, so hide those badges and give the width to the category
  const isDefaultFormat = contentFormatValue === DEFAULT_CONTENT_FORMAT;
  const isDefaultMedia = mediaTypeValue === DEFAULT_MEDIA_TYPE;
  const promptId = prompt.clientId;
  const safeCategory = getCategoryLabelOrFallback(prompt.category, undefined, locale);
  const safeCreatedAt = formatPromptDate(prompt.created_at) || t("promptShare.dateUnavailable");
  const commentCount = Number(prompt.comment_count || 0);
  const isUsedInChat = Boolean(prompt.used_in_chat);
  const menuId = `prompt-actions-menu-${promptId}`;
  const authorName = prompt.author || t("promptShare.authorMissing");
  const authorUserId = Number(prompt.author_user_id || 0);
  const hasAuthorProfile = authorUserId > 0;

  // SKILLフォーマットはskill_markdownを、それ以外はcontentをプレビューに使う
  // Show skill_markdown preview for skill-format prompts; fall back to content otherwise
  const cardPreview =
    contentFormatValue === "skill"
      ? truncateContent(prompt.skill_markdown || t("promptShare.skillOpenHelp"))
      : truncateContent(prompt.content);

  return (
    <div
      className={`prompt-card cc-press${isDropdownOpen ? " menu-open" : ""}`}
      data-category={prompt.category || ""}
      onClick={() => {
        onOpenDetail(prompt);
      }}
    >
      <div className="prompt-card__header">
        <div className="prompt-card__badges">
          <span className="prompt-card__category-pill">
            <i className="bi bi-hash"></i>
            <span>{safeCategory}</span>
          </span>
          {/* 既定値のバッジ（プロンプト / テキスト）は情報量がなく、狭い画面でカテゴリ名を潰すだけなので出さない */}
          {/* Skip the default badges (prompt / text): they add no information and squeeze the category name on narrow screens */}
          {isDefaultFormat ? null : (
            <span className={`prompt-card__type-pill prompt-card__type-pill--format prompt-card__type-pill--${contentFormatValue}`}>
              <i className={`bi ${getPromptFormatIconClass(contentFormatValue)}`}></i>
              <span>{getPromptFormatLabel(contentFormatValue, locale)}</span>
            </span>
          )}
          {/* メディア軸を独立したバッジとして表示し、画像を生成対象として扱う */}
          {/* Render media as an independent badge, so image is a generation target rather than a post type */}
          {isDefaultMedia ? null : (
            <span className={`prompt-card__type-pill prompt-card__type-pill--media prompt-card__type-pill--${mediaTypeValue}`}>
              <i className={`bi ${getPromptMediaIconClass(mediaTypeValue)}`}></i>
              <span>{getPromptMediaLabel(mediaTypeValue, locale)}</span>
            </span>
          )}
        </div>
        <span className="prompt-card__created-at">
          <i className="bi bi-calendar3"></i>
          {safeCreatedAt}
        </span>
        {/* 投稿者と日付を同じメタ情報行に配置する。ユーザーIDがある場合のみプロフィールへ遷移できる */}
        {/* Keep the author and date on the same metadata row; only make the author interactive when a user ID exists */}
        {hasAuthorProfile ? (
          <button
            type="button"
            className="prompt-card__author"
            onClick={(event) => {
              event.stopPropagation();
              onOpenAuthorProfile(authorUserId, authorName);
            }}
          >
            <AuthorAvatarImage
              src={prompt.author_avatar_url || ""}
              alt={t("promptShare.authorAvatarAlt", { name: authorName })}
            />
            <span className="prompt-card__author-name">{authorName}</span>
          </button>
        ) : (
          <div className="prompt-card__author prompt-card__author--static">
            <AuthorAvatarImage
              src={prompt.author_avatar_url || ""}
              alt={t("promptShare.authorAvatarAlt", { name: authorName })}
            />
            <span className="prompt-card__author-name">{authorName}</span>
          </div>
        )}
        {/* クリックがカード本体に伝播しないようにstopPropagationでモーダル誤起動を防ぐ */}
        {/* Stop propagation so clicking the menu button does not also open the detail modal */}
        <button
          className="meatball-menu cc-press"
          type="button"
          aria-label={t("promptShare.moreActions")}
          aria-haspopup="true"
          aria-expanded={isDropdownOpen ? "true" : "false"}
          aria-controls={menuId}
          data-tooltip={t("promptShare.moreActions")}
          data-tooltip-placement="left"
          onClick={(event) => {
            event.stopPropagation();
            onToggleDropdown(promptId);
          }}
        >
          <i className="bi bi-three-dots"></i>
        </button>
      </div>

      {/* ドロップダウンもカードクリックを遮断し、意図しない詳細モーダルの起動を避ける */}
      {/* Dropdown also stops propagation to prevent unintended detail modal trigger */}
      <div
        id={menuId}
        className={`prompt-actions-dropdown${isDropdownOpen ? " is-open" : ""}`}
        role="menu"
        aria-hidden={isDropdownOpen ? "false" : "true"}
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        <button
          className="dropdown-item cc-press"
          type="button"
          role="menuitem"
          data-action="share"
          onClick={(event) => {
            onOpenShare(prompt, event);
          }}
        >
          <i className="bi bi-share"></i>
          <span>{t("common.share")}</span>
        </button>
        <button
          className="dropdown-item cc-press"
          type="button"
          role="menuitem"
          onClick={() => {
            onCloseDropdown();
          }}
        >
          <i className="bi bi-bell-slash"></i>
          <span>{t("promptShare.mute")}</span>
        </button>
        <button
          className="dropdown-item cc-press"
          type="button"
          role="menuitem"
          onClick={() => {
            onCloseDropdown();
          }}
        >
          <i className="bi bi-flag"></i>
          <span>{t("promptShare.report")}</span>
        </button>
      </div>

      {/* 作例画像は存在する場合のみ表示し、遅延読み込みで初期描画コストを下げる */}
      {/* Reference image is optional; lazy loading reduces initial render cost */}
      {prompt.reference_image_url ? (
        <div className="prompt-card__image">
          <img
            src={prompt.reference_image_url}
            alt={t("promptShare.exampleImageAlt", { title: truncateTitle(prompt.title) })}
            loading="lazy"
            decoding="async"
          />
        </div>
      ) : null}

      <h3>{truncateTitle(prompt.title)}</h3>
      {/* カード内の本文プレビューも詳細モーダルと同じ安全なMarkdownレンダラーで整形する */}
      {/* Render the card preview through the same safe Markdown renderer as the detail modal */}
      <MarkdownContent text={cardPreview} className="prompt-card__content" />

      <div className="prompt-meta">
        <div className="prompt-actions">
          <button
            className="prompt-action-btn comment-btn cc-press"
            type="button"
            aria-label={t("promptShare.comments")}
            data-tooltip={t("promptShare.commentTooltip")}
            data-tooltip-placement="top"
            onClick={(event) => {
              event.stopPropagation();
              onOpenComments(prompt);
            }}
          >
            <i className="bi bi-chat-dots"></i>
            <span className="prompt-action-count">{commentCount}</span>
          </button>

          {/* isPendingの間は追加クリックを無視してAPIの二重送信を防ぐ */}
          {/* Guard against double-submission by ignoring clicks while a like request is in flight */}
          <button
            className={`prompt-action-btn like-btn cc-press${prompt.liked ? " liked" : ""}${isLikePending ? " is-pending" : ""}${isLikeEffectActive ? " is-celebrating" : ""}`}
            type="button"
            aria-label={prompt.liked ? t("promptShare.unlike") : t("promptShare.like")}
            aria-pressed={prompt.liked ? "true" : "false"}
            aria-disabled={isLikePending ? "true" : "false"}
            data-tooltip={prompt.liked ? t("promptShare.unlike") : t("promptShare.likeTooltip")}
            data-tooltip-placement="top"
            onClick={(event) => {
              event.stopPropagation();
              if (isLikePending) {
                return;
              }
              void onToggleLike(prompt);
            }}
          >
            <i className={`bi ${prompt.liked ? "bi-heart-fill" : "bi-heart"}`}></i>
          </button>

          {/* チャットで使う操作も二重送信を防ぐ */}
          {/* Guard the use-in-chat action against duplicate API requests */}
          <button
            className={`prompt-action-btn use-in-chat-btn cc-press${isUsedInChat ? " used-in-chat" : ""}${isAddAsTaskPending ? " is-pending" : ""}${isUseInChatEffectActive ? " is-celebrating" : ""}`}
            type="button"
            aria-label={isUsedInChat ? t("promptShare.removeFromChat") : t("promptShare.useInChat")}
            aria-pressed={isUsedInChat ? "true" : "false"}
            aria-disabled={isAddAsTaskPending ? "true" : "false"}
            data-tooltip={
              isAddAsTaskPending
                ? t("promptShare.updatingChat")
                : isUsedInChat
                  ? t("promptShare.removeFromChat")
                  : t("promptShare.useInChat")
            }
            data-tooltip-placement="top"
            onClick={(event) => {
              event.stopPropagation();
              if (isAddAsTaskPending) {
                return;
              }
              void onAddAsTask(prompt);
            }}
          >
            <i className={`bi ${isUsedInChat ? "bi-plus-square-fill" : "bi-plus-square"}`}></i>
          </button>
        </div>
      </div>
    </div>
  );
}

// propsが変わらない限り再レンダリングをスキップし、カードリスト全体のパフォーマンスを保つ
// Wrap with memo so unchanged cards in a large list are not re-rendered unnecessarily
export const PromptCard = memo(PromptCardComponent);
PromptCard.displayName = "PromptCard";
