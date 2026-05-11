import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
  type MutableRefObject,
  type RefObject
} from "react";

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
  postSkillMarkdown: string;
  setPostSkillMarkdown: (value: string) => void;
  postSkillPythonScript: string;
  setPostSkillPythonScript: (value: string) => void;
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
  promptPostSkillMarkdownRef: RefObject<HTMLTextAreaElement>;
  promptPostSkillPythonScriptRef: RefObject<HTMLTextAreaElement>;
  promptImageInputRef: RefObject<HTMLInputElement>;
  promptAssistRootRef: RefObject<HTMLDivElement>;
  promptImagePreviewUrl: string;
  promptImagePreviewName: string;
  onReferenceImageChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onClearReferenceImage: () => void;
};

type PromptComposerSelectOption = {
  value: string;
  label: string;
  group?: string;
};

const AI_MODEL_OPTION_GROUPS: { label: string; options: PromptComposerSelectOption[] }[] = [
  {
    label: "OpenAI",
    options: [
      { value: "ChatGPT (GPT-5.4)", label: "ChatGPT (GPT-5.4)" },
      { value: "ChatGPT (GPT-5.4 mini)", label: "ChatGPT (GPT-5.4 mini)" },
      { value: "ChatGPT (o3)", label: "ChatGPT (o3)" },
      { value: "ChatGPT (GPT-4o)", label: "ChatGPT (GPT-4o)" }
    ]
  },
  {
    label: "Anthropic",
    options: [
      { value: "Claude Opus 4.6", label: "Claude Opus 4.6" },
      { value: "Claude Sonnet 4.6", label: "Claude Sonnet 4.6" },
      { value: "Claude Haiku 4.5", label: "Claude Haiku 4.5" },
      { value: "Claude 3.7 Sonnet", label: "Claude 3.7 Sonnet" }
    ]
  },
  {
    label: "Google",
    options: [
      { value: "Gemini 3.1 Pro", label: "Gemini 3.1 Pro" },
      { value: "Gemini 3.1 Flash", label: "Gemini 3.1 Flash" },
      { value: "Gemini 2.0 Flash", label: "Gemini 2.0 Flash" }
    ]
  },
  {
    label: "Meta",
    options: [
      { value: "Llama 4 Maverick", label: "Llama 4 Maverick" },
      { value: "Llama 4 Scout", label: "Llama 4 Scout" }
    ]
  },
  {
    label: "DeepSeek",
    options: [
      { value: "DeepSeek-R1", label: "DeepSeek-R1" },
      { value: "DeepSeek-V3", label: "DeepSeek-V3" }
    ]
  },
  {
    label: "xAI",
    options: [{ value: "Grok 3", label: "Grok 3" }]
  },
  {
    label: "画像生成",
    options: [
      { value: "Midjourney", label: "Midjourney" },
      { value: "Stable Diffusion", label: "Stable Diffusion" },
      { value: "FLUX", label: "FLUX" },
      { value: "DALL-E 3", label: "DALL-E 3" }
    ]
  }
];

const AI_MODEL_OPTIONS: PromptComposerSelectOption[] = [
  { value: "", label: "未設定" },
  ...AI_MODEL_OPTION_GROUPS.flatMap((group) =>
    group.options.map((option) => ({ ...option, group: group.label }))
  ),
  { value: "その他", label: "その他" }
];

