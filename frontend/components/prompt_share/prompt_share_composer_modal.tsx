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

import {
  ALL_ATTRIBUTE_FIELDS,
  getAttributeFields,
  getContentFormat,
  getMediaType
} from "../../scripts/prompt_share/prompt_type_registry";
import type { ContentFormat, MediaType, PromptResource } from "../../scripts/prompt_share/types";
import type { PromptCategoryOption, PromptPostStatus } from "./prompt_share_page_types";
import { SkillResourceEditor } from "./skill_resource_editor";
import { useTranslation } from "../../contexts/locale_context";
import { getPromptFormatLabel } from "../../scripts/prompt_share/formatters";
import { getCategoryLabelOrFallback } from "../../scripts/prompt_share/prompt_category_registry";

// レジストリ駆動で描画する属性フィールドの、親が用意する状態バインディング。
// State binding (provided by the parent) for a registry-driven attribute field.
export type AttributeBinding = {
  value: string;
  setValue: (value: string) => void;
  ref: RefObject<HTMLTextAreaElement | null>;
};

// 投稿モーダルが親コンポーネントから受け取るすべての状態とハンドラを定義する
// Defines all state and handlers passed down from the parent into the composer modal
type PromptShareComposerModalProps = {
  isOpen: boolean;
  isPostSubmitting: boolean;
  postModalRef: RefObject<HTMLDivElement | null>;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  // 2軸モデル: フォーマット軸 × メディア軸。
  // Two-axis model: content format axis × media type axis.
  contentFormat: ContentFormat;
  setContentFormat: (value: ContentFormat) => void;
  mediaType: MediaType;
  setMediaType: (value: MediaType) => void;
  postTitle: string;
  setPostTitle: (value: string) => void;
  postCategory: string;
  setPostCategory: (value: string) => void;
  postContent: string;
  setPostContent: (value: string) => void;
  postAiModel: string;
  setPostAiModel: (value: string) => void;
  guardrailEnabled: boolean;
  setGuardrailEnabled: (value: boolean) => void;
  postInputExample: string;
  setPostInputExample: (value: string) => void;
  postOutputExample: string;
  setPostOutputExample: (value: string) => void;
  postResources: PromptResource[];
  setPostResources: (resources: PromptResource[]) => void;
  // フォーマット固有の属性フィールド (キー -> 状態バインディング)。
  // Format-specific attribute fields (key -> state binding).
  attributeBindings: Record<string, AttributeBinding>;
  updatePromptFeedbackErrorIfNeeded: () => void;
  categoryOptions: PromptCategoryOption[];
  promptPostStatus: PromptPostStatus;
  promptPostTitleInputRef: RefObject<HTMLInputElement | null>;
  promptPostCategorySelectRef: RefObject<HTMLSelectElement | null>;
  promptPostContentTextareaRef: RefObject<HTMLTextAreaElement | null>;
  promptPostAiModelSelectRef: RefObject<HTMLInputElement | null>;
  promptPostInputExamplesRef: RefObject<HTMLTextAreaElement | null>;
  promptPostOutputExamplesRef: RefObject<HTMLTextAreaElement | null>;
  promptImageInputRef: RefObject<HTMLInputElement | null>;
  promptAssistRootRef: RefObject<HTMLDivElement | null>;
  promptImagePreviewUrl: string;
  promptImagePreviewName: string;
  onReferenceImageChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onClearReferenceImage: () => void;
};

// カスタムセレクトの各選択肢を表す型
// Represents a single option in the custom select dropdown
type PromptComposerSelectOption = {
  value: string;
  label: string;
};

type ComposerPostType = "text-prompt" | "image-prompt" | "skill";

const MAX_PROMPT_TITLE_LENGTH = 255;
const MAX_PROMPT_CONTENT_LENGTH = 30000;

