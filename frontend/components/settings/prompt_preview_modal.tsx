import { getCategoryLabelOrFallback } from "../../scripts/prompt_share/prompt_category_registry";
import { toDisplayDate } from "../../scripts/user/settings/utils";

// 設定画面のカードから閲覧するプロンプト詳細に必要な共通データ
// Shared prompt data needed by the settings-card preview modal
export type PromptPreview = {
  title: string;
  content: string;
  contentFormat: string;
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
  const categoryLabel = getCategoryLabelOrFallback(prompt.category);
  const createdAtLabel = prompt.createdAt ? toDisplayDate(prompt.createdAt) : "日時未設定";
  const isSkill = prompt.contentFormat === "skill";
  const promptBody = isSkill ? prompt.skillMarkdown : prompt.content;
  const promptBodyLabel = isSkill ? "SKILL定義" : "プロンプト本文";
  const hasExamples = !isSkill && Boolean(prompt.inputExamples.trim() || prompt.outputExamples.trim());
  const sourceLabel = source === "authored" ? "投稿したプロンプト" : "いいねしたプロンプト";

  return (
    <div
      id="promptPreviewModal"
      className="prompt-preview-modal"
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-labelledby="promptPreviewModalTitle"
      onClick={(event) => {
        // 背景領域だけをクリックした場合に閉じ、本文の選択操作は妨げない
        // Only close from the backdrop, leaving text-selection inside untouched
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="prompt-preview-modal__dialog" role="document">
        <header className="prompt-preview-modal__header">
          <div className="prompt-preview-modal__heading">
            <span className="prompt-preview-modal__icon" aria-hidden="true">
              <i className="bi bi-file-earmark-text"></i>
            </span>
            <div>
              <p className="prompt-preview-modal__eyebrow">{sourceLabel}</p>
              <h2 id="promptPreviewModalTitle">{prompt.title || "無題のプロンプト"}</h2>
              <div className="prompt-preview-modal__meta" aria-label="プロンプト情報">
                {isSkill ? (
                  <span>
                    <i className="bi bi-code-slash" aria-hidden="true"></i>
                    SKILL
                  </span>
                ) : null}
                <span>
                  <i className="bi bi-tag" aria-hidden="true"></i>
                  {categoryLabel}
                </span>
                <time dateTime={prompt.createdAt}>
                  <i className="bi bi-clock-history" aria-hidden="true"></i>
                  {createdAtLabel}
                </time>
              </div>
            </div>
          </div>
          <button
            type="button"
            className="prompt-preview-modal__close"
            aria-label="詳細を閉じる"
            onClick={onClose}
          >
            <i className="bi bi-x-lg" aria-hidden="true"></i>
          </button>
        </header>

        <div className="prompt-preview-modal__body">
          <section className="prompt-preview-modal__section" aria-labelledby="promptPreviewContentTitle">
            <div className="prompt-preview-modal__section-heading">
              <p>{promptBodyLabel}</p>
              <span>{promptBody.length.toLocaleString("ja-JP")}文字</span>
            </div>
            <p id="promptPreviewContentTitle" className="prompt-preview-modal__content">
              {promptBody || "内容が設定されていません。"}
            </p>
          </section>

          {hasExamples ? (
            <section className="prompt-preview-modal__examples" aria-labelledby="promptPreviewExamplesTitle">
              <div className="prompt-preview-modal__section-heading">
                <p id="promptPreviewExamplesTitle">入出力例</p>
                <span>任意の補足情報</span>
              </div>
              <div className="prompt-preview-modal__example-grid">
                {prompt.inputExamples.trim() ? (
                  <article className="prompt-preview-modal__example">
                    <h3><i className="bi bi-box-arrow-in-right" aria-hidden="true"></i>入力例</h3>
                    <p>{prompt.inputExamples}</p>
                  </article>
                ) : null}
                {prompt.outputExamples.trim() ? (
                  <article className="prompt-preview-modal__example">
                    <h3><i className="bi bi-box-arrow-right" aria-hidden="true"></i>出力例</h3>
                    <p>{prompt.outputExamples}</p>
                  </article>
                ) : null}
              </div>
            </section>
          ) : null}
        </div>

        <footer className="prompt-preview-modal__footer">
          <button type="button" className="prompt-preview-modal__button" onClick={onClose}>
            閉じる
          </button>
        </footer>
      </div>
    </div>
  );
}
