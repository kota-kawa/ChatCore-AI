import { asId } from "../../lib/utils";
import {
  getCategoryLabel,
  getCategoryLabelOrFallback
} from "../../scripts/prompt_share/prompt_category_registry";
import type { LikedPrompt, PromptRecord } from "../../scripts/user/settings/types";
import { normalizePreviewText, toDisplayDate, truncateTitle } from "../../scripts/user/settings/utils";

// ユーザーが投稿したプロンプト 1 件を表示するカードコンポーネント
// Card component displaying a single user-authored prompt
export function PromptCard({
  prompt,
  onEdit,
  onDelete
}: {
  prompt: PromptRecord;
  onEdit: (prompt: PromptRecord) => void;
  onDelete: (prompt: PromptRecord) => void;
}) {
  // プレビュー用に各テキストを正規化・整形する
  // Normalize each text field for preview display
  const promptId = asId(prompt.id);
  const contentPreview = normalizePreviewText(prompt.content);
  const inputPreview = normalizePreviewText(prompt.inputExamples);
  const outputPreview = normalizePreviewText(prompt.outputExamples);
  const categoryLabel = getCategoryLabelOrFallback(normalizePreviewText(prompt.category));
  const createdAtLabel = prompt.createdAt ? toDisplayDate(prompt.createdAt) : "日時未設定";

  return (
    <article className="prompt-card cc-press" data-prompt-id={promptId}>
      <div className="prompt-card__main">
        <div className="prompt-card__header">
          <div className="prompt-card__eyebrow">
            <span className="prompt-card__badge prompt-card__badge--category">{categoryLabel}</span>
            <time className="prompt-card__date" dateTime={prompt.createdAt}>
              <i className="bi bi-clock-history" aria-hidden="true"></i>
              {createdAtLabel}
            </time>
          </div>
          <h3 className="prompt-card__title" title={prompt.title}>{truncateTitle(prompt.title)}</h3>
        </div>
        <div className="prompt-card__body">
          <p className="prompt-card__description" title={prompt.content}>
            {contentPreview || "内容が設定されていません。"}
          </p>
          {/* 入出力例が存在する場合のみプレビューセクションを表示する / Show the preview section only when input or output examples exist */}
          {(inputPreview || outputPreview) ? (
            <div className="prompt-card__preview-sections">
              {inputPreview ? (
                <div className="prompt-card__preview-item">
                  <span className="prompt-card__preview-label">Input</span>
                  <p className="prompt-card__preview-text" title={prompt.inputExamples}>{inputPreview}</p>
                </div>
              ) : null}
              {outputPreview ? (
                <div className="prompt-card__preview-item">
                  <span className="prompt-card__preview-label">Output</span>
                  <p className="prompt-card__preview-text" title={prompt.outputExamples}>{outputPreview}</p>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      <div className="prompt-card__footer">
        <div className="prompt-card__actions">
          <button
            type="button"
            className="prompt-card__action-btn prompt-card__action-btn--edit cc-press"
            onClick={() => onEdit(prompt)}
            aria-label="編集"
          >
            <i className="bi bi-pencil-square"></i>
            <span>編集</span>
          </button>
          <button
            type="button"
            className="prompt-card__action-btn prompt-card__action-btn--delete cc-press"
            onClick={() => onDelete(prompt)}
            aria-label="削除"
          >
            <i className="bi bi-trash3"></i>
            <span>削除</span>
          </button>
        </div>
      </div>
    </article>
  );
}

// ユーザーがいいねしたプロンプト 1 件を表示するカードコンポーネント
// Card component displaying a single liked prompt entry
export function LikedPromptCard({
  entry,
  onDelete
}: {
  entry: LikedPrompt;
  onDelete: (entry: LikedPrompt) => void;
}) {
  const entryId = asId(entry.id);
  const contentPreview = normalizePreviewText(entry.content);
  const inputPreview = normalizePreviewText(entry.inputExamples);
  const outputPreview = normalizePreviewText(entry.outputExamples);
  // カテゴリ未設定時はバッジ自体を出さないため、フォールバックなしでラベルを解決する
  // Resolve the label without a fallback: an unset category hides the badge entirely
  const categoryLabel = getCategoryLabel(normalizePreviewText(entry.category));
  const likedAtLabel = entry.likedAt ? toDisplayDate(entry.likedAt) : "日時未設定";

  return (
    <article className="prompt-card cc-press" data-liked-prompt-id={entryId}>
      <div className="prompt-card__main">
        <div className="prompt-card__header">
          <div className="prompt-card__eyebrow">
            {/* いいね済みバッジを常に表示し、カテゴリがある場合のみカテゴリバッジも表示する / Always show the liked badge; show category badge only when a category is set */}
            <span className="prompt-card__badge prompt-card__badge--saved">
              <i className="bi bi-heart-fill me-1"></i>いいね済み
            </span>
            {categoryLabel ? (
              <span className="prompt-card__badge prompt-card__badge--category">{categoryLabel}</span>
            ) : null}
            <time className="prompt-card__date" dateTime={entry.likedAt}>
              {likedAtLabel}
            </time>
          </div>
          <h3 className="prompt-card__title" title={entry.title}>{truncateTitle(entry.title)}</h3>
        </div>
        <div className="prompt-card__body">
          <p className="prompt-card__description" title={entry.content}>
            {contentPreview || "内容が設定されていません。"}
          </p>
          {(inputPreview || outputPreview) ? (
            <div className="prompt-card__preview-sections">
              {inputPreview ? (
                <div className="prompt-card__preview-item">
                  <span className="prompt-card__preview-label">Input</span>
                  <p className="prompt-card__preview-text" title={entry.inputExamples}>{inputPreview}</p>
                </div>
              ) : null}
              {outputPreview ? (
                <div className="prompt-card__preview-item">
                  <span className="prompt-card__preview-label">Output</span>
                  <p className="prompt-card__preview-text" title={entry.outputExamples}>{outputPreview}</p>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      <div className="prompt-card__footer">
        <div className="prompt-card__actions">
          <button
            type="button"
            className="prompt-card__action-btn prompt-card__action-btn--delete cc-press"
            onClick={() => onDelete(entry)}
            aria-label="いいねを解除"
          >
            <i className="bi bi-heartbreak"></i>
            <span>いいねを解除</span>
          </button>
        </div>
      </div>
    </article>
  );
}
