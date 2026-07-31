import { useState, type RefObject } from "react";

import { DEFAULT_AUTHOR_AVATAR_URL } from "../../scripts/prompt_share/constants";
import { getCategoryLabelOrFallback } from "../../scripts/prompt_share/prompt_category_registry";
import {
  formatPromptDate,
  getPromptFormatIconClass,
  getPromptFormatLabel,
  getPromptMediaIconClass,
  getPromptMediaLabel,
  normalizePromptContentFormat,
  normalizePromptMediaType,
  truncateContent,
  truncateTitle
} from "../../scripts/prompt_share/formatters";
import type { PromptAuthorProfile } from "../../scripts/prompt_share/types";
import type { PromptRecord } from "./prompt_card";
import { useTranslation } from "../../contexts/locale_context";

type PromptShareAuthorProfileModalProps = {
  isOpen: boolean;
  authorProfileModalRef: RefObject<HTMLDivElement | null>;
  profile: PromptAuthorProfile | null;
  fallbackName: string;
  prompts: PromptRecord[];
  isLoading: boolean;
  isLoadingMore: boolean;
  error: string | null;
  hasMore: boolean;
  onLoadMore: () => void;
  onOpenPrompt: (prompt: PromptRecord) => void;
  onClose: () => void;
};

// アバター画像が読み込めない場合にデフォルト画像へ差し替える
// Falls back to the default image when the avatar cannot be loaded
function ProfileAvatarImage({ src, alt }: { src: string; alt: string }) {
  const [hasError, setHasError] = useState(false);
  return (
    <img
      className="author-profile-header__avatar"
      src={hasError || !src ? DEFAULT_AUTHOR_AVATAR_URL : src}
      alt={alt}
      onError={() => {
        setHasError(true);
      }}
    />
  );
}

// 投稿者のプロフィール一覧に並ぶ1件分の簡易カード。タップすると通常の詳細モーダルへ遷移する
// One row in the author's post list; tapping opens the standard detail modal for full interactivity
function AuthorPromptRow({
  prompt,
  onOpen
}: {
  prompt: PromptRecord;
  onOpen: (prompt: PromptRecord) => void;
}) {
  const { locale, t } = useTranslation();
  const contentFormatValue = normalizePromptContentFormat(String(prompt.content_format || ""));
  const mediaTypeValue = normalizePromptMediaType(String(prompt.media_type || ""));
  const categoryLabel = getCategoryLabelOrFallback(prompt.category, undefined, locale);
  const createdAtLabel = formatPromptDate(prompt.created_at) || t("promptShare.dateUnavailable");
  const preview =
    contentFormatValue === "skill"
      ? truncateContent(prompt.skill_markdown || t("promptShare.skillOpenHelp"))
      : truncateContent(prompt.content);

  return (
    <li className="author-profile-list__item">
      <button
        type="button"
        className="author-profile-prompt"
        aria-label={t("promptShare.showDetails", { title: prompt.title })}
        onClick={() => {
          onOpen(prompt);
        }}
      >
        <div className="author-profile-prompt__badges">
          <span className="author-profile-prompt__pill">
            <i className="bi bi-hash" aria-hidden="true"></i>
            {categoryLabel}
          </span>
          <span className="author-profile-prompt__pill">
            <i className={`bi ${getPromptFormatIconClass(contentFormatValue)}`} aria-hidden="true"></i>
            {getPromptFormatLabel(contentFormatValue, locale)}
          </span>
          <span className="author-profile-prompt__pill">
            <i className={`bi ${getPromptMediaIconClass(mediaTypeValue)}`} aria-hidden="true"></i>
            {getPromptMediaLabel(mediaTypeValue, locale)}
          </span>
        </div>
        <h4 className="author-profile-prompt__title">{truncateTitle(prompt.title)}</h4>
        <p className="author-profile-prompt__content">{preview}</p>
        <div className="author-profile-prompt__meta">
          <span>
            <i className="bi bi-calendar3" aria-hidden="true"></i>
            {createdAtLabel}
          </span>
          <span>
            <i className="bi bi-chat-dots" aria-hidden="true"></i>
            {Number(prompt.comment_count || 0)}
          </span>
        </div>
      </button>
    </li>
  );
}

// SNSのように、アイコンから投稿者のこれまでの投稿と自己紹介を確認できるプロフィールモーダル
// SNS-style profile modal showing an author's past posts and self-introduction from their avatar
export function PromptShareAuthorProfileModal({
  isOpen,
  authorProfileModalRef,
  profile,
  fallbackName,
  prompts,
  isLoading,
  isLoadingMore,
  error,
  hasMore,
  onLoadMore,
  onOpenPrompt,
  onClose
}: PromptShareAuthorProfileModalProps) {
  const { t, formatNumber } = useTranslation();
  const displayName = profile?.username || fallbackName;
  const bio = profile?.bio?.trim() || "";
  const postCount = profile ? profile.prompt_count : prompts.length;

  return (
    <div
      id="promptAuthorProfileModal"
      className={`post-modal${isOpen ? " show" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-labelledby="authorProfileModalTitle"
      aria-hidden={isOpen ? "false" : "true"}
      ref={authorProfileModalRef}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="post-modal-content post-modal-content--author-profile" tabIndex={-1}>
        <button
          type="button"
          className="close-btn"
          aria-label={t("promptShare.closeAuthorProfile")}
          onClick={onClose}
        >
          &times;
        </button>

        <header className="author-profile-header">
          <ProfileAvatarImage
            src={profile?.avatar_url || ""}
            alt={t("promptShare.authorAvatarAlt", { name: displayName })}
          />
          <div className="author-profile-header__identity">
            <h2 id="authorProfileModalTitle">{displayName}</h2>
            <p className="author-profile-header__count">
              {t("promptShare.authorPostCount", { count: formatNumber(postCount) })}
            </p>
          </div>
          <p className="author-profile-header__bio">{bio || t("promptShare.noBio")}</p>
        </header>

        <div className="author-profile-body">
          <h3 className="author-profile-body__label">{t("promptShare.authorPosts")}</h3>

          {isLoading ? (
            <p className="author-profile-status">{t("promptShare.loading")}</p>
          ) : error ? (
            <p className="author-profile-status author-profile-status--error">{error}</p>
          ) : prompts.length === 0 ? (
            <p className="author-profile-status">{t("promptShare.noAuthorPosts")}</p>
          ) : (
            <ul className="author-profile-list">
              {prompts.map((prompt) => (
                <AuthorPromptRow key={prompt.clientId} prompt={prompt} onOpen={onOpenPrompt} />
              ))}
            </ul>
          )}

          {hasMore ? (
            <button
              type="button"
              className="author-profile-load-more"
              disabled={isLoadingMore}
              onClick={onLoadMore}
            >
              {isLoadingMore ? t("promptShare.loading") : t("promptShare.loadMore")}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