const COMPOSER_POST_TYPES: Array<{
  key: ComposerPostType;
  contentFormat: ContentFormat;
  mediaType: MediaType;
  icon: string;
  labelKey:
    | "promptShare.postType.text-prompt"
    | "promptShare.postType.image-prompt"
    | "promptShare.postType.skill";
  helpKey:
    | "promptShare.postType.text-prompt.help"
    | "promptShare.postType.image-prompt.help"
    | "promptShare.postType.skill.help";
}> = [
  {
    key: "text-prompt", contentFormat: "prompt", mediaType: "text", icon: "bi-chat-square-text",
    labelKey: "promptShare.postType.text-prompt", helpKey: "promptShare.postType.text-prompt.help"
  },
  {
    key: "image-prompt", contentFormat: "prompt", mediaType: "image", icon: "bi-image",
    labelKey: "promptShare.postType.image-prompt", helpKey: "promptShare.postType.image-prompt.help"
  },
  {
    key: "skill", contentFormat: "skill", mediaType: "text", icon: "bi-code-slash",
    labelKey: "promptShare.postType.skill", helpKey: "promptShare.postType.skill.help"
  }
];

// AIモデルの入力候補（datalist）。固定リストではなく自由入力の補助のため、
// ここに無いモデル名を入力してもそのまま投稿できる。
// AI model suggestions for the <datalist>. The field itself is free text, so
// typing a model that isn't listed here still works fine.
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

// ネイティブ<select>とカスタムUIを同期させ、キーボード操作も担うコンポーネント
// Renders a custom accessible dropdown that stays in sync with a hidden native <select>
function PromptComposerSelect({
  selectId,
  nativeRef,
  value,
  options,
  onChange,
  onAfterChange,
  required = false,
  menuLabel,
  isModalOpen
}: {
  selectId: string;
  nativeRef: RefObject<HTMLSelectElement | null>;
  value: string;
  options: PromptComposerSelectOption[];
  onChange: (value: string) => void;
  onAfterChange: () => void;
  required?: boolean;
  menuLabel: string;
  isModalOpen?: boolean;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  // 各選択肢ボタンへのrefを配列で管理し、矢印キーフォーカス移動に使う
  // Holds refs to each option button so arrow-key navigation can call .focus() directly
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [isOpen, setIsOpen] = useState(false);
  const selectedIndex = Math.max(
    0,
    options.findIndex((option) => option.value === value)
  );
  const [activeIndex, setActiveIndex] = useState(selectedIndex);
  const selectedLabel = options[selectedIndex]?.label ?? value;
  const listboxId = `${selectId}-menu`;

  // 外部からvalueが変わったとき、activeIndexを新しい選択位置に追従させる
  // Keep activeIndex in sync when the selected value changes externally
  useEffect(() => {
    setActiveIndex(selectedIndex);
  }, [selectedIndex]);

  // モーダルが閉じられたときにドロップダウンを閉じる。Escapeキーや投稿成功後の自動クローズで
  // モーダルが閉じてもisOpen状態がリセットされず、次回モーダルを開いたときにメニューが
  // 開いたまま表示されてしまう問題を防ぐ
  // Close the dropdown when the parent modal closes to prevent it from reopening in an open state
  useEffect(() => {
    if (isModalOpen === false) {
      setIsOpen(false);
    }
  }, [isModalOpen]);

  // メニューが開いている間だけpointerdownを監視し、外側クリックで閉じる
  // Listen for outside pointer events only while the menu is open to close it on click-away
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

  // activeIndexが変わったとき、対応するオプションボタンにフォーカスを移す
  // Shift DOM focus to the newly active option after arrow-key navigation
  useEffect(() => {
    if (!isOpen) {
      return;
    }
    optionRefs.current[activeIndex]?.focus();
  }, [activeIndex, isOpen]);

  // 選択を確定し、親に通知してメニューを閉じる
  // Commit a selection, notify the parent, and return focus to the trigger
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

  // 指定インデックスでメニューを開き、範囲外のインデックスをクランプする
  // Open the menu at the given index, clamped to valid range
  const openAt = (index: number) => {
    setActiveIndex(Math.min(Math.max(index, 0), options.length - 1));
    setIsOpen(true);
  };

  // トリガーボタンのキーボード操作：矢印でメニューを開き、Enter/Spaceで選択を開く
  // Trigger keyboard handler: arrows open the menu; Enter/Space opens at selected index
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

  // オプション内のキー操作：Home/Endで端へ、Escapeでメニューを閉じる
  // Option keyboard handler: Home/End jump to edges; Escape closes and returns focus
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
      event.stopPropagation();
      setIsOpen(false);
      triggerRef.current?.focus();
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectOption(index);
    }
  };

  return (
    <div ref={rootRef} className={`prompt-composer-select${isOpen ? " is-open" : ""}`.trim()}>
      {/* ネイティブselectはフォームバリデーションとスクリーンリーダーのためのフォールバック */}
      {/* Native select acts as fallback for form validation and screen reader compatibility */}
      <select
        id={selectId}
        className="prompt-composer-select-native"
        required={required}
        ref={nativeRef}
        aria-hidden="true"
        tabIndex={-1}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
          onAfterChange();
        }}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>

      <button
        ref={triggerRef}
        id={`${selectId}-trigger`}
        type="button"
        className="prompt-composer-select__trigger"
        aria-haspopup="listbox"
        aria-expanded={isOpen ? "true" : "false"}
        aria-controls={listboxId}
        aria-label={`${menuLabel}: ${selectedLabel}`}
        onClick={() => {
          setActiveIndex(selectedIndex);
          setIsOpen((previous) => !previous);
        }}
        onKeyDown={handleTriggerKeyDown}
      >
        <span className="prompt-composer-select__label">{selectedLabel}</span>
        <i className="bi bi-chevron-down prompt-composer-select__chevron" aria-hidden="true"></i>
      </button>

      <div className="prompt-composer-select__menu" id={listboxId} role="listbox" aria-label={menuLabel}>
        {options.map((option, index) => (
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
        ))}
      </div>
    </div>
  );
}

