import { asId } from "../../lib/utils";
import { stripMarkdownForPreview } from "../../scripts/core/markdown_preview";
import {
  getCategoryLabel,
  getCategoryLabelOrFallback
} from "../../scripts/prompt_share/prompt_category_registry";
import type { LikedPrompt, PromptRecord } from "../../scripts/user/settings/types";
import { normalizePreviewText, toDisplayDate, truncateTitle } from "../../scripts/user/settings/utils";
import type { PromptPreview } from "./prompt_preview_modal";
import { useTranslation } from "../../contexts/locale_context";

// ユーザーが投稿したプロンプト 1 件を表示するカードコンポーネント
// Card component displaying a single user-authored prompt
export function PromptCard({
  prompt,
  onPreview,
  onEdit,
  onDelete
}: {
  prompt: PromptRecord;
  onPreview: (prompt: PromptPreview) => void;
  onEdit: (prompt: PromptRecord) => void;
  onDelete: (prompt: PromptRecord) => void;
}) {
  const { t } = useTranslation();
  // プレビュー用に各テキストを正規化・整形する
  // Normalize each text field for preview display
  const promptId = asId(prompt.id);
  const isSkill = prompt.contentFormat === "skill";
  // 内容にMarkdown記法が含まれていても、カードの一行プレビューでは記号を残さず読みやすく表示する
  // Even when the content contains Markdown syntax, the one-line card preview strips it for readability
  const contentPreview = stripMarkdownForPreview(isSkill ? prompt.skillMarkdown : prompt.content);
  const inputPreview = normalizePreviewText(prompt.inputExamples);
  const outputPreview = normalizePreviewText(prompt.outputExamples);
  const categoryLabel = getCategoryLabelOrFallback(normalizePreviewText(prompt.category));
  const createdAtLabel = prompt.createdAt ? toDisplayDate(prompt.createdAt) : t("promptShare.dateUnknown");

  return (
    <article className="prompt-card cc-press" data-prompt-id={promptId}>
      <div
        className="prompt-card__main"
        role="button"
        tabIndex={0}
        aria-label={t("promptShare.showDetails", { title: prompt.title })}
        onClick={() => onPreview(prompt)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onPreview(prompt);
          }
        }}
      >
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
          <p className="prompt-card__description" title={isSkill ? prompt.skillMarkdown : prompt.content}>
            {contentPreview || t("promptShare.noContent")}
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
        <span className="prompt-card__view-hint">
          {t("promptShare.viewDetails")}<i className="bi bi-arrow-up-right" aria-hidden="true"></i>
        </span>
      </div>
      <div className="prompt-card__footer">
        <div className="prompt-card__actions">
          <button
            type="button"
            className="prompt-card__action-btn prompt-card__action-btn--edit cc-press"
            onClick={() => onEdit(prompt)}
            aria-label={t("common.edit")}
          >
            <i className="bi bi-pencil-square"></i>
            <span>{t("common.edit")}</span>
          </button>
          <button
            type="button"
            className="prompt-card__action-btn prompt-card__action-btn--delete cc-press"
            onClick={() => onDelete(prompt)}
            aria-label={t("common.delete")}
          >
            <i className="bi bi-trash3"></i>
            <span>{t("common.delete")}</span>
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
  onPreview,
  onDelete
}: {
  entry: LikedPrompt;
  onPreview: (prompt: PromptPreview) => void;
  onDelete: (entry: LikedPrompt) => void;
}) {
  const { t } = useTranslation();
  const entryId = asId(entry.id);
  const isSkill = entry.contentFormat === "skill";
  // 内容にMarkdown記法が含まれていても、カードの一行プレビューでは記号を残さず読みやすく表示する
  // Even when the content contains Markdown syntax, the one-line card preview strips it for readability
  const contentPreview = stripMarkdownForPreview(isSkill ? entry.skillMarkdown : entry.content);
  const inputPreview = normalizePreviewText(entry.inputExamples);
  const outputPreview = normalizePreviewText(entry.outputExamples);
  // カテゴリ未設定時はバッジ自体を出さないため、フォールバックなしでラベルを解決する
  // Resolve the label without a fallback: an unset category hides the badge entirely
  const categoryLabel = getCategoryLabel(normalizePreviewText(entry.category));
  const likedAtLabel = entry.likedAt ? toDisplayDate(entry.likedAt) : t("promptShare.dateUnknown");

  return (
    <article className="prompt-card cc-press" data-liked-prompt-id={entryId}>
      <div
        className="prompt-card__main"
        role="button"
        tabIndex={0}
        aria-label={t("promptShare.showDetails", { title: entry.title })}
        onClick={() => onPreview(entry)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onPreview(entry);
          }
        }}
      >
        <div className="prompt-card__header">
          <div className="prompt-card__eyebrow">
            {/* いいね済みバッジを常に表示し、カテゴリがある場合のみカテゴリバッジも表示する / Always show the liked badge; show category badge only when a category is set */}
            <span className="prompt-card__badge prompt-card__badge--saved">
              <i className="bi bi-heart-fill me-1"></i>{t("promptShare.liked")}
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
          <p className="prompt-card__description" title={isSkill ? entry.skillMarkdown : entry.content}>
            {contentPreview || t("promptShare.noContent")}
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
        <span className="prompt-card__view-hint">
          {t("promptShare.viewDetails")}<i className="bi bi-arrow-up-right" aria-hidden="true"></i>
        </span>
      </div>
      <div className="prompt-card__footer">
        <div className="prompt-card__actions">
          <button
            type="button"
            className="prompt-card__action-btn prompt-card__action-btn--delete cc-press"
            onClick={() => onDelete(entry)}
            aria-label={t("promptShare.unlike")}
          >
            <i className="bi bi-heartbreak"></i>
            <span>{t("promptShare.unlike")}</span>
          </button>
        </div>
      </div>
    </article>
  );
}
