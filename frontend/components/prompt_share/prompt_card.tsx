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
  isSaveToListPending: boolean;
  onOpenDetail: (prompt: PromptRecord) => void;
  onOpenShare: (prompt: PromptRecord, event: MouseEvent<HTMLButtonElement>) => void;
  onToggleDropdown: (promptId: string) => void;
  onCloseDropdown: () => void;
  onSaveToList: (prompt: PromptRecord) => void;
  onToggleLike: (prompt: PromptRecord) => void;
  onToggleBookmark: (prompt: PromptRecord) => void;
};

function PromptCardComponent({
  prompt,
  isDropdownOpen,
  isLikePending,
  isBookmarkPending,
  isSaveToListPending,
  onOpenDetail,
  onOpenShare,
  onToggleDropdown,
  onCloseDropdown,
  onSaveToList,
  onToggleLike,
  onToggleBookmark,
}: PromptCardProps) {
  const promptTypeValue = normalizePromptType(prompt.prompt_type);
  const isBookmarked = Boolean(prompt.bookmarked);
  const isSavedToList = Boolean(prompt.saved_to_list);
  const promptId = prompt.clientId;
  const safeCategory = prompt.category || "未分類";
  const safeCreatedAt = formatPromptDate(prompt.created_at) || "日付未設定";
  const commentCount = Number(prompt.comment_count || 0);

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
          data-action="save-to-list"
          disabled={isSavedToList || isSaveToListPending}
          onClick={(event) => {
            event.stopPropagation();
            void onSaveToList(prompt);
          }}
        >
          {isSavedToList ? "プロンプトリストに保存済み" : "プロンプトリストに保存"}
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
      <p className="prompt-card__content">{truncateContent(prompt.content)}</p>

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
              onOpenDetail(prompt);
            }}
          >
            <i className="bi bi-chat-dots"></i>
            <span className="prompt-action-count">{commentCount}</span>
          </button>
          <button
            className={`prompt-action-btn like-btn${prompt.liked ? " liked" : ""}`}
            type="button"
            aria-label="いいね"
            aria-pressed={prompt.liked ? "true" : "false"}
            data-tooltip="このプロンプトにいいね"
            data-tooltip-placement="top"
            disabled={isLikePending}
            onClick={(event) => {
              event.stopPropagation();
              void onToggleLike(prompt);
            }}
          >
            <i className={`bi ${prompt.liked ? "bi-heart-fill" : "bi-heart"}`}></i>
          </button>
          <button
            className={`prompt-action-btn bookmark-btn${isBookmarked ? " bookmarked" : ""}`}
            type="button"
            aria-label="保存"
            aria-pressed={isBookmarked ? "true" : "false"}
            data-tooltip={isBookmarked ? "保存を解除" : "このプロンプトを保存"}
            data-tooltip-placement="top"
            disabled={isBookmarkPending}
            onClick={(event) => {
              event.stopPropagation();
              void onToggleBookmark(prompt);
            }}
          >
            <i className={`bi ${isBookmarked ? "bi-bookmark-check-fill" : "bi-bookmark"}`}></i>
          </button>
        </div>
      </div>
    </div>
  );
}

export const PromptCard = memo(PromptCardComponent);
PromptCard.displayName = "PromptCard";
