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
  CONTENT_FORMATS,
  MEDIA_TYPES,
  getAttributeFields,
  getContentFormat,
  getMediaType,
  normalizeContentFormat,
  normalizeMediaType
} from "../../scripts/prompt_share/prompt_type_registry";
import type { ContentFormat, MediaType, PromptResource } from "../../scripts/prompt_share/types";
import type { PromptCategoryOption, PromptPostStatus } from "./prompt_share_page_types";
import { SkillResourceEditor } from "./skill_resource_editor";
import { useTranslation } from "../../contexts/locale_context";
import { getPromptFormatLabel, getPromptMediaLabel } from "../../scripts/prompt_share/formatters";
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
  promptPostAiModelSelectRef: RefObject<HTMLSelectElement | null>;
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
  group?: string;
};

// AIモデルをベンダーでグループ化した選択肢の定義
// AI model options grouped by vendor for visual separation in the dropdown
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

// フラットなオプションリストを用意し、グループ情報を各要素に付与する
// Flatten grouped options into a single list while preserving group metadata for rendering
const AI_MODEL_OPTIONS: PromptComposerSelectOption[] = [
  { value: "", label: "未設定" },
  ...AI_MODEL_OPTION_GROUPS.flatMap((group) =>
    group.options.map((option) => ({ ...option, group: group.label }))
  ),
  { value: "その他", label: "その他" }
];