function PromptComposerSelect({
  selectId,
  nativeRef,
  value,
  options,
  groupedOptions,
  onChange,
  onAfterChange,
  required = false,
  menuLabel
}: {
  selectId: string;
  nativeRef: RefObject<HTMLSelectElement>;
  value: string;
  options: PromptComposerSelectOption[];
  groupedOptions?: { label: string; options: PromptComposerSelectOption[] }[];
  onChange: (value: string) => void;
  onAfterChange: () => void;
  required?: boolean;
  menuLabel: string;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [isOpen, setIsOpen] = useState(false);
  const selectedIndex = Math.max(
    0,
    options.findIndex((option) => option.value === value)
  );
  const [activeIndex, setActiveIndex] = useState(selectedIndex);
  const selectedLabel = options[selectedIndex]?.label ?? value;
  const listboxId = `${selectId}-menu`;

  useEffect(() => {
    setActiveIndex(selectedIndex);
  }, [selectedIndex]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    optionRefs.current[activeIndex]?.focus();
  }, [activeIndex, isOpen]);

  const selectOption = (index: number) => {
    const option = options[index];
    if (!option) {
      return;
    }
    onChange(option.value);
    onAfterChange();
    setIsOpen(false);
    triggerRef.current?.focus();
  };

  const openAt = (index: number) => {
    setActiveIndex(Math.min(Math.max(index, 0), options.length - 1));
    setIsOpen(true);
  };

  const handleTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      openAt(isOpen ? activeIndex + 1 : selectedIndex);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      openAt(isOpen ? activeIndex - 1 : selectedIndex);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openAt(selectedIndex);
    }
  };

  const handleOptionKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      openAt(index + 1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      openAt(index - 1);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      openAt(0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      openAt(options.length - 1);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setIsOpen(false);
      triggerRef.current?.focus();
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectOption(index);
    }
  };

  let optionIndex = 0;

  return (
    <div ref={rootRef} className={`prompt-composer-select${isOpen ? " is-open" : ""}`.trim()}>
      <select
        id={selectId}
        className="prompt-composer-select-native"
        required={required}
        ref={nativeRef}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
          onAfterChange();
        }}
      >
        {groupedOptions ? (
          <>
            <option value="">未設定</option>
            {groupedOptions.map((group) => (
              <optgroup key={group.label} label={group.label}>
                {group.options.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </optgroup>
            ))}
            <option value="その他">その他</option>
          </>
        ) : (
          options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))
        )}
      </select>

      <button
        ref={triggerRef}
        type="button"
        className="prompt-composer-select__trigger"
        aria-haspopup="listbox"
        aria-expanded={isOpen ? "true" : "false"}
        aria-controls={listboxId}
        aria-label={menuLabel}
        onClick={() => {
          setActiveIndex(selectedIndex);
          setIsOpen((previous) => !previous);
        }}
        onKeyDown={handleTriggerKeyDown}
      >
        <span className="prompt-composer-select__label">{selectedLabel}</span>
        <i className="bi bi-chevron-down prompt-composer-select__chevron"></i>
      </button>

      <div className="prompt-composer-select__menu" id={listboxId} role="listbox" aria-label={menuLabel}>
        {groupedOptions ? (
          <>
            <PromptComposerSelectOptionButton
              index={optionIndex++}
              option={options[0]}
              value={value}
              optionRefs={optionRefs}
              activeIndex={activeIndex}
              onSelect={selectOption}
              onKeyDown={handleOptionKeyDown}
            />
            {groupedOptions.map((group) => (
              <div key={group.label} className="prompt-composer-select__group">
                <div className="prompt-composer-select__group-label">{group.label}</div>
                {group.options.map((option) => (
                  <PromptComposerSelectOptionButton
                    key={option.value}
                    index={optionIndex++}
                    option={option}
                    value={value}
                    optionRefs={optionRefs}
                    activeIndex={activeIndex}
                    onSelect={selectOption}
                    onKeyDown={handleOptionKeyDown}
                  />
                ))}
              </div>
            ))}
            <PromptComposerSelectOptionButton
              index={optionIndex++}
              option={options[options.length - 1]}
              value={value}
              optionRefs={optionRefs}
              activeIndex={activeIndex}
              onSelect={selectOption}
              onKeyDown={handleOptionKeyDown}
            />
          </>
        ) : (
          options.map((option, index) => (
            <PromptComposerSelectOptionButton
              key={option.value}
              index={index}
              option={option}
              value={value}
              optionRefs={optionRefs}
              activeIndex={activeIndex}
              onSelect={selectOption}
              onKeyDown={handleOptionKeyDown}
            />
          ))
        )}
      </div>
    </div>
  );
}

