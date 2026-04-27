import type { ChangeEvent, FormEvent, RefObject } from "react";

import { normalizePromptType } from "../../scripts/prompt_share/formatters";
import type { PromptType } from "../../scripts/prompt_share/types";
import type { PromptPostStatus } from "./prompt_share_page_types";

type PromptShareComposerModalProps = {
  isOpen: boolean;
  isPostSubmitting: boolean;
  postModalRef: RefObject<HTMLDivElement>;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  promptType: PromptType;
  setPromptType: (value: PromptType) => void;
  postTitle: string;
  setPostTitle: (value: string) => void;
  postCategory: string;
  setPostCategory: (value: string) => void;
  postContent: string;
  setPostContent: (value: string) => void;
  postAuthor: string;
  setPostAuthor: (value: string) => void;
  setHasAutoFilledAuthor: (value: boolean) => void;
  postAiModel: string;
  setPostAiModel: (value: string) => void;
  guardrailEnabled: boolean;
  setGuardrailEnabled: (value: boolean) => void;
  postInputExample: string;
  setPostInputExample: (value: string) => void;
  postOutputExample: string;
  setPostOutputExample: (value: string) => void;
  updatePromptFeedbackErrorIfNeeded: () => void;
  categoryOptions: string[];
  promptPostStatus: PromptPostStatus;
  promptPostTitleInputRef: RefObject<HTMLInputElement>;
  promptPostCategorySelectRef: RefObject<HTMLSelectElement>;
  promptPostContentTextareaRef: RefObject<HTMLTextAreaElement>;
  promptPostAuthorInputRef: RefObject<HTMLInputElement>;
  promptPostAiModelSelectRef: RefObject<HTMLSelectElement>;
  promptPostInputExamplesRef: RefObject<HTMLTextAreaElement>;
  promptPostOutputExamplesRef: RefObject<HTMLTextAreaElement>;
  promptImageInputRef: RefObject<HTMLInputElement>;
  promptAssistRootRef: RefObject<HTMLDivElement>;
  promptImagePreviewUrl: string;
  promptImagePreviewName: string;
  onReferenceImageChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onClearReferenceImage: () => void;
};

