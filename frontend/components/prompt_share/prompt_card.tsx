import { memo, type MouseEvent } from "react";

import {
  formatPromptDate,
  getPromptTypeIconClass,
  getPromptTypeLabel,
  normalizePromptType,
  truncateContent,
  truncateTitle,
} from "../../scripts/prompt_share/formatters";
import type { PromptData } from "../../scripts/prompt_share/types";

export type PromptRecord = PromptData & {
  clientId: string;
  liked: boolean;
};

type PromptCardProps = {
  prompt: PromptRecord;
  isDropdownOpen: boolean;
  isLikePending: boolean;
  isBookmarkPending: boolean;
  isLikeEffectActive: boolean;
  isBookmarkEffectActive: boolean;
  isAddAsTaskPending: boolean;
  onOpenDetail: (prompt: PromptRecord) => void;
  onOpenComments: (prompt: PromptRecord) => void;
  onOpenShare: (prompt: PromptRecord, event: MouseEvent<HTMLButtonElement>) => void;
  onToggleDropdown: (promptId: string) => void;
  onCloseDropdown: () => void;
  onAddAsTask: (prompt: PromptRecord) => void;
  onToggleLike: (prompt: PromptRecord) => void;
  onToggleBookmark: (prompt: PromptRecord) => void;
};

function PromptCardComponent({
  prompt,
  isDropdownOpen,
  isLikePending,
  isBookmarkPending,
  isLikeEffectActive,
  isBookmarkEffectActive,
  isAddAsTaskPending,
  onOpenDetail,
  onOpenComments,
  onOpenShare,
  onToggleDropdown,
  onCloseDropdown,
  onAddAsTask,
  onToggleLike,
  onToggleBookmark,
}: PromptCardProps) {
  const promptTypeValue = normalizePromptType(prompt.prompt_type);
  const isBookmarked = Boolean(prompt.bookmarked);
  const promptId = prompt.clientId;
  const safeCategory = prompt.category || "未分類";
  const safeCreatedAt = formatPromptDate(prompt.created_at) || "日付未設定";
  const commentCount = Number(prompt.comment_count || 0);
  const cardPreview =
    promptTypeValue === "skill"
      ? truncateContent(prompt.skill_markdown || "SKILLの詳細を開いて内容を確認してください。")
      : truncateContent(prompt.content);

  return (
    <div
      className={`prompt-card${isDropdownOpen ? " menu-open" : ""}`}
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
          <span className={`prompt-card__type-pill prompt-card__type-pill--${promptTypeValue}`}>
            <i className={`bi ${getPromptTypeIconClass(promptTypeValue)}`}></i>
            <span>{getPromptTypeLabel(promptTypeValue)}</span>
          </span>
        </div>
        <span className="prompt-card__created-at">
          <i className="bi bi-calendar3"></i>
          {safeCreatedAt}
        </span>
        <button
          className="meatball-menu"
          type="button"
          aria-label="その他の操作"
          aria-haspopup="true"
          aria-expanded={isDropdownOpen ? "true" : "false"}
          data-tooltip="その他の操作"
          data-tooltip-placement="left"
          onClick={(event) => {
            event.stopPropagation();
            onToggleDropdown(promptId);
          }}
        >
          <i className="bi bi-three-dots"></i>
        </button>
      </div>

      <div
        className={`prompt-actions-dropdown${isDropdownOpen ? " is-open" : ""}`}
        role="menu"
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        <button
          className="dropdown-item"
          type="button"
          role="menuitem"
          data-action="share"
          onClick={(event) => {
            onOpenShare(prompt, event);
          }}
        >
          共有する
        </button>
        <button
          className="dropdown-item"
          type="button"
          role="menuitem"
          data-action="add-as-task"
          disabled={isAddAsTaskPending}
          onClick={(event) => {
            event.stopPropagation();
            void onAddAsTask(prompt);
          }}
        >
          {isAddAsTaskPending ? "タスクに追加中..." : "タスクとして追加"}
        </button>
        <button
          className="dropdown-item"
          type="button"
          role="menuitem"
          onClick={() => {
            onCloseDropdown();
          }}
        >
          ミュート
        </button>
        <button
          className="dropdown-item"
          type="button"
          role="menuitem"
          onClick={() => {
            onCloseDropdown();
          }}
        >
          報告する
        </button>
      </div>

      {prompt.reference_image_url ? (
        <div className="prompt-card__image">
          <img
            src={prompt.reference_image_url}
            alt={`${truncateTitle(prompt.title)} の作例画像`}
            loading="lazy"
            decoding="async"
          />
        </div>
      ) : null}

      <h3>{truncateTitle(prompt.title)}</h3>
      <p className="prompt-card__content">{cardPreview}</p>

      <div className="prompt-meta">
        <div className="prompt-actions">
          <button
            className="prompt-action-btn comment-btn"
            type="button"
            aria-label="コメント"
            data-tooltip="コメントを見る・投稿する"
            data-tooltip-placement="top"
            onClick={(event) => {
              event.stopPropagation();
              onOpenComments(prompt);
            }}
          >
            <i className="bi bi-chat-dots"></i>
            <span className="prompt-action-count">{commentCount}</span>
          </button>
          <button
            className={`prompt-action-btn like-btn${prompt.liked ? " liked" : ""}${isLikePending ? " is-pending" : ""}${isLikeEffectActive ? " is-celebrating" : ""}`}
            type="button"
            aria-label={prompt.liked ? "いいねを解除" : "いいね"}
            aria-pressed={prompt.liked ? "true" : "false"}
            aria-disabled={isLikePending ? "true" : "false"}
            data-tooltip={prompt.liked ? "いいねを解除" : "このプロンプトにいいね"}
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
          <button
            className={`prompt-action-btn bookmark-btn${isBookmarked ? " bookmarked" : ""}${isBookmarkPending ? " is-pending" : ""}${isBookmarkEffectActive ? " is-celebrating" : ""}`}
            type="button"
            aria-label={isBookmarked ? "ブックマークを解除" : "ブックマーク"}
            aria-pressed={isBookmarked ? "true" : "false"}
            aria-disabled={isBookmarkPending ? "true" : "false"}
            data-tooltip={isBookmarked ? "ブックマークを解除" : "このプロンプトをブックマーク"}
            data-tooltip-placement="top"
            onClick={(event) => {
              event.stopPropagation();
              if (isBookmarkPending) {
                return;
              }
              void onToggleBookmark(prompt);
            }}
          >
            <i className={`bi ${isBookmarked ? "bi-bookmark-fill" : "bi-bookmark"}`}></i>
          </button>
        </div>
      </div>
    </div>
  );
}

export const PromptCard = memo(PromptCardComponent);
PromptCard.displayName = "PromptCard";