// ネイティブ<select>とカスタムUIを同期させ、キーボード操作も担うコンポーネント
// Renders a custom accessible dropdown that stays in sync with a hidden native <select>
function PromptComposerSelect({
  selectId,
  nativeRef,
  value,
  options,
  groupedOptions,
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
  groupedOptions?: { label: string; options: PromptComposerSelectOption[] }[];
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
      setIsOpen(false);
      triggerRef.current?.focus();
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectOption(index);
    }
  };

  // グループ付きレンダリング時にフラットなoptionIndexを手動でインクリメントする
  // Manual counter for flat option index when rendering grouped options
  let optionIndex = 0;

  return (
    <div ref={rootRef} className={`prompt-composer-select${isOpen ? " is-open" : ""}`.trim()}>
      {/* ネイティブselectはフォームバリデーションとスクリーンリーダーのためのフォールバック */}
      {/* Native select acts as fallback for form validation and screen reader compatibility */}
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
            <option value={options[0]?.value ?? ""}>{options[0]?.label}</option>
            {groupedOptions.map((group) => (
              <optgroup key={group.label} label={group.label}>
                {group.options.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </optgroup>
            ))}
            <option value={options[options.length - 1]?.value ?? "その他"}>{options[options.length - 1]?.label}</option>
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
            {/* 「未設定」はグループ外の先頭に独立して配置する */}
            {/* Render the "unset" option separately before the grouped options */}
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
            {/* 「その他」はグループ外の末尾に独立して配置する */}
            {/* Render "other" as a standalone option after all groups */}
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
      {selected ? <i className="bi bi-check-lg prompt-composer-select__check"></i> : null}
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
  const activeMediaLabel = getPromptMediaLabel(mediaType, locale);
  const localizedCategoryOptions = categoryOptions.map((option) => ({
    ...option,
    label: option.value ? getCategoryLabelOrFallback(option.value, option.label, locale) : t("promptShare.notSelected")
  }));
  const localizedAiModelGroups = AI_MODEL_OPTION_GROUPS.map((group) => ({
    ...group,
    label: group.label === "画像生成" ? t("promptShare.imageGeneration") : group.label
  }));
  const localizedAiModelOptions: PromptComposerSelectOption[] = [
    { value: "", label: t("promptShare.unset") },
    ...localizedAiModelGroups.flatMap((group) => group.options.map((option) => ({ ...option, group: group.label }))),
    { value: "その他", label: t("promptShare.categoryOther") }
  ];

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
      data-submitting={isPostSubmitting ? "true" : "false"}
      ref={postModalRef}
    >
      <div className="post-modal-content post-modal-content--composer" tabIndex={-1}>
        <button type="button" className="close-btn" aria-label={t("promptShare.closeComposer")} onClick={onClose}>
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
            {/* --- 基本情報セクション: タイプ・タイトル・カテゴリを設定する --- */}
            {/* --- Basics section: set prompt type, title, and category --- */}
            <section className="composer-section composer-section--primary" aria-labelledby="composerBasicsTitle">
              <div className="composer-section__header">
                <div>
                  <p className="composer-section__eyebrow">Basics</p>
                  <h3 id="composerBasicsTitle">{t("promptShare.basicPostInfo")}</h3>
                </div>
              </div>

              {/* 2軸セレクタ: フォーマット軸とメディア軸を独立に選ぶ。アイコン＋短いラベルで一目で分かるようにする */}
              {/* Two-axis selectors: format and media chosen independently. Icon + short label, minimal text */}
              <div className="composer-axis-grid">
                <div className="form-group">
                  <label>{t("promptShare.format")}</label>
                  <div className="prompt-axis-toggle" role="radiogroup" aria-label={t("promptShare.chooseFormat")}>
                    {CONTENT_FORMATS.map((format) => (
                      <label
                        key={format.key}
                        className={`prompt-axis-option${contentFormat === format.key ? " prompt-axis-option--active" : ""}`}
                      >
                        <input
                          type="radio"
                          name="content-format"
                          value={format.key}
                          checked={contentFormat === format.key}
                          onChange={(event) => {
                            setContentFormat(normalizeContentFormat(event.target.value));
                          }}
                        />
                        <span className="prompt-axis-option__icon">
                          <i className={`bi ${format.icon}`}></i>
                        </span>
                        <span className="prompt-axis-option__body">
                          <strong>{getPromptFormatLabel(format.key, locale)}</strong>
                          <small>{format.key === "skill" ? t("promptShare.formatSkillTagline") : t("promptShare.formatPromptTagline")}</small>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="form-group">
                  <label>{t("promptShare.generationMedia")}</label>
                  <div className="prompt-axis-toggle" role="radiogroup" aria-label={t("promptShare.chooseMedia")}>
                    {MEDIA_TYPES.map((media) => (
                      <label
                        key={media.key}
                        className={`prompt-axis-option${mediaType === media.key ? " prompt-axis-option--active" : ""}`}
                      >
                        <input
                          type="radio"
                          name="media-type"
                          value={media.key}
                          checked={mediaType === media.key}
                          onChange={(event) => {
                            setMediaType(normalizeMediaType(event.target.value));
                          }}
                        />
                        <span className="prompt-axis-option__icon">
                          <i className={`bi ${media.icon}`}></i>
                        </span>
                        <span className="prompt-axis-option__body">
                          <strong>{getPromptMediaLabel(media.key, locale)}</strong>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>

              <div className="composer-field-grid composer-field-grid--two">
                <div className="form-group">
                  <label htmlFor="prompt-title">{t("promptShare.titleLabel")}</label>
                  {/* 入力のたびにバリデーションエラーをリアルタイムでクリアする */}
                  {/* Clear validation feedback in real-time as the user types */}
                  <input
                    type="text"
                    id="prompt-title"
                    placeholder={t("promptShare.titlePlaceholder")}
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
                  <label htmlFor="prompt-category">{t("promptShare.category")}</label>
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
                      {contentFormat === "skill" ? t("promptShare.skillSupport") : t("promptShare.promptContent")}
                    </h3>
                    {/* SKILLの場合のみ情報ボタンを表示し、説明文の表示をトグルする */}
                    {/* Show info toggle only for skill format to explain the SKILL structure */}
                    {contentFormat === "skill" ? (
                      <button
                        type="button"
                        className={`composer-info-btn${showSkillInfo ? " is-active" : ""}`}
                        aria-label={t("promptShare.skillAbout")}
                        aria-expanded={showSkillInfo}
                        onClick={() => { setShowSkillInfo((v) => !v); }}
                      >
                        <i className="bi bi-info-circle" aria-hidden="true"></i>
                      </button>
                    ) : null}
                  </div>
                </div>
                {contentFormat === "skill" && showSkillInfo ? (
                  <p className="composer-section__description">
                    {t("promptShare.skillHelp")}
                  </p>
                ) : null}
              </div>

              {/* 本文を使わないフォーマット(SKILL等)のときはCSSのdisplayで隠し、DOMを維持してrefを保持する */}
              {/* Hide with CSS display rather than unmounting to preserve refs when the format omits content */}
              <div className="form-group" style={{ display: activeFormat.requiresContent ? "" : "none" }}>
                <label htmlFor="prompt-content">{t("promptShare.promptContent")}</label>
                <textarea
                  id="prompt-content"
                  rows={6}
                  placeholder={t("promptShare.contentPlaceholder")}
                  required={activeFormat.requiresContent}
                  ref={promptPostContentTextareaRef}
                  value={postContent}
                  onChange={(event) => {
                    setPostContent(event.target.value);
                    updatePromptFeedbackErrorIfNeeded();
                  }}
                ></textarea>
              </div>

              {/* AI補助UIのマウントポイント（外部スクリプトがここにReactツリーを注入する） */}
              {/* Mount point for the AI-assist widget injected by an external script */}
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

            {/* --- 詳細設定セクション: AIモデル選択・画像・SKILLフィールド --- */}
            {/* --- Details section: AI model, reference image, and SKILL-specific fields --- */}
            <section className="composer-section" aria-labelledby="composerMetaTitle">
              <div className="composer-section__header">
                <div>
                  <p className="composer-section__eyebrow">Details</p>
                  <h3 id="composerMetaTitle">{t("promptShare.postSettings")}</h3>
                </div>
              </div>

              <div className="composer-field-grid">
                <div className="form-group">
                  <label htmlFor="prompt-ai-model">{t("promptShare.aiModelOptional")}</label>
                  <PromptComposerSelect
                    selectId="prompt-ai-model"
                    nativeRef={promptPostAiModelSelectRef}
                    value={postAiModel}
                    options={localizedAiModelOptions}
                    groupedOptions={localizedAiModelGroups}
                    menuLabel={t("promptShare.chooseAiModel")}
                    onChange={setPostAiModel}
                    onAfterChange={updatePromptFeedbackErrorIfNeeded}
                    isModalOpen={isOpen}
                  />
                </div>
              </div>

              {/* メディアが添付を許可する場合のみ、汎用の作例添付フィールドを表示する */}
              {/* Generic reference attachment field, shown only when the media allows attachments */}
              <div className="image-prompt-fields" hidden={!attachmentRule}>
                <div className="form-group">
                  <label htmlFor="prompt-reference-image">{t("promptShare.exampleAttachment", { media: activeMediaLabel })}</label>
                  <label className="image-upload-field" htmlFor="prompt-reference-image">
                    <input
                      type="file"
                      id="prompt-reference-image"
                      accept={attachmentRule?.accept}
                      ref={promptImageInputRef}
                      onChange={onReferenceImageChange}
                    />
                    <span className="image-upload-field__icon">
                      <i className="bi bi-cloud-arrow-up"></i>
                    </span>
                    <span className="image-upload-field__copy">
                      <strong>{t("promptShare.uploadMedia", { media: activeMediaLabel })}</strong>
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
                  <div id="promptImagePreview" className="prompt-image-preview" hidden={!promptImagePreviewUrl}>
                    <img id="promptImagePreviewImg" src={promptImagePreviewUrl} alt={t("promptShare.uploadPreview")} />
                    <div className="prompt-image-preview__meta">
                      <span id="promptImagePreviewName">{promptImagePreviewName}</span>
                      <button
                        type="button"
                        id="promptImageClearButton"
                        className="prompt-image-clear-btn"
                        onClick={onClearReferenceImage}
                      >
                        <i className="bi bi-x-lg"></i>
                        <span>{t("promptShare.removeAttachment")}</span>
                      </button>
                    </div>
                  </div>
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

            {/* --- 利用例セクション: フォーマットがhidesExamplesのときは非表示 --- */}
            {/* --- Examples section: hidden when the active format declares hidesExamples --- */}
            <section className="composer-section" aria-labelledby="composerExamplesTitle" hidden={activeFormat.hidesExamples}>
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
                      placeholder={t("promptShare.inputPlaceholder")}
                      ref={promptPostInputExamplesRef}
                      value={postInputExample}
                      onChange={(event) => {
                        setPostInputExample(event.target.value);
                        updatePromptFeedbackErrorIfNeeded();
                      }}
                    ></textarea>
                  </div>
                  <div className="form-group">
                    <label htmlFor="prompt-output-example">{t("promptShare.outputExample")}</label>
                    <textarea
                      id="prompt-output-example"
                      rows={3}
                      placeholder={t("promptShare.outputPlaceholder")}
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
              {/* 送信中はボタンをdisabledにして重複送信を防ぐ */}
              {/* Disable submit button during submission to prevent duplicate requests */}
              <button type="submit" className="submit-btn" disabled={isPostSubmitting}>
                <i className={`bi ${isPostSubmitting ? "bi-stars" : "bi-upload"}`}></i>
                {isPostSubmitting ? t("promptShare.preparingPost") : t("promptShare.post")}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