// カスタムセレクトの各オプションをボタンとして描画し、ARIA属性でlistboxの役割を満たす
// Renders each select option as a button, satisfying listbox ARIA semantics
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
      // activeIndexと一致するときだけtabIndex=0にし、ローバーtabindexパターンを実現する
      // Only the active option is tab-reachable, implementing the roving tabindex pattern
      tabIndex={activeIndex === index ? 0 : -1}
      onClick={() => {
        onSelect(index);
      }}
      onKeyDown={(event) => {
        onKeyDown(event, index);
      }}
    >
      <span className="prompt-composer-select__option-label">{option.label}</span>
      {selected ? <i className="bi bi-check-lg prompt-composer-select__check" aria-hidden="true"></i> : null}
    </button>
  );
}

// プロンプト投稿フォーム全体を内包するモーダルコンポーネント
// Main composer modal that wraps the full prompt submission form
export function PromptShareComposerModal({
  isOpen,
  isPostSubmitting,
  postModalRef,
  onClose,
  onSubmit,
  contentFormat,
  setContentFormat,
  mediaType,
  setMediaType,
  postTitle,
  setPostTitle,
  postCategory,
  setPostCategory,
  postContent,
  setPostContent,
  postAiModel,
  setPostAiModel,
  guardrailEnabled,
  setGuardrailEnabled,
  postInputExample,
  setPostInputExample,
  postOutputExample,
  setPostOutputExample,
  postResources,
  setPostResources,
  attributeBindings,
  updatePromptFeedbackErrorIfNeeded,
  categoryOptions,
  promptPostStatus,
  promptPostTitleInputRef,
  promptPostCategorySelectRef,
  promptPostContentTextareaRef,
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
  const { locale, t } = useTranslation();
  // 選択中の2軸からレジストリ定義を解決する。
  // Resolve the registry descriptors for the currently selected axes.
  const activeFormat = getContentFormat(contentFormat);
  const activeMedia = getMediaType(mediaType);
  const attachmentRule = activeMedia.attachmentRule;
  const activeFieldKeys = new Set(getAttributeFields(contentFormat).map((field) => field.key));
  const activeFormatLabel = getPromptFormatLabel(contentFormat, locale);
  const activePostType: ComposerPostType = contentFormat === "skill"
    ? "skill"
    : mediaType === "image"
      ? "image-prompt"
      : "text-prompt";
  const showExamples = contentFormat === "prompt" && mediaType === "text" && !activeFormat.hidesExamples;
  const localizedCategoryOptions = categoryOptions.map((option) => ({
    ...option,
    label: option.value ? getCategoryLabelOrFallback(option.value, option.label, locale) : t("promptShare.notSelected")
  }));
  // 投稿タイプ（テキスト/画像）に合わせて、datalistに出す候補モデル名だけ絞り込む
  // Narrow the datalist suggestions to models relevant to the current post type (text vs image)
  const aiModelSuggestions = AI_MODEL_OPTION_GROUPS.filter((group) =>
    mediaType === "image" ? group.label === "画像生成" : group.label !== "画像生成"
  ).flatMap((group) => group.options.map((option) => option.value));

  // SKILLの説明パネルの開閉状態を管理し、フォーマットが切り替わると自動で閉じる
  // Manage the SKILL info panel toggle; reset it whenever the content format changes
  const [showSkillInfo, setShowSkillInfo] = useState(false);
  useEffect(() => {
    setShowSkillInfo(false);
  }, [contentFormat]);

  return (
    <div
      id="postModal"
      className={`post-modal${isOpen ? " show" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-labelledby="postModalTitle"
      aria-hidden={isOpen ? "false" : "true"}
      aria-busy={isPostSubmitting ? "true" : "false"}
      data-submitting={isPostSubmitting ? "true" : "false"}
      ref={postModalRef}
    >
      <div className="post-modal-content post-modal-content--composer" tabIndex={-1}>
        <button
          type="button"
          className="close-btn"
          aria-label={t("promptShare.closeComposer")}
          onClick={onClose}
          disabled={isPostSubmitting}
        >
          &times;
        </button>

        <div className="post-modal-scroll">
          <div className="composer-hero">
            <div className="composer-hero__copy">
              <p className="composer-hero__eyebrow">Prompt Share Composer</p>
              <h2 id="postModalTitle">{t("promptShare.newPrompt")}</h2>
            </div>
          </div>

          <form className="post-form" id="postForm" onSubmit={onSubmit}>
            <fieldset className="composer-form-fields" disabled={isPostSubmitting}>
            {/* --- 基本情報セクション: タイプ・タイトル・カテゴリを設定する --- */}
            {/* --- Basics section: set prompt type, title, and category --- */}
            <section className="composer-section composer-section--primary" aria-labelledby="composerBasicsTitle">
              <div className="composer-section__header">
                <div>
                  <p className="composer-section__eyebrow">Basics</p>
                  <h3 id="composerBasicsTitle">{t("promptShare.basicPostInfo")}</h3>
                </div>
              </div>

              {/* 保存上の2軸は維持しつつ、利用者には意味のある投稿タイプ3択として提示する。 */}
              {/* Preserve the two-axis data model while presenting three meaningful post types. */}
              <div className="form-group">
                <label>{t("promptShare.postType")}</label>
                <div className="prompt-axis-toggle prompt-axis-toggle--post-types" role="radiogroup" aria-label={t("promptShare.choosePostType")}>
                  {COMPOSER_POST_TYPES.map((postType) => (
                    <label
                      key={postType.key}
                      className={`prompt-axis-option${activePostType === postType.key ? " prompt-axis-option--active" : ""}`}
                    >
                      <input
                        type="radio"
                        name="post-type"
                        value={postType.key}
                        checked={activePostType === postType.key}
                        onChange={() => {
                          setContentFormat(postType.contentFormat);
                          setMediaType(postType.mediaType);
                          updatePromptFeedbackErrorIfNeeded();
                        }}
                      />
                      <span className="prompt-axis-option__icon" aria-hidden="true">
                        <i className={`bi ${postType.icon}`}></i>
                      </span>
                      <span className="prompt-axis-option__body">
                        <strong>{t(postType.labelKey)}</strong>
                        <small>{t(postType.helpKey)}</small>
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="composer-field-grid">
                <div className="form-group">
                  <label htmlFor="prompt-title">
                    {t("promptShare.titleLabel")} <span className="composer-required">{t("settings.required")}</span>
                  </label>
                  {/* 入力のたびにバリデーションエラーをリアルタイムでクリアする */}
                  {/* Clear validation feedback in real-time as the user types */}
                  <input
                    type="text"
                    id="prompt-title"
                    placeholder={t("promptShare.titlePlaceholder")}
                    required
                    maxLength={MAX_PROMPT_TITLE_LENGTH}
                    aria-describedby="prompt-title-counter"
                    ref={promptPostTitleInputRef}
                    value={postTitle}
                    onChange={(event) => {
                      setPostTitle(event.target.value);
                      updatePromptFeedbackErrorIfNeeded();
                    }}
                  />
                  <span className="composer-character-count" id="prompt-title-counter">
                    {t("promptShare.characterCount", { current: postTitle.length, max: MAX_PROMPT_TITLE_LENGTH })}
                  </span>
                </div>
              </div>
            </section>

            {/* --- 本文セクション: フォーマットに応じて本文/属性フィールドを切り替える --- */}
            {/* --- Content section: visibility switches based on the selected content format --- */}
            <section className="composer-section composer-section--content" aria-labelledby="composerContentTitle">
              <div className="composer-section__header">
                <div>
                  <p className="composer-section__eyebrow">{activeFormatLabel}</p>
                  <div className="composer-section__title-row">
                    <h3 id="composerContentTitle">
                      {contentFormat === "skill"
                        ? t("promptShare.skillSupport")
                        : mediaType === "image"
                          ? t("promptShare.imagePromptContent")
                          : t("promptShare.promptContent")}
                    </h3>
                    {/* SKILLの場合のみ情報ボタンを表示し、説明文の表示をトグルする */}
                    {/* Show info toggle only for skill format to explain the SKILL structure */}
                    {contentFormat === "skill" ? (
                      <button
                        type="button"
                        className={`composer-info-btn${showSkillInfo ? " is-active" : ""}`}
                        aria-label={t("promptShare.skillAbout")}
                        aria-expanded={showSkillInfo}
                        aria-controls="composerSkillHelp"
                        onClick={() => { setShowSkillInfo((v) => !v); }}
                      >
                        <i className="bi bi-info-circle" aria-hidden="true"></i>
                      </button>
                    ) : null}
                  </div>
                </div>
                {contentFormat === "skill" && showSkillInfo ? (
                  <p className="composer-section__description" id="composerSkillHelp">
                    {t("promptShare.skillHelp")}
                  </p>
                ) : null}
              </div>

              {/* 本文を使わないフォーマット(SKILL等)のときはCSSのdisplayで隠し、DOMを維持してrefを保持する */}
              {/* Hide with CSS display rather than unmounting to preserve refs when the format omits content */}
              <div className="form-group" style={{ display: activeFormat.requiresContent ? "" : "none" }}>
                <label htmlFor="prompt-content">
                  {mediaType === "image" ? t("promptShare.imagePromptContent") : t("promptShare.promptContent")}
                  {" "}<span className="composer-required">{t("settings.required")}</span>
                </label>
                <textarea
                  id="prompt-content"
                  rows={6}
                  placeholder={mediaType === "image" ? t("promptShare.imageContentPlaceholder") : t("promptShare.contentPlaceholder")}
                  required={activeFormat.requiresContent}
                  maxLength={MAX_PROMPT_CONTENT_LENGTH}
                  aria-describedby="prompt-content-counter"
                  ref={promptPostContentTextareaRef}
                  value={postContent}
                  onChange={(event) => {
                    setPostContent(event.target.value);
                    updatePromptFeedbackErrorIfNeeded();
                  }}
                ></textarea>
                <span className="composer-character-count" id="prompt-content-counter">
                  {t("promptShare.characterCount", { current: postContent.length, max: MAX_PROMPT_CONTENT_LENGTH })}
                </span>
              </div>

              {/* AI補助は必要な利用者だけ展開できるようにし、通常入力の見通しを保つ。 */}
              {/* Keep AI assistance collapsible so the primary form remains easy to scan. */}
              <details className="composer-ai-assist" aria-disabled={isPostSubmitting ? "true" : undefined}>
                <summary
                  tabIndex={isPostSubmitting ? -1 : undefined}
                  onClick={(event) => {
                    if (isPostSubmitting) event.preventDefault();
                  }}
                  onKeyDown={(event) => {
                    if (isPostSubmitting && (event.key === "Enter" || event.key === " ")) {
                      event.preventDefault();
                    }
                  }}
                >
                  <i className="bi bi-stars" aria-hidden="true"></i>
                  <span>{t("promptShare.aiAssistToggle")}</span>
                </summary>
                <div id="sharedPromptAssistRoot" ref={promptAssistRootRef}></div>
              </details>
            </section>

            {/* --- 詳細設定セクション: AIモデル選択・画像・SKILLフィールド --- */}
            {/* --- Details section: AI model, reference image, and SKILL-specific fields --- */}
            <section className="composer-section" aria-labelledby="composerMetaTitle">
              <div className="composer-section__header">
                <div>
                  <p className="composer-section__eyebrow">Details</p>
                  <h3 id="composerMetaTitle">{t("promptShare.postSettings")}</h3>
                </div>
              </div>

              <div className="composer-field-grid composer-field-grid--two">
                <div className="form-group">
                  <label htmlFor="prompt-category-trigger">
                    {t("promptShare.category")} <span className="composer-optional">{t("common.optional")}</span>
                  </label>
                  <span className="form-group__hint" id="prompt-category-help">{t("promptShare.categoryOptionalHelp")}</span>
                  <PromptComposerSelect
                    selectId="prompt-category"
                    nativeRef={promptPostCategorySelectRef}
                    value={postCategory}
                    options={localizedCategoryOptions}
                    menuLabel={t("promptShare.selectCategory")}
                    onChange={setPostCategory}
                    onAfterChange={updatePromptFeedbackErrorIfNeeded}
                    isModalOpen={isOpen}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="prompt-ai-model">{t("promptShare.aiModelOptional")}</label>
                  {/* 固定リストのプルダウンではなく自由入力にし、リストにないモデルも
                      そのまま入力できるようにする。datalistは代表的なモデル名を補助として示すだけ。 */}
                  {/* Free text instead of a fixed dropdown, so models not on the list can still be
                      entered as-is. The datalist only offers common model names as a convenience. */}
                  <input
                    type="text"
                    id="prompt-ai-model"
                    list="prompt-ai-model-suggestions"
                    autoComplete="off"
                    placeholder={t("promptShare.aiModelPlaceholder")}
                    maxLength={100}
                    ref={promptPostAiModelSelectRef}
                    value={postAiModel}
                    onChange={(event) => {
                      setPostAiModel(event.target.value);
                      updatePromptFeedbackErrorIfNeeded();
                    }}
                  />
                  <datalist id="prompt-ai-model-suggestions">
                    {aiModelSuggestions.map((modelName) => (
                      <option key={modelName} value={modelName} />
                    ))}
                  </datalist>
                </div>
              </div>

              {/* メディアが添付を許可する場合のみ、汎用の作例添付フィールドを表示する */}
              {/* Generic reference attachment field, shown only when the media allows attachments */}
              <div className="image-prompt-fields" hidden={!attachmentRule}>
                <div className="form-group">
                  <label htmlFor="prompt-reference-image">{t("promptShare.generatedExampleAttachment")}</label>
                  <label className="image-upload-field" htmlFor="prompt-reference-image">
                    <input
                      type="file"
                      id="prompt-reference-image"
                      accept={attachmentRule?.accept}
                      ref={promptImageInputRef}
                      onChange={onReferenceImageChange}
                    />
                    <span className="image-upload-field__icon" aria-hidden="true">
                      <i className="bi bi-cloud-arrow-up"></i>
                    </span>
                    <span className="image-upload-field__copy">
                      <strong>{t("promptShare.uploadGeneratedExample")}</strong>
                      <small>
                        {attachmentRule
                          ? t("promptShare.attachmentRules", { types: attachmentRule.acceptedExt
                              .map((ext) => ext.replace(".", "").toUpperCase())
                              .filter((ext, index, list) => list.indexOf(ext) === index)
                              .join(" / "), max: Math.round(attachmentRule.maxBytes / (1024 * 1024)) })
                          : ""}
                      </small>
                    </span>
                  </label>

                  {/* プレビューは添付が選択されているときのみ表示する */}
                  {/* Preview section is only shown once an attachment has been selected */}
                  {promptImagePreviewUrl ? (
                  <div id="promptImagePreview" className="prompt-image-preview">
                    <img id="promptImagePreviewImg" src={promptImagePreviewUrl} alt={t("promptShare.uploadPreview")} />
                    <div className="prompt-image-preview__meta">
                      <span id="promptImagePreviewName">{promptImagePreviewName}</span>
                      <button
                        type="button"
                        id="promptImageClearButton"
                        className="prompt-image-clear-btn"
                        onClick={onClearReferenceImage}
                      >
                        <i className="bi bi-x-lg" aria-hidden="true"></i>
                        <span>{t("promptShare.removeAttachment")}</span>
                      </button>
                    </div>
                  </div>
                  ) : null}
                </div>
              </div>

              {/* フォーマット固有の属性フィールドをレジストリから描画する。 */}
              {/* DOMは常時マウントし、選択中フォーマットに属さないものはhiddenで隠してrefを保持する。 */}
              {/* Render format-specific attribute fields from the registry. */}
              {/* Keep them all mounted, hiding the ones not in the active format to preserve refs. */}
              <div className="skill-prompt-fields">
                {ALL_ATTRIBUTE_FIELDS.map((field) => {
                  const binding = attributeBindings[field.key];
                  if (!binding) return null;
                  const isActive = activeFieldKeys.has(field.key);
                  const fieldId = `prompt-attr-${field.key}`;
                  return (
                    <div className="form-group" key={field.key} hidden={!isActive}>
                      <label htmlFor={fieldId}>{t("promptShare.skillMarkdownLabel")}</label>
                      <textarea
                        id={fieldId}
                        rows={field.rows ?? 8}
                        maxLength={field.maxLength}
                        placeholder={t("promptShare.skillMarkdownHint")}
                        required={isActive && Boolean(field.required)}
                        ref={binding.ref}
                        value={binding.value}
                        onChange={(event) => {
                          binding.setValue(event.target.value);
                          updatePromptFeedbackErrorIfNeeded();
                        }}
                      ></textarea>
                    </div>
                  );
                })}
                {contentFormat === "skill" ? (
                  <SkillResourceEditor
                    resources={postResources}
                    setResources={setPostResources}
                    onEdit={updatePromptFeedbackErrorIfNeeded}
                  />
                ) : null}
              </div>
            </section>

            {/* --- 利用例セクション: テキストプロンプトでのみ表示 --- */}
            {/* --- Examples section: shown only for text prompts --- */}
            <section className="composer-section" aria-labelledby="composerExamplesTitle" hidden={!showExamples}>
              <div className="composer-section__header">
                <div>
                  <p className="composer-section__eyebrow">Examples</p>
                  <h3 id="composerExamplesTitle">{t("promptShare.examplesOptional")}</h3>
                </div>
              </div>

              {/* トグルをONにしたときだけ入出力例フィールドを展開する */}
              {/* Expand example fields only when the user opts in via the toggle */}
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
                    <strong>{t("promptShare.addExamples")}</strong>
                    <small>{t("promptShare.examplesBenefit")}</small>
                  </span>
                </label>
              </div>

              <div id="guardrail-fields" style={{ display: guardrailEnabled ? "block" : "none" }}>
                <div className="composer-field-grid">
                  <div className="form-group">
                    <label htmlFor="prompt-input-example">{t("promptShare.inputExampleLabel")}</label>
                    <textarea
                      id="prompt-input-example"
                      rows={3}
                      maxLength={MAX_PROMPT_CONTENT_LENGTH}
                      placeholder={t("promptShare.inputPlaceholder")}
                      ref={promptPostInputExamplesRef}
                      value={postInputExample}
                      onChange={(event) => {
                        setPostInputExample(event.target.value);
                        updatePromptFeedbackErrorIfNeeded();
                      }}
                    ></textarea>
                    <span className="composer-character-count">
                      {t("promptShare.characterCount", { current: postInputExample.length, max: MAX_PROMPT_CONTENT_LENGTH })}
                    </span>
                  </div>
                  <div className="form-group">
                    <label htmlFor="prompt-output-example">{t("promptShare.outputExample")}</label>
                    <textarea
                      id="prompt-output-example"
                      rows={3}
                      maxLength={MAX_PROMPT_CONTENT_LENGTH}
                      placeholder={t("promptShare.outputPlaceholder")}
                      ref={promptPostOutputExamplesRef}
                      value={postOutputExample}
                      onChange={(event) => {
                        setPostOutputExample(event.target.value);
                        updatePromptFeedbackErrorIfNeeded();
                      }}
                    ></textarea>
                    <span className="composer-character-count">
                      {t("promptShare.characterCount", { current: postOutputExample.length, max: MAX_PROMPT_CONTENT_LENGTH })}
                    </span>
                  </div>
                </div>
              </div>
            </section>
            </fieldset>

            {/* --- 送信アクション: 画面下部に固定せず、入力欄の末尾にそのまま並べる --- */}
            {/* --- Submit action: not pinned to the viewport; it flows at the end of the inputs --- */}
            <div className="composer-actions">
              {/* エラー時のみ文言を可視表示し、送信中/成功はボタン自体のビジュアル（スピナー→チェック）で伝える。
                  読み上げ用のテキストはスクリーンリーダー向けに残す（視覚的には非表示）。 */}
              {/* Only errors show visible text; submitting/success states are conveyed by the button's
                  own visuals (spinner → checkmark). The message stays for screen readers but is visually hidden otherwise. */}
              <p
                id="promptPostStatus"
                className={`composer-status${promptPostStatus.variant === "error" ? "" : " composer-status--visually-hidden"}`}
                hidden={!promptPostStatus.message}
                data-variant={promptPostStatus.variant}
                role={promptPostStatus.variant === "error" ? "alert" : "status"}
                aria-live={promptPostStatus.variant === "error" ? "assertive" : "polite"}
                aria-atomic="true"
              >
                {promptPostStatus.variant === "error" ? (
                  <i className="bi bi-exclamation-triangle-fill" aria-hidden="true"></i>
                ) : null}
                {promptPostStatus.message}
              </p>
              {/* 送信中はボタンをdisabledにして重複送信を防ぐ */}
              {/* Disable submit button during submission to prevent duplicate requests */}
              <button
                type="submit"
                className={`submit-btn${isPostSubmitting ? " is-loading" : ""}${
                  promptPostStatus.variant === "success" ? " is-success" : ""
                }`}
                disabled={isPostSubmitting}
              >
                <i
                  className={`bi ${
                    promptPostStatus.variant === "success"
                      ? "bi-check-lg"
                      : isPostSubmitting
                        ? "bi-arrow-repeat submit-btn__spinner"
                        : "bi-upload"
                  }`}
                  aria-hidden="true"
                ></i>
                <span className="submit-btn__label">
                  {promptPostStatus.variant === "success"
                    ? t("promptShare.posted")
                    : isPostSubmitting
                      ? t("promptShare.preparingPost")
                      : t("promptShare.post")}
                </span>
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