export function PromptShareComposerModal({
  isOpen,
  isPostSubmitting,
  postModalRef,
  onClose,
  onSubmit,
  promptType,
  setPromptType,
  postTitle,
  setPostTitle,
  postCategory,
  setPostCategory,
  postContent,
  setPostContent,
  postAuthor,
  setPostAuthor,
  setHasAutoFilledAuthor,
  postAiModel,
  setPostAiModel,
  guardrailEnabled,
  setGuardrailEnabled,
  postInputExample,
  setPostInputExample,
  postOutputExample,
  setPostOutputExample,
  updatePromptFeedbackErrorIfNeeded,
  categoryOptions,
  promptPostStatus,
  promptPostTitleInputRef,
  promptPostCategorySelectRef,
  promptPostContentTextareaRef,
  promptPostAuthorInputRef,
  promptPostAiModelSelectRef,
  promptPostInputExamplesRef,
  promptPostOutputExamplesRef,
  promptImageInputRef,
  promptAssistRootRef,
  promptImagePreviewUrl,
  promptImagePreviewName,
  onReferenceImageChange,
  onClearReferenceImage
}: PromptShareComposerModalProps) {
  return (
    <div
      id="postModal"
      className={`post-modal${isOpen ? " show" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-labelledby="postModalTitle"
      aria-hidden={isOpen ? "false" : "true"}
      data-submitting={isPostSubmitting ? "true" : "false"}
      ref={postModalRef}
    >
      <div className="post-modal-content post-modal-content--composer" tabIndex={-1}>
        <button type="button" className="close-btn" aria-label="投稿モーダルを閉じる" onClick={onClose}>
          &times;
        </button>

        <div className="post-modal-scroll">
          <div className="composer-hero">
            <div className="composer-hero__copy">
              <p className="composer-hero__eyebrow">Prompt Share Composer</p>
              <h2 id="postModalTitle">新しいプロンプトを投稿</h2>
              <p className="post-modal-lead">
                AI 補助を使いながら、公開用の見やすさと使いやすさまでその場で仕上げます。
              </p>
            </div>
            <div className="composer-hero__chips" aria-hidden="true">
              <span>Searchable</span>
              <span>Polished</span>
              <span>Share Ready</span>
            </div>
          </div>

          <form className="post-form" id="postForm" onSubmit={onSubmit}>
            <section className="composer-section composer-section--primary" aria-labelledby="composerBasicsTitle">
              <div className="composer-section__header">
                <div>
                  <p className="composer-section__eyebrow">Basics</p>
                  <h3 id="composerBasicsTitle">投稿の基本情報</h3>
                </div>
                <p className="composer-section__description">
                  まずは投稿タイプとタイトルを決めて、一覧で見つけやすい形に整えます。
                </p>
              </div>

              <div className="form-group">
                <label>投稿タイプ</label>
                <div className="prompt-type-toggle" role="radiogroup" aria-label="投稿タイプを選択">
                  <label className={`prompt-type-option${promptType === "text" ? " prompt-type-option--active" : ""}`}>
                    <input
                      type="radio"
                      name="prompt-type"
                      value="text"
                      checked={promptType === "text"}
                      onChange={(event) => {
                        setPromptType(normalizePromptType(event.target.value));
                      }}
                    />
                    <span className="prompt-type-option__icon">
                      <i className="bi bi-chat-square-text"></i>
                    </span>
                    <span className="prompt-type-option__body">
                      <strong>通常プロンプト</strong>
                      <small>文章生成、要約、相談、分析など</small>
                    </span>
                  </label>

                  <label className={`prompt-type-option${promptType === "image" ? " prompt-type-option--active" : ""}`}>
                    <input
                      type="radio"
                      name="prompt-type"
                      value="image"
                      checked={promptType === "image"}
                      onChange={(event) => {
                        setPromptType(normalizePromptType(event.target.value));
                      }}
                    />
                    <span className="prompt-type-option__icon">
                      <i className="bi bi-image"></i>
                    </span>
                    <span className="prompt-type-option__body">
                      <strong>画像生成プロンプト</strong>
                      <small>Midjourney、Stable Diffusion、Flux など向け</small>
                    </span>
                  </label>
                </div>
              </div>

              <div className="composer-field-grid composer-field-grid--two">
                <div className="form-group">
                  <label htmlFor="prompt-title">タイトル</label>
                  <span className="form-group__hint">用途が伝わる短い名前にすると保存後に探しやすくなります。</span>
                  <input
                    type="text"
                    id="prompt-title"
                    placeholder="プロンプトのタイトルを入力"
                    required
                    ref={promptPostTitleInputRef}
                    value={postTitle}
                    onChange={(event) => {
                      setPostTitle(event.target.value);
                      updatePromptFeedbackErrorIfNeeded();
                    }}
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="prompt-category">カテゴリ</label>
                  <span className="form-group__hint">検索や絞り込みに使われるため、目的に近いものを選択してください。</span>
                  <select
                    id="prompt-category"
                    required
                    ref={promptPostCategorySelectRef}
                    value={postCategory}
                    onChange={(event) => {
                      setPostCategory(event.target.value);
                      updatePromptFeedbackErrorIfNeeded();
                    }}
                  >
                    {categoryOptions.map((category) => (
                      <option key={category} value={category}>
                        {category}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </section>

            <section className="composer-section composer-section--content" aria-labelledby="composerContentTitle">
              <div className="composer-section__header">
                <div>
                  <p className="composer-section__eyebrow">Content</p>
                  <h3 id="composerContentTitle">プロンプト本文</h3>
                </div>
                <p className="composer-section__description">
                  指示文の意図や条件が明確に伝わるように、本文を先にまとめます。
                </p>
              </div>

              <div className="form-group">
                <label htmlFor="prompt-content">プロンプト内容</label>
                <span className="form-group__hint">役割、前提条件、出力形式まで書くと再利用しやすくなります。</span>
                <textarea
                  id="prompt-content"
                  rows={6}
                  placeholder="具体的なプロンプト内容を入力"
                  required
                  ref={promptPostContentTextareaRef}
                  value={postContent}
                  onChange={(event) => {
                    setPostContent(event.target.value);
                    updatePromptFeedbackErrorIfNeeded();
                  }}
                ></textarea>
              </div>

              <div id="sharedPromptAssistRoot" ref={promptAssistRootRef}></div>
              <p
                id="promptPostStatus"
                className="composer-status"
                hidden={!promptPostStatus.message}
                data-variant={promptPostStatus.variant}
              >
                {promptPostStatus.message}
              </p>
            </section>

            <section className="composer-section" aria-labelledby="composerMetaTitle">
              <div className="composer-section__header">
                <div>
                  <p className="composer-section__eyebrow">Details</p>
                  <h3 id="composerMetaTitle">投稿設定</h3>
                </div>
                <p className="composer-section__description">
                  投稿者名や使用モデルを添えると、利用者が使いどころを判断しやすくなります。
                </p>
              </div>

              <div className="composer-field-grid composer-field-grid--two">
                <div className="form-group">
                  <label htmlFor="prompt-author">投稿者名</label>
                  <span className="form-group__hint">ニックネームやチーム名など、公開してよい表示名を使ってください。</span>
                  <input
                    type="text"
                    id="prompt-author"
                    placeholder="ニックネームなど"
                    required
                    ref={promptPostAuthorInputRef}
                    value={postAuthor}
                    onChange={(event) => {
                      setPostAuthor(event.target.value);
                      setHasAutoFilledAuthor(false);
                      updatePromptFeedbackErrorIfNeeded();
                    }}
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="prompt-ai-model">使用AIモデル（任意）</label>
                  <span className="form-group__hint">このプロンプトを試したモデルを残すと、再現条件の共有に役立ちます。</span>
                  <select
                    id="prompt-ai-model"
                    ref={promptPostAiModelSelectRef}
                    value={postAiModel}
                    onChange={(event) => {
                      setPostAiModel(event.target.value);
                      updatePromptFeedbackErrorIfNeeded();
                    }}
                  >
                    <option value="">未設定</option>
                    <optgroup label="OpenAI">
                      <option value="ChatGPT (GPT-5.4)">ChatGPT (GPT-5.4)</option>
                      <option value="ChatGPT (GPT-5.4 mini)">ChatGPT (GPT-5.4 mini)</option>
                      <option value="ChatGPT (o3)">ChatGPT (o3)</option>
                      <option value="ChatGPT (GPT-4o)">ChatGPT (GPT-4o)</option>
                    </optgroup>
                    <optgroup label="Anthropic">
                      <option value="Claude Opus 4.6">Claude Opus 4.6</option>
                      <option value="Claude Sonnet 4.6">Claude Sonnet 4.6</option>
                      <option value="Claude Haiku 4.5">Claude Haiku 4.5</option>
                      <option value="Claude 3.7 Sonnet">Claude 3.7 Sonnet</option>
                    </optgroup>
                    <optgroup label="Google">
                      <option value="Gemini 3.1 Pro">Gemini 3.1 Pro</option>
                      <option value="Gemini 3.1 Flash">Gemini 3.1 Flash</option>
                      <option value="Gemini 2.0 Flash">Gemini 2.0 Flash</option>
                    </optgroup>
                    <optgroup label="Meta">
                      <option value="Llama 4 Maverick">Llama 4 Maverick</option>
                      <option value="Llama 4 Scout">Llama 4 Scout</option>
                    </optgroup>
                    <optgroup label="DeepSeek">
                      <option value="DeepSeek-R1">DeepSeek-R1</option>
                      <option value="DeepSeek-V3">DeepSeek-V3</option>
                    </optgroup>
                    <optgroup label="xAI">
                      <option value="Grok 3">Grok 3</option>
                    </optgroup>
                    <optgroup label="画像生成">
                      <option value="Midjourney">Midjourney</option>
                      <option value="Stable Diffusion">Stable Diffusion</option>
                      <option value="FLUX">FLUX</option>
                      <option value="DALL-E 3">DALL-E 3</option>
                    </optgroup>
                    <option value="その他">その他</option>
                  </select>
                </div>
              </div>

              <div id="imagePromptFields" className="image-prompt-fields" hidden={promptType !== "image"}>
                <div className="form-group">
                  <label htmlFor="prompt-reference-image">作例画像（任意・1枚）</label>
                  <span className="form-group__hint">画像生成系の投稿では、完成イメージを添えると意図が伝わりやすくなります。</span>
                  <label className="image-upload-field" htmlFor="prompt-reference-image">
                    <input
                      type="file"
                      id="prompt-reference-image"
                      accept="image/png,image/jpeg,image/webp,image/gif"
                      ref={promptImageInputRef}
                      onChange={onReferenceImageChange}
                    />
                    <span className="image-upload-field__icon">
                      <i className="bi bi-cloud-arrow-up"></i>
                    </span>
                    <span className="image-upload-field__copy">
                      <strong>画像をアップロード</strong>
                      <small>PNG / JPG / WebP / GIF、5MBまで、1枚のみ</small>
                    </span>
                  </label>

                  <div id="promptImagePreview" className="prompt-image-preview" hidden={!promptImagePreviewUrl}>
                    <img id="promptImagePreviewImg" src={promptImagePreviewUrl} alt="アップロード画像のプレビュー" />
                    <div className="prompt-image-preview__meta">
                      <span id="promptImagePreviewName">{promptImagePreviewName}</span>
                      <button
                        type="button"
                        id="promptImageClearButton"
                        className="prompt-image-clear-btn"
                        onClick={onClearReferenceImage}
                      >
                        <i className="bi bi-x-lg"></i>
                        <span>画像を外す</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <section className="composer-section" aria-labelledby="composerExamplesTitle">
              <div className="composer-section__header">
                <div>
                  <p className="composer-section__eyebrow">Examples</p>
                  <h3 id="composerExamplesTitle">利用例</h3>
                </div>
                <p className="composer-section__description">
                  必須ではありませんが、入力例と出力例があると他のユーザーがそのまま試せます。
                </p>
              </div>

              <div className="form-group form-group--toggle">
                <label className="composer-toggle" htmlFor="guardrail-checkbox">
                  <input
                    type="checkbox"
                    id="guardrail-checkbox"
                    checked={guardrailEnabled}
                    onChange={(event) => {
                      setGuardrailEnabled(event.target.checked);
                    }}
                  />
                  <span className="composer-toggle__copy">
                    <strong>入出力例を追加する</strong>
                    <small>
                      保存・再利用しやすい投稿にするため、プロンプトの使い方を例で添えます。
                    </small>
                  </span>
                </label>
              </div>

              <div id="guardrail-fields" style={{ display: guardrailEnabled ? "block" : "none" }}>
                <div className="composer-field-grid">
                  <div className="form-group">
                    <label htmlFor="prompt-input-example">入力例（プロンプト内容とは別にしてください）</label>
                    <textarea
                      id="prompt-input-example"
                      rows={3}
                      placeholder="例: 夏休みの思い出をテーマにした短いエッセイを書いてください。"
                      ref={promptPostInputExamplesRef}
                      value={postInputExample}
                      onChange={(event) => {
                        setPostInputExample(event.target.value);
                        updatePromptFeedbackErrorIfNeeded();
                      }}
                    ></textarea>
                  </div>
                  <div className="form-group">
                    <label htmlFor="prompt-output-example">出力例</label>
                    <textarea
                      id="prompt-output-example"
                      rows={3}
                      placeholder="例: 夏休みのある日、私は家族と一緒に海辺へ出かけました。波の音と潮風に包まれながら、子供の頃の記憶がよみがえり、心が温かくなりました。その日は一生忘れられない、宝物のような時間となりました。"
                      ref={promptPostOutputExamplesRef}
                      value={postOutputExample}
                      onChange={(event) => {
                        setPostOutputExample(event.target.value);
                        updatePromptFeedbackErrorIfNeeded();
                      }}
                    ></textarea>
                  </div>
                </div>
              </div>
            </section>

            <div className="composer-footer">
              <p className="composer-footer__note">
                入力内容はそのまま保持されます。送信後に一覧へ反映され、他のユーザーから参照できるようになります。
              </p>
              <button type="submit" className="submit-btn" disabled={isPostSubmitting}>
                <i className={`bi ${isPostSubmitting ? "bi-stars" : "bi-upload"}`}></i>
                {isPostSubmitting ? " 投稿を準備中..." : " 投稿する"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
