import MarkdownContent from "../MarkdownContent";
import { getCategoryLabelOrFallback } from "../../scripts/prompt_share/prompt_category_registry";
import { getPromptReferenceImageUrl } from "../../scripts/prompt_share/formatters";
import { toDisplayDate } from "../../scripts/user/settings/utils";
import { useTranslation } from "../../contexts/locale_context";
import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";

// 設定画面のカードから閲覧するプロンプト詳細に必要な共通データ
// Shared prompt data needed by the settings-card preview modal
export type PromptPreview = {
  title: string;
  content: string;
  description?: string;
  contentFormat: string;
  attachments: Record<string, string>[];
  referenceImageUrl: string;
  skillMarkdown: string;
  category: string;
  inputExamples: string;
  outputExamples: string;
  createdAt?: string;
};

// 投稿・いいねのカードから内容を確認するための閲覧専用モーダル
// Read-only modal for viewing a prompt from authored and liked cards
export function PromptPreviewModal({
  prompt,
  source,
  onClose
}: {
  prompt: PromptPreview;
  source: "authored" | "liked";
  onClose: () => void;
}) {
  const { t, formatNumber } = useTranslation();
  const categoryLabel = getCategoryLabelOrFallback(prompt.category);
  const createdAtLabel = prompt.createdAt ? toDisplayDate(prompt.createdAt) : t("promptShare.dateUnknown");
  const isSkill = prompt.contentFormat === "skill";
  const promptBody = isSkill ? prompt.skillMarkdown : prompt.content;
  const promptBodyLabel = isSkill ? t("promptShare.skillDefinition") : t("promptShare.body");
  const imageUrl = getPromptReferenceImageUrl(prompt);
  const hasExamples = !isSkill && Boolean(prompt.inputExamples.trim() || prompt.outputExamples.trim());
  const sourceLabel = source === "authored" ? t("settings.prompts") : t("settings.likedPrompts");

  return (
    <ModalShell
      isOpen
      onClose={onClose}
      id="promptPreviewModal"
      className="cc-modal prompt-preview-modal"
      labelledBy="promptPreviewModalTitle"
    >
      {/* 読む面。プロンプト共有の詳細モーダルと同じ寸法で組む / A reading sheet sized like the prompt share detail modal */}
      <div className="cc-modal__panel cc-modal__panel--xl cc-modal__panel--reader prompt-preview-modal__dialog" tabIndex={-1}>
        <header className="cc-modal__header prompt-preview-modal__header">
          <div className="cc-modal__heading">
            <h2 className="cc-modal__title" id="promptPreviewModalTitle">{prompt.title || t("promptShare.untitled")}</h2>
            <div className="cc-modal__meta prompt-preview-modal__meta" aria-label={t("promptShare.promptInfo")}>
              {isSkill ? (
                <span>
                  <i className="bi bi-code-slash" aria-hidden="true"></i>
                  SKILL
                </span>
              ) : null}
              <span>
                <i className={`bi ${source === "authored" ? "bi-pencil-square" : "bi-heart"}`} aria-hidden="true"></i>
                {sourceLabel}
              </span>
              <span>
                <i className="bi bi-hash" aria-hidden="true"></i>
                {categoryLabel}
              </span>
              <time dateTime={prompt.createdAt}>
                <i className="bi bi-calendar3" aria-hidden="true"></i>
                {createdAtLabel}
              </time>
            </div>
          </div>
          <ModalCloseButton label={t("promptShare.closeDetails")} onClick={onClose} />
        </header>

        <div className="cc-modal__body prompt-preview-modal__body">
          {imageUrl ? (
            <figure className="prompt-preview-modal__image">
              <img
                src={imageUrl}
                alt={t("promptShare.exampleImageAlt", { title: prompt.title })}
                decoding="async"
              />
            </figure>
          ) : null}

          {prompt.description?.trim() ? (
            <section className="cc-modal__section prompt-preview-modal__section prompt-preview-modal__description" aria-labelledby="promptPreviewDescriptionTitle">
              <div className="cc-modal__section-head">
                <p className="cc-modal__section-title" id="promptPreviewDescriptionTitle">{t("promptShare.description")}</p>
              </div>
              <p>{prompt.description}</p>
            </section>
          ) : null}

          <section className="cc-modal__section prompt-preview-modal__section" aria-labelledby="promptPreviewContentTitle">
            <div className="cc-modal__section-head">
              <p className="cc-modal__section-title">{promptBodyLabel}</p>
              <span className="cc-modal__section-meta">{t("promptShare.characters", { count: formatNumber(promptBody.length) })}</span>
            </div>
            {/* 本文はMarkdown記法を含む可能性があるため、フォーマット軸に関わらず常にMarkdownとして整形する */}
            {/* The body may contain Markdown syntax, so it is always rendered as Markdown regardless of the format axis */}
            {promptBody ? (
              <MarkdownContent
                id="promptPreviewContentTitle"
                text={promptBody}
                className="cc-modal__prose prompt-preview-modal__content prompt-preview-modal__markdown"
              />
            ) : (
              <p id="promptPreviewContentTitle" className="prompt-preview-modal__content">
                {t("promptShare.noContent")}
              </p>
            )}
          </section>

          {hasExamples ? (
            <section className="cc-modal__section prompt-preview-modal__examples" aria-labelledby="promptPreviewExamplesTitle">
              <div className="cc-modal__section-head">
                <p className="cc-modal__section-title" id="promptPreviewExamplesTitle">{t("promptShare.examples")}</p>
                <span className="cc-modal__section-meta">{t("promptShare.supplemental")}</span>
              </div>
              <div className="cc-modal__example-grid prompt-preview-modal__example-grid">
                {prompt.inputExamples.trim() ? (
                  <article className="cc-modal__example prompt-preview-modal__example">
                    <h3><i className="bi bi-box-arrow-in-right" aria-hidden="true"></i>{t("promptShare.inputExample")}</h3>
                    <p>{prompt.inputExamples}</p>
                  </article>
                ) : null}
                {prompt.outputExamples.trim() ? (
                  <article className="cc-modal__example prompt-preview-modal__example">
                    <h3><i className="bi bi-box-arrow-right" aria-hidden="true"></i>{t("promptShare.outputExample")}</h3>
                    <p>{prompt.outputExamples}</p>
                  </article>
                ) : null}
              </div>
            </section>
          ) : null}
        </div>
      </div>
    </ModalShell>
  );
}
