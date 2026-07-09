import { memo, type MouseEvent } from "react";

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
  truncateTitle,
} from "../../scripts/prompt_share/formatters";
import type { PromptData } from "../../scripts/prompt_share/types";

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
};

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
}: PromptCardProps) {
  // サーバー値を正規化し、未設定時のフォールバックを確保する
  // Normalize server values and set safe fallbacks for missing fields
  const contentFormatValue = normalizePromptContentFormat(String(prompt.content_format || ""));
  const mediaTypeValue = normalizePromptMediaType(String(prompt.media_type || ""));
  const promptId = prompt.clientId;
  const safeCategory = getCategoryLabelOrFallback(prompt.category);
  const safeCreatedAt = formatPromptDate(prompt.created_at) || "日付未設定";
  const commentCount = Number(prompt.comment_count || 0);
  const isUsedInChat = Boolean(prompt.used_in_chat);
  const menuId = `prompt-actions-menu-${promptId}`;

  // SKILLフォーマットはskill_markdownを、それ以外はcontentをプレビューに使う
  // Show skill_markdown preview for skill-format prompts; fall back to content otherwise
  const cardPreview =
    contentFormatValue === "skill"
      ? truncateContent(prompt.skill_markdown || "SKILLの詳細を開いて内容を確認してください。")
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
          {/* フォーマット軸をCSSクラスに反映し、アイコンとラベルをレジストリから決定する */}
          {/* Apply content-format class and resolve icon/label from the registry */}
          <span className={`prompt-card__type-pill prompt-card__type-pill--format prompt-card__type-pill--${contentFormatValue}`}>
            <i className={`bi ${getPromptFormatIconClass(contentFormatValue)}`}></i>
            <span>{getPromptFormatLabel(contentFormatValue)}</span>
          </span>
          {/* メディア軸を独立したバッジとして表示し、画像を生成対象として扱う */}
          {/* Render media as an independent badge, so image is a generation target rather than a post type */}
          <span className={`prompt-card__type-pill prompt-card__type-pill--media prompt-card__type-pill--${mediaTypeValue}`}>
            <i className={`bi ${getPromptMediaIconClass(mediaTypeValue)}`}></i>
            <span>{getPromptMediaLabel(mediaTypeValue)}</span>
          </span>
        </div>
        <span className="prompt-card__created-at">
          <i className="bi bi-calendar3"></i>
          {safeCreatedAt}
        </span>
        {/* クリックがカード本体に伝播しないようにstopPropagationでモーダル誤起動を防ぐ */}
        {/* Stop propagation so clicking the menu button does not also open the detail modal */}
        <button
          className="meatball-menu cc-press"
          type="button"
          aria-label="その他の操作"
          aria-haspopup="true"
          aria-expanded={isDropdownOpen ? "true" : "false"}
          aria-controls={menuId}
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
          <span>共有する</span>
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
          <span>ミュート</span>
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
          <span>報告する</span>
        </button>
      </div>

      {/* 作例画像は存在する場合のみ表示し、遅延読み込みで初期描画コストを下げる */}
      {/* Reference image is optional; lazy loading reduces initial render cost */}
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
            className="prompt-action-btn comment-btn cc-press"
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

          {/* isPendingの間は追加クリックを無視してAPIの二重送信を防ぐ */}
          {/* Guard against double-submission by ignoring clicks while a like request is in flight */}
          <button
            className={`prompt-action-btn like-btn cc-press${prompt.liked ? " liked" : ""}${isLikePending ? " is-pending" : ""}${isLikeEffectActive ? " is-celebrating" : ""}`}
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

          {/* チャットで使う操作も二重送信を防ぐ */}
          {/* Guard the use-in-chat action against duplicate API requests */}
          <button
            className={`prompt-action-btn use-in-chat-btn cc-press${isUsedInChat ? " used-in-chat" : ""}${isAddAsTaskPending ? " is-pending" : ""}${isUseInChatEffectActive ? " is-celebrating" : ""}`}
            type="button"
            aria-label={isUsedInChat ? "チャットで使う設定を解除" : "チャットで使う"}
            aria-pressed={isUsedInChat ? "true" : "false"}
            aria-disabled={isAddAsTaskPending ? "true" : "false"}
            data-tooltip={
              isAddAsTaskPending
                ? "チャット設定を更新中"
                : isUsedInChat
                  ? "チャットで使う設定を解除"
                  : "チャットで使う"
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