function PromptComposerSelectOptionButton({
  index,
  option,
  value,
  optionRefs,
  activeIndex,
  onSelect,
  onKeyDown
}: {
  index: number;
  option: PromptComposerSelectOption;
  value: string;
  optionRefs: MutableRefObject<Array<HTMLButtonElement | null>>;
  activeIndex: number;
  onSelect: (index: number) => void;
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>, index: number) => void;
}) {
  const selected = value === option.value;

  return (
    <button
      ref={(node) => {
        optionRefs.current[index] = node;
      }}
      type="button"
      className={`prompt-composer-select__option${selected ? " is-selected" : ""}`.trim()}
      role="option"
      aria-selected={selected ? "true" : "false"}
      tabIndex={activeIndex === index ? 0 : -1}
      onClick={() => {
        onSelect(index);
      }}
      onKeyDown={(event) => {
        onKeyDown(event, index);
      }}
    >
      <span className="prompt-composer-select__option-label">{option.label}</span>
      {selected ? <i className="bi bi-check-lg prompt-composer-select__check"></i> : null}
    </button>
  );
}

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
  postSkillMarkdown,
  setPostSkillMarkdown,
  postSkillPythonScript,
  setPostSkillPythonScript,
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
  promptPostSkillMarkdownRef,
  promptPostSkillPythonScriptRef,
  promptImageInputRef,
  promptAssistRootRef,
  promptImagePreviewUrl,
  promptImagePreviewName,
  onReferenceImageChange,
  onClearReferenceImage
}: PromptShareComposerModalProps) {
  const categorySelectOptions = categoryOptions.map((category) => ({
    value: category,
    label: category
  }));

  const [showSkillInfo, setShowSkillInfo] = useState(false);
  useEffect(() => {
    setShowSkillInfo(false);
  }, [promptType]);

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
                本文の下書きはAI補助で作ることもできます。投稿すると一覧に表示され、他のユーザーから参照できます。
              </p>
            </div>
          </div>

          <form className="post-form" id="postForm" onSubmit={onSubmit}>
            <section className="composer-section composer-section--primary" aria-labelledby="composerBasicsTitle">
              <div className="composer-section__header">
                <div>
                  <p className="composer-section__eyebrow">Basics</p>
                  <h3 id="composerBasicsTitle">投稿の基本情報</h3>
                </div>
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

                  <label className={`prompt-type-option${promptType === "skill" ? " prompt-type-option--active" : ""}`}>
                    <input
                      type="radio"
                      name="prompt-type"
                      value="skill"
                      checked={promptType === "skill"}
                      onChange={(event) => {
                        setPromptType(normalizePromptType(event.target.value));
                      }}
                    />
                    <span className="prompt-type-option__icon">
                      <i className="bi bi-code-slash"></i>
                    </span>
                    <span className="prompt-type-option__body">
                      <strong>SKILL</strong>
                      <small>Claude Code / Codex CLI で使う手順・テンプレートを共有</small>
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
                  <PromptComposerSelect
                    selectId="prompt-category"
                    nativeRef={promptPostCategorySelectRef}
                    value={postCategory}
                    options={categorySelectOptions}
                    menuLabel="カテゴリを選択"
                    onChange={setPostCategory}
                    onAfterChange={updatePromptFeedbackErrorIfNeeded}
                  />
                </div>
              </div>
            </section>

            <section className="composer-section composer-section--content" aria-labelledby="composerContentTitle">
              <div className="composer-section__header">
                <div>
                  <p className="composer-section__eyebrow">{promptType === "skill" ? "SKILL" : "Content"}</p>
                  <div className="composer-section__title-row">
                    <h3 id="composerContentTitle">
                      {promptType === "skill" ? "SKILL作成サポート" : "プロンプト本文"}
                    </h3>
                    {promptType === "skill" ? (
                      <button
                        type="button"
                        className={`composer-info-btn${showSkillInfo ? " is-active" : ""}`}
                        aria-label="SKILLについての説明を表示"
                        aria-expanded={showSkillInfo}
                        onClick={() => { setShowSkillInfo((v) => !v); }}
                      >
                        <i className="bi bi-info-circle" aria-hidden="true"></i>
                      </button>
                    ) : null}
                  </div>
                </div>
                {promptType !== "skill" ? (
                  <p className="composer-section__description">
                    指示文の意図や条件が明確に伝わるように、本文を先にまとめます。
                  </p>
                ) : showSkillInfo ? (
                  <p className="composer-section__description">
                    SKILLではAI補助を使ってMarkdown定義と必要なPythonスクリプトを作成できます。
                  </p>
                ) : null}
              </div>

              <div className="form-group" style={{ display: promptType === "skill" ? "none" : "" }}>
                <label htmlFor="prompt-content">プロンプト内容</label>
                <span className="form-group__hint">役割、前提条件、出力形式まで書くと再利用しやすくなります。</span>
                <textarea
                  id="prompt-content"
                  rows={6}
                  placeholder="具体的なプロンプト内容を入力"
                  required={promptType !== "skill"}
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
                  <PromptComposerSelect
                    selectId="prompt-ai-model"
                    nativeRef={promptPostAiModelSelectRef}
                    value={postAiModel}
                    options={AI_MODEL_OPTIONS}
                    groupedOptions={AI_MODEL_OPTION_GROUPS}
                    menuLabel="使用AIモデルを選択"
                    onChange={setPostAiModel}
                    onAfterChange={updatePromptFeedbackErrorIfNeeded}
                  />
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

              <div id="skillPromptFields" className="skill-prompt-fields" hidden={promptType !== "skill"}>
                <div className="form-group">
                  <label htmlFor="prompt-skill-markdown">SKILL定義（Markdown）</label>
                  <span className="form-group__hint">
                    SKILLの使い方、ルール、入出力例を Markdown で記述してください。
                  </span>
                  <textarea
                    id="prompt-skill-markdown"
                    rows={10}
                    placeholder={"# SKILL名\n\n## 目的\n- ...\n\n## 手順\n1. ..."}
                    required={promptType === "skill"}
                    ref={promptPostSkillMarkdownRef}
                    value={postSkillMarkdown}
                    onChange={(event) => {
                      setPostSkillMarkdown(event.target.value);
                      updatePromptFeedbackErrorIfNeeded();
                    }}
                  ></textarea>
                </div>

                <div className="form-group">
                  <label htmlFor="prompt-skill-python-script">追加 Python スクリプト（任意）</label>
                  <span className="form-group__hint">
                    必要であれば補助スクリプトを貼り付けてください（.py の内容をそのまま記載）。
                  </span>
                  <textarea
                    id="prompt-skill-python-script"
                    rows={8}
                    placeholder={"def run(input_text: str) -> str:\n    return input_text"}
                    ref={promptPostSkillPythonScriptRef}
                    value={postSkillPythonScript}
                    onChange={(event) => {
                      setPostSkillPythonScript(event.target.value);
                      updatePromptFeedbackErrorIfNeeded();
                    }}
                  ></textarea>
                </div>
              </div>
            </section>

            <section className="composer-section" aria-labelledby="composerExamplesTitle" hidden={promptType === "skill"}>
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
