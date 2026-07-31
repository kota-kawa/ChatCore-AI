import type { ReactNode } from "react";

import { asId } from "../../lib/utils";
import { stripMarkdownForPreview } from "../../scripts/core/markdown_preview";
import {
  getPromptFormatIconClass,
  getPromptFormatLabel,
  normalizePromptContentFormat
} from "../../scripts/prompt_share/formatters";
import {
  getCategoryLabel,
  getCategoryLabelOrFallback
} from "../../scripts/prompt_share/prompt_category_registry";
import type { LikedPrompt, PromptRecord } from "../../scripts/user/settings/types";
import { normalizePreviewText, toDisplayDate, truncateTitle } from "../../scripts/user/settings/utils";
import type { PromptPreview } from "./prompt_preview_modal";
import { useTranslation } from "../../contexts/locale_context";

// プロンプト共有ページのカードと同じ構造・同じ見た目を設定画面でも使うための土台コンポーネント。
// 共有ページ側と揃えて「バッジ列 + 日付」「タイトル」「本文プレビュー」「操作列」の順に並べる。
// Shared shell that mirrors the prompt share page card: badge row + date, title,
// content preview, and an icon-only action row at the bottom.
function SettingsPromptCard({
  cardAttributes,
  title,
  contentSource,
  contentFormat,
  categoryLabel,
  savedBadge,
  dateLabel,
  dateTime,
  onOpenDetail,
  actions
}: {
  cardAttributes: Record<string, string>;
  title: string;
  contentSource: string;
  contentFormat: string;
  categoryLabel: string;
  savedBadge?: ReactNode;
  dateLabel: string;
  dateTime?: string;
  onOpenDetail: () => void;
  actions: ReactNode;
}) {
  const { locale, t } = useTranslation();
  const formatValue = normalizePromptContentFormat(contentFormat);
  // 内容にMarkdown記法が含まれていても、カードのプレビューでは記号を残さず読みやすく表示する
  // Even when the content contains Markdown syntax, the card preview strips it for readability
  const contentPreview = stripMarkdownForPreview(contentSource);

  return (
    <article className="prompt-card cc-press" {...cardAttributes}>
      {/* 操作ボタンをrole="button"の内側に入れないよう、本文側だけを詳細表示のトリガーにする */}
      {/* Keep the action buttons outside the role="button" region; only the body opens the detail modal */}
      <div
        className="prompt-card__main"
        role="button"
        tabIndex={0}
        aria-label={t("promptShare.showDetails", { title })}
        onClick={onOpenDetail}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onOpenDetail();
          }
        }}
      >
        <div className="prompt-card__header">
          <div className="prompt-card__badges">
            {savedBadge}
            {categoryLabel ? (
              <span className="prompt-card__category-pill">
                <i className="bi bi-hash" aria-hidden="true"></i>
                <span>{categoryLabel}</span>
              </span>
            ) : null}
            {/* フォーマット軸をCSSクラスに反映し、アイコンとラベルをレジストリから決定する */}
            {/* Apply content-format class and resolve icon/label from the registry */}
            <span className={`prompt-card__type-pill prompt-card__type-pill--format prompt-card__type-pill--${formatValue}`}>
              <i className={`bi ${getPromptFormatIconClass(formatValue)}`} aria-hidden="true"></i>
              <span>{getPromptFormatLabel(formatValue, locale)}</span>
            </span>
          </div>
          <time className="prompt-card__created-at" dateTime={dateTime}>
            <i className="bi bi-calendar3" aria-hidden="true"></i>
            {dateLabel}
          </time>
        </div>
        <h3 className="prompt-card__title" title={title}>{truncateTitle(title)}</h3>
        <p className="prompt-card__content" title={contentSource}>
          {contentPreview || t("promptShare.noContent")}
        </p>
      </div>
      <div className="prompt-card__footer">
        <div className="prompt-actions">{actions}</div>
      </div>
    </article>
  );
}

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
  const { locale, t } = useTranslation();
  const promptId = asId(prompt.id);
  const isSkill = prompt.contentFormat === "skill";
  const categoryLabel = getCategoryLabelOrFallback(normalizePreviewText(prompt.category), undefined, locale);
  const createdAtLabel = prompt.createdAt ? toDisplayDate(prompt.createdAt) : t("promptShare.dateUnknown");

  return (
    <SettingsPromptCard
      cardAttributes={{ "data-prompt-id": promptId }}
      title={prompt.title}
      contentSource={isSkill ? prompt.skillMarkdown : prompt.content}
      contentFormat={prompt.contentFormat}
      categoryLabel={categoryLabel}
      dateLabel={createdAtLabel}
      dateTime={prompt.createdAt}
      onOpenDetail={() => onPreview(prompt)}
      actions={
        <>
          <button
            type="button"
            className="prompt-action-btn prompt-action-btn--edit cc-press"
            onClick={() => onEdit(prompt)}
            aria-label={t("common.edit")}
            data-tooltip={t("common.edit")}
            data-tooltip-placement="top"
          >
            <i className="bi bi-pencil-square"></i>
          </button>
          <button
            type="button"
            className="prompt-action-btn prompt-action-btn--delete cc-press"
            onClick={() => onDelete(prompt)}
            aria-label={t("common.delete")}
            data-tooltip={t("common.delete")}
            data-tooltip-placement="top"
          >
            <i className="bi bi-trash3"></i>
          </button>
        </>
      }
    />
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
  const { locale, t } = useTranslation();
  const entryId = asId(entry.id);
  const isSkill = entry.contentFormat === "skill";
  // カテゴリ未設定時はバッジ自体を出さないため、フォールバックなしでラベルを解決する
  // Resolve the label without a fallback: an unset category hides the badge entirely
  const categoryLabel = getCategoryLabel(normalizePreviewText(entry.category), locale);
  const likedAtLabel = entry.likedAt ? toDisplayDate(entry.likedAt) : t("promptShare.dateUnknown");

  return (
    <SettingsPromptCard
      cardAttributes={{ "data-liked-prompt-id": entryId }}
      title={entry.title}
      contentSource={isSkill ? entry.skillMarkdown : entry.content}
      contentFormat={entry.contentFormat}
      categoryLabel={categoryLabel}
      savedBadge={
        <span className="prompt-card__type-pill prompt-card__type-pill--saved">
          <i className="bi bi-heart-fill" aria-hidden="true"></i>
          <span>{t("promptShare.liked")}</span>
        </span>
      }
      dateLabel={likedAtLabel}
      dateTime={entry.likedAt}
      onOpenDetail={() => onPreview(entry)}
      actions={
        <button
          type="button"
          className="prompt-action-btn prompt-action-btn--delete cc-press"
          onClick={() => onDelete(entry)}
          aria-label={t("promptShare.unlike")}
          data-tooltip={t("promptShare.unlike")}
          data-tooltip-placement="top"
        >
          <i className="bi bi-heartbreak"></i>
        </button>
      }
    />
  );
}
