// ユーザー設定ページ全体のエントリポイント — プロフィール・外観・プロンプト・セキュリティを一画面で管理する
// Entry point for the user settings page — manages profile, appearance, prompts, and security in a single view
import { SeoHead } from "../components/SeoHead";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent
} from "react";

import "../scripts/core/csrf";
import { PasskeyCancelledError, browserSupportsPasskeys, registerPasskey } from "../scripts/core/passkeys";
import { showConfirmModal } from "../scripts/core/alert_modal";
import { showToast } from "../scripts/core/toast";
import { fetchJsonOrThrow } from "../scripts/core/runtime_validation";
import { getStoredThemePreference, setThemePreference, type ThemePreference } from "../scripts/core/theme";
import { InlineLoading } from "../components/ui/inline_loading";
import { formatDateTime } from "../lib/datetime";
import { asId, asRecord, asString } from "../lib/utils";
import {
  parseLikedPromptsResponse,
  parseMyPromptsResponse,
  parsePromptManageMutationResponse,
  type LikedPrompt,
  type PromptRecord
} from "../scripts/user/settings/types";
import { truncateTitle } from "../scripts/user/settings/utils";
import { PROMPT_CATEGORY_OPTIONS } from "../components/prompt_share/prompt_share_page_constants";

// 設定画面のどのセクションを表示するかを識別するユニオン型
// Union type identifying which section of the settings page is currently visible
type SettingsSection = "profile" | "appearance" | "prompts" | "liked-prompts" | "notifications" | "security";

// テーマ選択肢の定義型 — アイコン・ラベル・説明を束ねる
// Type for a single theme option bundling icon, label, and description
type ThemeOption = {
  value: ThemePreference;
  iconClass: string;
  label: string;
  description: string;
};

// 選択可能なテーマの一覧 — ライト・ダーク・システム追従の 3 択
// Available theme choices — light, dark, and system-follow
const THEME_OPTIONS: ThemeOption[] = [
  {
    value: "light",
    iconClass: "bi bi-sun-fill",
    label: "ライト",
    description: "明るい背景の固定テーマ"
  },
  {
    value: "dark",
    iconClass: "bi bi-moon-stars-fill",
    label: "ダーク",
    description: "暗い背景の固定テーマ"
  },
  {
    value: "auto",
    iconClass: "bi bi-circle-half",
    label: "システムに合わせる",
    description: "OS の設定に追従して自動切り替え"
  }
];

// サイドバーナビゲーション項目の型
// Type for a sidebar navigation item
type SettingsNavItem = {
  section: SettingsSection;
  iconClass: string;
  label: string;
};

// プロフィールフォームの入力値をまとめた型 — 送信前の一時的な状態を保持する
// Type holding the current (unsaved) values of the profile form
type ProfileFormState = {
  username: string;
  email: string;
  bio: string;
  llmProfileContext: string;
};

// プロフィール保存後のフィードバック表示に使う型
// Type used to display inline feedback after a profile save attempt
type ProfileSaveStatus = {
  tone: "success" | "error";
  message: string;
};

// メールアドレス変更フローの進行ステージ
// Progress stage of the email-change two-step verification flow
type EmailChangeStage = "idle" | "current_email" | "new_email";

// プロンプト編集モーダルで管理するフォーム状態
// Form state managed inside the prompt-edit modal
type EditPromptFormState = {
  id: string;
  title: string;
  category: string;
  content: string;
  inputExamples: string;
  outputExamples: string;
};

// 登録済み Passkey 1 件の情報を表す型
// Represents a single registered passkey record
type PasskeyRecord = {
  id: number;
  label: string;
  credentialDeviceType: string;
  credentialBackedUp: boolean;
  createdAt: string;
  lastUsedAt: string;
};

// 保存成功アニメーションの表示時間（ミリ秒）
// Duration in milliseconds to show the save-success animation
const PROFILE_SAVE_EFFECT_DURATION_MS = 2200;
// アカウント削除を確定させるためにユーザーが入力すべき文字列
// Exact string the user must type to confirm account deletion
const ACCOUNT_DELETE_CONFIRMATION_TEXT = "DELETE ACCOUNT";

// サイドバーに表示するナビゲーション項目の定義
// Definition of navigation items shown in the settings sidebar
const SETTINGS_NAV_ITEMS: SettingsNavItem[] = [
  { section: "profile", iconClass: "bi bi-person-circle", label: "プロフィール設定" },
  { section: "appearance", iconClass: "bi bi-palette", label: "外観" },
  { section: "prompts", iconClass: "bi bi-shield-lock", label: "投稿したプロンプト" },
  { section: "liked-prompts", iconClass: "bi bi-heart", label: "いいねしたプロンプト" },
  { section: "notifications", iconClass: "bi bi-bell", label: "通知設定" },
  { section: "security", iconClass: "bi bi-key", label: "セキュリティ" }
];

// アバター未設定時に表示するデフォルト画像のパス
// Path to the default avatar image shown when no avatar is set
const DEFAULT_AVATAR_URL = "/static/user-icon.png";
// Passkey 対応状況チェック開始前に表示する初期メッセージ
// Initial message shown while checking passkey browser support
const PASSKEY_INITIAL_SUPPORT_TEXT = "このブラウザの対応状況を確認しています。";

// 生の日付文字列を人間が読みやすい形式に変換する — 空値は空文字を返す
// Converts a raw date string to a human-readable format; returns empty string for falsy input
function toDisplayDate(rawDate?: string): string {
  return formatDateTime(rawDate) || rawDate || "";
}

// 複数の空白文字を 1 つに正規化しトリムする — カード上のプレビューテキスト整形用
// Collapses consecutive whitespace and trims — used to format preview text on cards
function normalizePreviewText(value?: string): string {
  return (value || "").replace(/\s+/g, " ").trim();
}

// API レスポンスの未知の配列を型安全な PasskeyRecord 配列に変換する
// Converts an unknown array from the API response into a type-safe PasskeyRecord array
function normalizePasskeyRecords(rawPasskeys: unknown[]): PasskeyRecord[] {
  return rawPasskeys
    .map((rawPasskey) => {
      const passkey = asRecord(rawPasskey);
      const id = Number(passkey.id);
      // 数値として有効でない ID はスキップして配列から除外する
      // Skip entries whose id is not a finite number to avoid corrupted records
      if (!Number.isFinite(id)) {
        return null;
      }
      const label = typeof passkey.label === "string" && passkey.label.trim()
        ? passkey.label.trim()
        : "保存済みPasskey";
      return {
        id,
        label,
        credentialDeviceType: typeof passkey.credential_device_type === "string"
          ? passkey.credential_device_type
          : "不明",
        credentialBackedUp: Boolean(passkey.credential_backed_up),
        createdAt: typeof passkey.created_at === "string" ? passkey.created_at : "",
        lastUsedAt: typeof passkey.last_used_at === "string" ? passkey.last_used_at : ""
      };
    })
    .filter((passkey): passkey is PasskeyRecord => passkey !== null);
}

// Passkey の日時を表示用にフォーマットする — 値がなければ「未使用」を返す
// Formats a passkey datetime for display; returns "未使用" when the value is absent
function formatPasskeyDateTime(value: string): string {
  if (!value) {
    return "未使用";
  }
  return formatDateTime(value) || "未使用";
}

// プロフィール情報から LLM に渡すデフォルトコンテキスト文字列を組み立てる
// Builds the default LLM context string from profile fields when no custom value has been saved
function buildDefaultLlmProfileContext(profile: Pick<ProfileFormState, "username" | "email" | "bio">): string {
  const lines: string[] = [];
  const username = profile.username.trim();
  const email = profile.email.trim();
  const bio = profile.bio.trim();

  // 空フィールドは出力に含めず、入力済みの項目だけを改行区切りで連結する
  // Only include fields that have content so the context stays clean
  if (username) {
    lines.push(`名前: ${username}`);
  }
  if (email) {
    lines.push(`メールアドレス: ${email}`);
  }
  if (bio) {
    lines.push(`自己紹介: ${bio}`);
  }

  return lines.join("\n");
}

// 設定画面の左側に表示するナビゲーションサイドバー
// Navigation sidebar displayed on the left side of the settings page
function SettingsSidebar({
  activeSection,
  onSectionSelect
}: {
  activeSection: SettingsSection;
  onSectionSelect: (section: SettingsSection) => void;
}) {
  return (
    <nav className="settings-sidebar">
      <div className="sidebar-header">
        <h3>設定</h3>
      </div>

      {/* 各設定セクションへのリンク一覧 — アクティブ状態を aria-current で通知する / List of links to each settings section — active state is communicated via aria-current */}
      <ul className="nav-menu">
        {SETTINGS_NAV_ITEMS.map((item) => (
          <li key={item.section}>
            <button
              type="button"
              className={`nav-link${activeSection === item.section ? " active" : ""}`}
              data-section={item.section}
              data-agent-id={`settings.section.${item.section}`}
              aria-current={activeSection === item.section ? "page" : undefined}
              onClick={(event) => {
                event.preventDefault();
                onSectionSelect(item.section);
              }}
            >
              <i className={item.iconClass}></i> {item.label}
            </button>
          </li>
        ))}
      </ul>

      <div className="sidebar-footer">
        <p>&copy; 2026 ChatCore-AI</p>
      </div>
    </nav>
  );
}

// ユーザーが投稿したプロンプト 1 件を表示するカードコンポーネント
// Card component displaying a single user-authored prompt
function PromptCard({
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
  const categoryLabel = normalizePreviewText(prompt.category) || "未分類";
  const createdAtLabel = prompt.createdAt ? toDisplayDate(prompt.createdAt) : "日時未設定";

  return (
    <article className="prompt-card" data-prompt-id={promptId}>
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
            className="prompt-card__action-btn prompt-card__action-btn--edit"
            onClick={() => onEdit(prompt)}
            aria-label="編集"
          >
            <i className="bi bi-pencil-square"></i>
            <span>編集</span>
          </button>
          <button
            type="button"
            className="prompt-card__action-btn prompt-card__action-btn--delete"
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
function LikedPromptCard({
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
  const categoryLabel = normalizePreviewText(entry.category);
  const likedAtLabel = entry.likedAt ? toDisplayDate(entry.likedAt) : "日時未設定";

  return (
    <article className="prompt-card" data-liked-prompt-id={entryId}>
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
            className="prompt-card__action-btn prompt-card__action-btn--delete"
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

// キーボード操作に対応したアクセシブルなカテゴリ選択コンポーネント
// Accessible category select component with full keyboard navigation support
function PromptCategorySelect({
  selectId,
  value,
  disabled,
  onChange
}: {
  selectId: string;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  // 各オプションボタンへの参照を保持し、フォーカス移動に使う
  // Holds refs to each option button so keyboard navigation can move focus programmatically
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [isOpen, setIsOpen] = useState(false);
  const selectedValue = value || "未選択";
  // 現在値が選択肢リストにない場合は先頭に追加して一覧に含める
  // Prepend the current value when it is not part of the standard option list
  const categoryOptions = PROMPT_CATEGORY_OPTIONS.includes(selectedValue)
    ? PROMPT_CATEGORY_OPTIONS
    : [selectedValue, ...PROMPT_CATEGORY_OPTIONS];
  const selectedIndex = Math.max(0, categoryOptions.indexOf(selectedValue));
  const [activeIndex, setActiveIndex] = useState(selectedIndex);
  const listboxId = `${selectId}-menu`;

  // 選択値が外部から変わったときにアクティブインデックスを同期する
  // Keep activeIndex in sync when the selected value changes externally
  useEffect(() => {
    setActiveIndex(selectedIndex);
  }, [selectedIndex]);

  // ドロップダウンが開いている間、外側クリックで閉じるためのグローバルリスナーを登録する
  // Register a global pointer-down listener to close the dropdown when clicking outside
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

  // activeIndex が変わるたびに対応するオプションにフォーカスを移す
  // Move focus to the option at activeIndex whenever it changes while the list is open
  useEffect(() => {
    if (isOpen) {
      optionRefs.current[activeIndex]?.focus();
    }
  }, [activeIndex, isOpen]);

  // 指定インデックスでリストを開く — 範囲外にならないようクランプする
  // Open the list at the specified index, clamped within valid bounds
  const openAt = (index: number) => {
    setActiveIndex(Math.min(Math.max(index, 0), categoryOptions.length - 1));
    setIsOpen(true);
  };

  // 選択を確定してリストを閉じ、トリガーボタンにフォーカスを戻す
  // Commit the selection, close the list, and return focus to the trigger button
  const selectOption = (index: number) => {
    const nextValue = categoryOptions[index];
    if (!nextValue) {
      return;
    }
    onChange(nextValue);
    setIsOpen(false);
    triggerRef.current?.focus();
  };

  // トリガーボタンのキーボードイベント — 矢印キーでリストを開く
  // Keyboard handler for the trigger button — arrow keys open the dropdown
  const handleTriggerKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (disabled) {
      return;
    }
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

  // オプション項目のキーボードイベント — Home/End でリストの端へ移動し、Escape で閉じる
  // Keyboard handler for option items — Home/End jump to list edges; Escape closes the list
  const handleOptionKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
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
      openAt(categoryOptions.length - 1);
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

  return (
    <div ref={rootRef} className="relative w-full">
      {/* ネイティブ select はスクリーンリーダー向けにのみ保持し、見た目は非表示にする / Native select is kept for screen-reader compatibility but hidden visually */}
      <select
        id={selectId}
        className="pointer-events-none absolute h-px w-px opacity-0"
        value={selectedValue}
        disabled={disabled}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      >
        {categoryOptions.map((category) => (
          <option key={category} value={category}>
            {category}
          </option>
        ))}
      </select>

      <button
        ref={triggerRef}
        type="button"
        className={[
          "flex min-h-[52px] w-full items-center justify-between gap-3 rounded-[18px] border px-4 py-3 text-left",
          "border-[#ccdbed] bg-gradient-to-b from-white to-[#f7fbff] text-[0.93rem] font-bold text-[#263f57]",
          "shadow-[inset_0_1px_0_rgba(255,255,255,0.72),0_10px_22px_rgba(42,87,135,0.06)] transition",
          "hover:border-[#80aee5] hover:bg-white hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.78),0_14px_28px_rgba(50,109,171,0.1)]",
          "focus:outline-none focus:ring-4 focus:ring-[#1a73e8]/15",
          isOpen ? "border-[#98bff0] bg-white ring-4 ring-[#1a73e8]/15" : "",
          disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer",
          "[html[data-theme='dark']_&]:border-slate-700",
          "[html[data-theme='dark']_&]:from-slate-900",
          "[html[data-theme='dark']_&]:to-slate-900/90",
          "[html[data-theme='dark']_&]:text-slate-100",
          "[html[data-theme='dark']_&]:hover:border-emerald-400/60",
          "[html[data-theme='dark']_&]:focus:ring-emerald-400/15"
        ].join(" ")}
        aria-haspopup="listbox"
        aria-expanded={isOpen ? "true" : "false"}
        aria-controls={listboxId}
        aria-label="カテゴリを選択"
        disabled={disabled}
        onClick={() => {
          setActiveIndex(selectedIndex);
          setIsOpen((previous) => !previous);
        }}
        onKeyDown={handleTriggerKeyDown}
      >
        <span className="min-w-0 flex-1 truncate">{selectedValue}</span>
        <i
          className={`bi bi-chevron-down shrink-0 text-sm text-[#4f7eb6] transition [html[data-theme='dark']_&]:text-emerald-300${isOpen ? " rotate-180 text-[#1a73e8]" : ""}`}
          aria-hidden="true"
        ></i>
      </button>

      {/* ドロップダウンリスト — isOpen が true の間だけレンダリングする / Dropdown list — rendered only while isOpen is true */}
      {isOpen ? (
        <div
          id={listboxId}
          role="listbox"
          aria-label="カテゴリを選択"
          className={[
            "absolute left-0 right-0 top-[calc(100%+0.48rem)] z-[var(--z-dropdown)] max-h-[min(330px,48vh)] overflow-y-auto rounded-[18px] border p-1.5",
            "border-[#9abee7]/50 bg-gradient-to-b from-white/95 to-[#f6faff]/95 shadow-[0_22px_48px_rgba(17,24,39,0.18),0_8px_18px_rgba(37,99,235,0.1)] backdrop-blur-xl",
            "[html[data-theme='dark']_&]:border-slate-700",
            "[html[data-theme='dark']_&]:from-slate-900/95",
            "[html[data-theme='dark']_&]:to-slate-950/95"
          ].join(" ")}
        >
          {categoryOptions.map((category, index) => {
            const selected = selectedValue === category;
            return (
              <button
                key={category}
                ref={(node) => {
                  optionRefs.current[index] = node;
                }}
                type="button"
                role="option"
                aria-selected={selected ? "true" : "false"}
                tabIndex={activeIndex === index ? 0 : -1}
                className={[
                  "flex min-h-[42px] w-full items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-left text-sm transition",
                  selected
                    ? "border-[#1a73e8]/70 bg-gradient-to-br from-[#0f4aa6] to-[#1a73e8] font-extrabold text-white shadow-[0_10px_20px_rgba(26,115,232,0.18)]"
                    : "border-transparent bg-transparent text-[#263f57] hover:border-[#1a73e8]/20 hover:bg-[#1a73e8]/10 hover:text-[#1559b4] focus:border-[#1a73e8]/20 focus:bg-[#1a73e8]/10 focus:text-[#1559b4] focus:outline-none",
                  "[html[data-theme='dark']_&]:text-slate-100",
                  !selected ? "[html[data-theme='dark']_&]:hover:bg-emerald-400/10 [html[data-theme='dark']_&]:hover:text-emerald-200 [html[data-theme='dark']_&]:focus:bg-emerald-400/10" : ""
                ].join(" ")}
                onClick={() => {
                  selectOption(index);
                }}
                onKeyDown={(event) => {
                  handleOptionKeyDown(event, index);
                }}
              >
                <span className="min-w-0 truncate">{category}</span>
                {selected ? <i className="bi bi-check-lg shrink-0" aria-hidden="true"></i> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

// プロンプト編集用のモーダルダイアログ — 保存中は全フォームを無効化する
// Modal dialog for editing a prompt — disables all form controls while saving
function EditPromptModal({
  formState,
  saving,
  onClose,
  onCategoryChange,
  onChange,
  onSubmit
}: {
  formState: EditPromptFormState;
  saving: boolean;
  onClose: () => void;
  onCategoryChange: (value: string) => void;
  onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  // 複数の入力欄で共通利用するクラス名をまとめて管理する
  // Reusable class string shared across all text inputs and textareas in the modal
  const inputClassName = [
    "w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5",
    "text-sm text-slate-900 shadow-sm outline-none transition",
    "placeholder:text-slate-400",
    "focus:border-primary focus:ring-4 focus:ring-primary/10",
    "disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500",
    "[html[data-theme='dark']_&]:border-slate-700",
    "[html[data-theme='dark']_&]:bg-slate-900/80",
    "[html[data-theme='dark']_&]:text-slate-100",
    "[html[data-theme='dark']_&]:focus:border-emerald-400",
    "[html[data-theme='dark']_&]:focus:ring-emerald-400/15"
  ].join(" ");
  const labelClassName = "mb-2 block text-sm font-semibold text-slate-700 [html[data-theme='dark']_&]:text-slate-200";

  return (
    <div
      id="editModal"
      className="fixed inset-0 z-[var(--z-modal)] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm [html[data-theme='dark']_&]:bg-slate-950/75"
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-labelledby="editPromptModalTitle"
      onClick={(event) => {
        // モーダル背景クリックでも閉じられるが、保存中は誤操作を防ぐためブロックする
        // Allow closing by clicking the backdrop, but block it during save to prevent accidental dismissal
        if (event.target === event.currentTarget && !saving) {
          onClose();
        }
      }}
    >
      <div className="flex max-h-[min(92vh,820px)] w-full max-w-3xl overflow-hidden rounded-2xl border border-white/70 bg-white shadow-2xl shadow-slate-950/25 [html[data-theme='dark']_&]:border-slate-700/80 [html[data-theme='dark']_&]:bg-slate-950" role="document">
        <div className="flex min-h-0 w-full flex-col">
          <div className="flex items-start justify-between gap-4 border-b border-slate-200/80 bg-slate-50 px-6 py-5 [html[data-theme='dark']_&]:border-slate-800 [html[data-theme='dark']_&]:bg-slate-900">
            <div className="flex min-w-0 items-center gap-3">
              <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-lg text-primary ring-1 ring-primary/15 [html[data-theme='dark']_&]:bg-emerald-400/10 [html[data-theme='dark']_&]:text-emerald-300 [html[data-theme='dark']_&]:ring-emerald-400/20" aria-hidden="true">
                <i className="bi bi-pencil-square"></i>
              </span>
              <div>
                <p className="mb-1 text-xs font-bold uppercase tracking-[0.22em] text-primary [html[data-theme='dark']_&]:text-emerald-300">投稿したプロンプト</p>
                <h5 id="editPromptModalTitle" className="m-0 text-xl font-semibold text-slate-950 [html[data-theme='dark']_&]:text-slate-50">
                  プロンプトを編集
                </h5>
              </div>
            </div>
            <button
              type="button"
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 shadow-sm transition hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus:ring-4 focus:ring-primary/10 disabled:cursor-not-allowed disabled:opacity-50 [html[data-theme='dark']_&]:border-slate-700 [html[data-theme='dark']_&]:bg-slate-900 [html[data-theme='dark']_&]:text-slate-300 [html[data-theme='dark']_&]:hover:bg-slate-800 [html[data-theme='dark']_&]:hover:text-white"
              aria-label="閉じる"
              onClick={onClose}
              disabled={saving}
            >
              <i className="bi bi-x-lg" aria-hidden="true"></i>
            </button>
          </div>

          <form id="editForm" className="flex min-h-0 flex-1 flex-col" onSubmit={onSubmit}>
            <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 py-5">
              {/* 編集対象のプロンプト ID を hidden フィールドで保持する / Hold the target prompt ID in a hidden field for form submission */}
              <input type="hidden" id="editPromptId" value={formState.id} readOnly />

              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label htmlFor="editTitle" className={labelClassName}>
                    タイトル
                  </label>
                  <input
                    type="text"
                    className={inputClassName}
                    id="editTitle"
                    name="title"
                    required
                    value={formState.title}
                    onChange={onChange}
                    disabled={saving}
                  />
                </div>

                <div>
                  <label htmlFor="editCategory" className={labelClassName}>
                    カテゴリ
                  </label>
                  <PromptCategorySelect
                    selectId="editCategory"
                    value={formState.category}
                    disabled={saving}
                    onChange={onCategoryChange}
                  />
                </div>
              </div>

              <div>
                <label htmlFor="editContent" className={labelClassName}>
                  内容
                </label>
                <textarea
                  className={`${inputClassName} min-h-44 resize-y leading-6`}
                  id="editContent"
                  name="content"
                  rows={5}
                  required
                  value={formState.content}
                  onChange={onChange}
                  disabled={saving}
                ></textarea>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label htmlFor="editInputExamples" className={labelClassName}>
                    入力例
                  </label>
                  <textarea
                    className={`${inputClassName} min-h-32 resize-y leading-6`}
                    id="editInputExamples"
                    name="inputExamples"
                    rows={3}
                    value={formState.inputExamples}
                    onChange={onChange}
                    disabled={saving}
                  ></textarea>
                </div>

                <div>
                  <label htmlFor="editOutputExamples" className={labelClassName}>
                    出力例
                  </label>
                  <textarea
                    className={`${inputClassName} min-h-32 resize-y leading-6`}
                    id="editOutputExamples"
                    name="outputExamples"
                    rows={3}
                    value={formState.outputExamples}
                    onChange={onChange}
                    disabled={saving}
                  ></textarea>
                </div>
              </div>
            </div>

            <div className="flex flex-col-reverse gap-3 border-t border-slate-200/80 bg-white px-6 py-4 sm:flex-row sm:justify-end [html[data-theme='dark']_&]:border-slate-800 [html[data-theme='dark']_&]:bg-slate-950">
              <button
                type="button"
                className="inline-flex h-11 items-center justify-center rounded-lg border border-slate-200 bg-white px-5 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 focus:outline-none focus:ring-4 focus:ring-primary/10 disabled:cursor-not-allowed disabled:opacity-50 [html[data-theme='dark']_&]:border-slate-700 [html[data-theme='dark']_&]:bg-slate-900 [html[data-theme='dark']_&]:text-slate-200 [html[data-theme='dark']_&]:hover:bg-slate-800"
                onClick={onClose}
                disabled={saving}
              >
                閉じる
              </button>
              <button
                type="submit"
                className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-primary px-5 text-sm font-semibold text-white shadow-lg shadow-emerald-900/10 transition hover:bg-primary-hover focus:outline-none focus:ring-4 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60 [html[data-theme='dark']_&]:shadow-emerald-950/30"
                disabled={saving}
              >
                <i className="bi bi-save" aria-hidden="true"></i>
                {saving ? "更新中..." : "更新する"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

// ユーザー設定ページのメインコンポーネント — すべての設定セクションを統括する
// Main component for the user settings page — orchestrates all settings sections
export default function UserSettingsPage() {
  // 現在表示中のセクションを管理する
  // Track which section is currently displayed
  const [activeSection, setActiveSection] = useState<SettingsSection>("profile");

  // プロフィールフォームの現在値と初期値を別々に保持して「キャンセル」で元に戻せるようにする
  // Keep current and initial profile form values separately so Cancel can restore them
  const [profileForm, setProfileForm] = useState<ProfileFormState>({
    username: "",
    email: "",
    bio: "",
    llmProfileContext: ""
  });
  const [initialProfileForm, setInitialProfileForm] = useState<ProfileFormState>({
    username: "",
    email: "",
    bio: "",
    llmProfileContext: ""
  });
  const [avatarPreviewUrl, setAvatarPreviewUrl] = useState(DEFAULT_AVATAR_URL);
  const [initialAvatarUrl, setInitialAvatarUrl] = useState(DEFAULT_AVATAR_URL);
  const [selectedAvatarFile, setSelectedAvatarFile] = useState<File | null>(null);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileSaveStatus, setProfileSaveStatus] = useState<ProfileSaveStatus | null>(null);
  // トークンをインクリメントすることで保存成功アニメーションを再トリガーする
  // Incrementing this token re-triggers the save-success animation effect
  const [profileSaveEffectToken, setProfileSaveEffectToken] = useState(0);
  const [profileSaveEffectActive, setProfileSaveEffectActive] = useState(false);
  // LLM コンテキストが自動生成のデフォルト値を使っているかどうかを追跡する
  // Track whether the LLM context is currently using the auto-generated default
  const [llmProfileContextUsesGeneratedDefault, setLlmProfileContextUsesGeneratedDefault] = useState(false);
  const [initialLlmProfileContextUsesGeneratedDefault, setInitialLlmProfileContextUsesGeneratedDefault] = useState(false);

  // 投稿済みプロンプト一覧の状態
  // State for the list of prompts authored by this user
  const [myPrompts, setMyPrompts] = useState<PromptRecord[]>([]);
  const [myPromptsLoading, setMyPromptsLoading] = useState(false);
  const [myPromptsError, setMyPromptsError] = useState<string | null>(null);

  // いいねしたプロンプト一覧の状態
  // State for the list of liked prompt entries
  const [likedPrompts, setLikedPrompts] = useState<LikedPrompt[]>([]);
  const [likedPromptsLoading, setLikedPromptsLoading] = useState(false);
  const [likedPromptsError, setLikedPromptsError] = useState<string | null>(null);

  // 編集モーダルの表示制御 — null のときモーダルは非表示
  // Controls the edit modal; null means the modal is hidden
  const [editPromptForm, setEditPromptForm] = useState<EditPromptFormState | null>(null);
  const [promptSaving, setPromptSaving] = useState(false);

  const [themePreference, setThemePreferenceState] = useState<ThemePreference>("auto");

  // Passkey 関連の状態 — 対応有無・一覧・ローディング・操作中フラグを管理する
  // Passkey-related state — tracks support, list, loading, and in-progress operation flags
  const [passkeySupported, setPasskeySupported] = useState(true);
  const [passkeySupportStatus, setPasskeySupportStatus] = useState(PASSKEY_INITIAL_SUPPORT_TEXT);
  const [passkeys, setPasskeys] = useState<PasskeyRecord[]>([]);
  const [passkeysLoading, setPasskeysLoading] = useState(false);
  const [registeringPasskey, setRegisteringPasskey] = useState(false);
  const [deletingPasskeyId, setDeletingPasskeyId] = useState<number | null>(null);
  const [accountDeleteConfirmation, setAccountDeleteConfirmation] = useState("");
  const [accountDeleting, setAccountDeleting] = useState(false);
  const [accountDeleteError, setAccountDeleteError] = useState<string | null>(null);

  // メールアドレス変更フローの状態 — 段階・入力値・送信中フラグ・結果を管理する
  // Email-change flow state — tracks stage, input values, submission flag, and result
  const [emailChangeStage, setEmailChangeStage] = useState<EmailChangeStage>("idle");
  const [emailChangeNewEmail, setEmailChangeNewEmail] = useState("");
  const [emailChangeCode, setEmailChangeCode] = useState("");
  const [emailChangeSubmitting, setEmailChangeSubmitting] = useState(false);
  const [emailChangeStatus, setEmailChangeStatus] = useState<ProfileSaveStatus | null>(null);

  const avatarInputRef = useRef<HTMLInputElement | null>(null);
  // 保存成功アニメーション用タイマーを保持し、再保存時にリセットできるようにする
  // Holds the save-effect timer so it can be cleared and reset on rapid saves
  const profileSaveEffectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 現在のセクションが指定したセクションかどうかを返すコールバック
  // Callback that returns whether the given section is currently active
  const isSectionActive = useCallback(
    (section: SettingsSection) => activeSection === section,
    [activeSection]
  );

  // プロフィール情報を API から取得してフォームに反映する
  // Fetch profile data from the API and populate the form
  const loadProfile = useCallback(async () => {
    try {
      const { payload } = await fetchJsonOrThrow<Record<string, unknown>>(
        "/api/user/profile",
        { credentials: "same-origin" },
        { defaultMessage: "プロフィール情報の取得に失敗しました。" }
      );

      const nextProfile: ProfileFormState = {
        username: asString(payload.username),
        email: asString(payload.email),
        bio: asString(payload.bio),
        llmProfileContext: ""
      };
      const rawLlmProfileContext = payload.llm_profile_context;
      // llm_profile_context が null/undefined の場合はプロフィールから自動生成する
      // Auto-generate LLM context from profile fields when llm_profile_context is null/undefined
      const shouldUseGeneratedDefault = rawLlmProfileContext === null || rawLlmProfileContext === undefined;
      const nextLlmProfileContext = shouldUseGeneratedDefault
        ? buildDefaultLlmProfileContext(nextProfile)
        : asString(rawLlmProfileContext);
      const nextResolvedProfile: ProfileFormState = {
        ...nextProfile,
        llmProfileContext: nextLlmProfileContext
      };
      const nextAvatarUrl = asString(payload.avatar_url) || DEFAULT_AVATAR_URL;

      setProfileForm(nextResolvedProfile);
      setInitialProfileForm(nextResolvedProfile);
      setAvatarPreviewUrl(nextAvatarUrl);
      setInitialAvatarUrl(nextAvatarUrl);
      setSelectedAvatarFile(null);
      setLlmProfileContextUsesGeneratedDefault(shouldUseGeneratedDefault);
      setInitialLlmProfileContextUsesGeneratedDefault(shouldUseGeneratedDefault);
      if (avatarInputRef.current) {
        avatarInputRef.current.value = "";
      }
    } catch (error) {
      console.error("loadProfile:", error instanceof Error ? error.message : String(error));
    }
  }, []);

  // ユーザーが投稿したプロンプト一覧を取得する
  // Fetch the list of prompts authored by the current user
  const loadMyPrompts = useCallback(async () => {
    setMyPromptsLoading(true);
    setMyPromptsError(null);
    try {
      const { payload } = await fetchJsonOrThrow(
        "/prompt_manage/api/my_prompts",
        {
          credentials: "same-origin"
        },
        {
          defaultMessage: "プロンプトの取得に失敗しました。"
        }
      );
      setMyPrompts(parseMyPromptsResponse(payload));
    } catch (error) {
      setMyPrompts([]);
      setMyPromptsError(error instanceof Error ? error.message : "プロンプトの取得に失敗しました。");
    } finally {
      setMyPromptsLoading(false);
    }
  }, []);

  // ユーザーがいいねしたプロンプト一覧を取得する
  // Fetch the list of prompts liked by the current user
  const loadLikedPrompts = useCallback(async () => {
    setLikedPromptsLoading(true);
    setLikedPromptsError(null);
    try {
      const { payload } = await fetchJsonOrThrow(
        "/prompt_manage/api/liked_prompts",
        {
          credentials: "same-origin"
        },
        {
          defaultMessage: "いいねしたプロンプトの取得に失敗しました。"
        }
      );
      setLikedPrompts(parseLikedPromptsResponse(payload));
    } catch (error) {
      setLikedPrompts([]);
      setLikedPromptsError(error instanceof Error ? error.message : "いいねしたプロンプトの取得に失敗しました。");
    } finally {
      setLikedPromptsLoading(false);
    }
  }, []);

  // ブラウザの Passkey 対応を確認してから登録済み Passkey 一覧を取得する
  // Check browser passkey support, then fetch the list of registered passkeys
  const loadPasskeys = useCallback(async () => {
    if (!browserSupportsPasskeys()) {
      setPasskeySupported(false);
      setPasskeySupportStatus("このブラウザではPasskeyを利用できません。");
      setPasskeys([]);
      return;
    }

    setPasskeySupported(true);
    setPasskeySupportStatus("このブラウザはPasskeyに対応しています。");
    setPasskeysLoading(true);

    try {
      const { payload } = await fetchJsonOrThrow<Record<string, unknown>>(
        "/api/passkeys",
        {
          credentials: "same-origin"
        },
        {
          defaultMessage: "Passkey一覧の取得に失敗しました。",
          hasApplicationError: (data) => data.status === "fail"
        }
      );
      const passkeyRecords = Array.isArray(payload.passkeys) ? payload.passkeys : [];
      setPasskeys(normalizePasskeyRecords(passkeyRecords));
    } catch (error) {
      setPasskeys([]);
      showToast(error instanceof Error ? error.message : "Passkey一覧の取得に失敗しました。", { variant: "error" });
    } finally {
      setPasskeysLoading(false);
    }
  }, []);

  // マウント時にページクラスを追加し、テーマ・プロフィール・Passkey を初期ロードする
  // On mount, add the page class and perform initial loads for theme, profile, and passkeys
  useEffect(() => {
    document.body.classList.add("settings-page");

    setThemePreferenceState(getStoredThemePreference());

    const importCustomElements = async () => {
      await import("../scripts/components/popup_menu");
    };
    void importCustomElements();

    void loadProfile();
    void loadPasskeys();

    return () => {
      if (profileSaveEffectTimeoutRef.current) {
        clearTimeout(profileSaveEffectTimeoutRef.current);
      }
      document.body.classList.remove("settings-page");
      document.body.classList.remove("modal-open");
    };
  }, [loadPasskeys, loadProfile]);

  // 保存成功トークンが変わるたびにアニメーションを一定時間表示して自動消灯する
  // Show the save-success animation for a fixed duration each time the token increments
  useEffect(() => {
    if (profileSaveEffectToken === 0) {
      return;
    }

    if (profileSaveEffectTimeoutRef.current) {
      clearTimeout(profileSaveEffectTimeoutRef.current);
    }

    setProfileSaveEffectActive(true);
    profileSaveEffectTimeoutRef.current = setTimeout(() => {
      setProfileSaveEffectActive(false);
      profileSaveEffectTimeoutRef.current = null;
    }, PROFILE_SAVE_EFFECT_DURATION_MS);

    return () => {
      if (profileSaveEffectTimeoutRef.current) {
        clearTimeout(profileSaveEffectTimeoutRef.current);
        profileSaveEffectTimeoutRef.current = null;
      }
    };
  }, [profileSaveEffectToken]);

  // 編集モーダルが開いている間、Escape キーでモーダルを閉じられるようにする
  // While the edit modal is open, allow closing it with the Escape key
  useEffect(() => {
    if (!editPromptForm) {
      return;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !promptSaving) {
        setEditPromptForm(null);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [editPromptForm, promptSaving]);

  // モーダルの開閉に合わせて body に modal-open クラスを付け外しし、背景スクロールを制御する
  // Toggle modal-open on body to prevent background scrolling when the modal is shown
  useEffect(() => {
    document.body.classList.toggle("modal-open", Boolean(editPromptForm));
    return () => {
      document.body.classList.remove("modal-open");
    };
  }, [editPromptForm]);

  // セクション切り替え時に必要なデータを遅延ロードする
  // Lazily load section-specific data when the user navigates to that section
  const handleSectionSelect = useCallback((section: SettingsSection) => {
    setActiveSection(section);

    if (section === "prompts") {
      void loadMyPrompts();
      return;
    }
    if (section === "liked-prompts") {
      void loadLikedPrompts();
      return;
    }
    if (section === "security") {
      void loadPasskeys();
    }
  }, [loadLikedPrompts, loadMyPrompts, loadPasskeys]);

  // テーマ選択を React 状態と localStorage の両方に反映する
  // Apply the selected theme to both React state and localStorage
  const handleThemeSelect = useCallback((preference: ThemePreference) => {
    setThemePreferenceState(preference);
    setThemePreference(preference);
  }, []);

  // プロフィールフィールドの変更を処理する — LLM コンテキストが自動生成の場合は連動更新する
  // Handle profile field changes — auto-update LLM context when it uses the generated default
  const handleProfileInputChange = useCallback(
    (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      const { name, value } = event.target;
      setProfileSaveStatus(null);
      setProfileSaveEffectActive(false);
      setProfileForm((prev) => {
        const nextProfile = {
          ...prev,
          [name]: value
        };

        // LLM コンテキスト欄自体を編集したら「自動生成を使用中」フラグを解除する
        // When the LLM context field itself is edited, stop using the auto-generated default
        if (name === "llmProfileContext") {
          setLlmProfileContextUsesGeneratedDefault(false);
          return nextProfile;
        }

        // 他のフィールドが変わったとき、自動生成中なら LLM コンテキストも再生成する
        // When other fields change and auto-default is active, regenerate the LLM context
        if (llmProfileContextUsesGeneratedDefault) {
          nextProfile.llmProfileContext = buildDefaultLlmProfileContext(nextProfile);
        }
        return nextProfile;
      });
    },
    [llmProfileContextUsesGeneratedDefault]
  );

  // アバター画像ファイルを選択し、FileReader でプレビュー表示する
  // Select an avatar image file and display a preview using FileReader
  const handleAvatarFileChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] || null;
    if (!file) {
      return;
    }
    // 画像以外のファイルは無視してアップロードを防ぐ
    // Ignore non-image files to prevent uploading unsupported types
    if (!file.type.startsWith("image/")) {
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        setAvatarPreviewUrl(reader.result);
      }
    };
    reader.readAsDataURL(file);

    setProfileSaveStatus(null);
    setProfileSaveEffectActive(false);
    setSelectedAvatarFile(file);
  }, []);

  // プロフィール変更をキャンセルして初期値に戻す
  // Cancel profile changes and restore the initial values
  const handleProfileCancel = useCallback(() => {
    setProfileForm(initialProfileForm);
    setAvatarPreviewUrl(initialAvatarUrl);
    setSelectedAvatarFile(null);
    setLlmProfileContextUsesGeneratedDefault(initialLlmProfileContextUsesGeneratedDefault);
    if (avatarInputRef.current) {
      avatarInputRef.current.value = "";
    }
    setProfileSaveStatus(null);
    setProfileSaveEffectActive(false);
  }, [initialAvatarUrl, initialLlmProfileContextUsesGeneratedDefault, initialProfileForm]);

  // プロフィールフォームを送信し、成功時に初期値を更新して「変更なし」状態にする
  // Submit the profile form and update the initial values on success to reset dirty state
  const handleProfileSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    // multipart/form-data でアバターファイルも一緒に送信するため FormData を使う
    // Use FormData to include the avatar file in a multipart/form-data POST
    const formData = new FormData();
    formData.append("username", profileForm.username.trim());
    formData.append("email", profileForm.email.trim());
    formData.append("bio", profileForm.bio.trim());
    formData.append("llm_profile_context", profileForm.llmProfileContext.trim());
    if (selectedAvatarFile) {
      formData.append("avatar", selectedAvatarFile);
    }

    setProfileSaving(true);
    setProfileSaveStatus(null);
    setProfileSaveEffectActive(false);
    try {
      const { payload } = await fetchJsonOrThrow<Record<string, unknown>>(
        "/api/user/profile",
        {
          method: "POST",
          body: formData,
          credentials: "same-origin"
        },
        {
          defaultMessage: "更新失敗"
        }
      );

      const successMessage = asString(payload.message) || "プロフィールを更新しました";
      setProfileSaveStatus({ tone: "success", message: successMessage });
      // トークンをインクリメントして保存成功アニメーションを再起動する
      // Increment the token to restart the save-success animation
      setProfileSaveEffectToken((current) => current + 1);

      const persistedAvatarUrl = asString(payload.avatar_url) || avatarPreviewUrl;
      setAvatarPreviewUrl(persistedAvatarUrl || DEFAULT_AVATAR_URL);
      setInitialAvatarUrl(persistedAvatarUrl || DEFAULT_AVATAR_URL);

      const persistedProfile: ProfileFormState = {
        username: profileForm.username.trim(),
        email: profileForm.email.trim(),
        bio: profileForm.bio.trim(),
        llmProfileContext: profileForm.llmProfileContext.trim()
      };
      setProfileForm(persistedProfile);
      setInitialProfileForm(persistedProfile);
      setSelectedAvatarFile(null);
      setLlmProfileContextUsesGeneratedDefault(false);
      setInitialLlmProfileContextUsesGeneratedDefault(false);
      if (avatarInputRef.current) {
        avatarInputRef.current.value = "";
      }
    } catch (error) {
      setProfileSaveEffectActive(false);
      setProfileSaveStatus({
        tone: "error",
        message: error instanceof Error ? error.message : String(error)
      });
    } finally {
      setProfileSaving(false);
    }
  }, [avatarPreviewUrl, profileForm, selectedAvatarFile]);

  // メールアドレス変更が完了したとき、フォームと初期値の両方に新しいアドレスを反映する
  // After an email change is committed, apply the new address to both form state and initial state
  const applyCommittedEmail = useCallback((email: string) => {
    setProfileForm((prev) => {
      const nextProfile = { ...prev, email };
      if (llmProfileContextUsesGeneratedDefault) {
        nextProfile.llmProfileContext = buildDefaultLlmProfileContext(nextProfile);
      }
      return nextProfile;
    });
    setInitialProfileForm((prev) => {
      const nextProfile = { ...prev, email };
      if (initialLlmProfileContextUsesGeneratedDefault) {
        nextProfile.llmProfileContext = buildDefaultLlmProfileContext(nextProfile);
      }
      return nextProfile;
    });
  }, [initialLlmProfileContextUsesGeneratedDefault, llmProfileContextUsesGeneratedDefault]);

  // メールアドレス変更の第 1 ステップ — 新しいアドレスへの確認コード送信をリクエストする
  // First step of the email-change flow — request a verification code sent to the new address
  const handleRequestEmailChange = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextEmail = emailChangeNewEmail.trim();
    if (!nextEmail) {
      setEmailChangeStatus({ tone: "error", message: "新しいメールアドレスを入力してください。" });
      return;
    }

    setEmailChangeSubmitting(true);
    setEmailChangeStatus(null);
    try {
      await fetchJsonOrThrow<Record<string, unknown>>(
        "/api/user/email/request_change",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ new_email: nextEmail })
        },
        { defaultMessage: "確認メールの送信に失敗しました。" }
      );
      // 現在のメールへの確認コード入力ステージに進む
      // Advance to the stage that collects the verification code sent to the current email
      setEmailChangeStage("current_email");
      setEmailChangeCode("");
      setEmailChangeStatus({
        tone: "success",
        message: "現在のメールアドレスに確認コードを送信しました。"
      });
    } catch (error) {
      setEmailChangeStatus({
        tone: "error",
        message: error instanceof Error ? error.message : "確認メールの送信に失敗しました。"
      });
    } finally {
      setEmailChangeSubmitting(false);
    }
  }, [emailChangeNewEmail]);

  // メールアドレス変更の第 2・第 3 ステップ — 確認コードを検証して変更を完了させる
  // Second and third steps — verify the confirmation code and finalize the email change
  const handleConfirmEmailChange = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const authCode = emailChangeCode.trim();
    if (!authCode) {
      setEmailChangeStatus({ tone: "error", message: "確認コードを入力してください。" });
      return;
    }

    setEmailChangeSubmitting(true);
    setEmailChangeStatus(null);
    try {
      const { payload } = await fetchJsonOrThrow<Record<string, unknown>>(
        "/api/user/email/confirm_change",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ auth_code: authCode })
        },
        { defaultMessage: "確認コードの検証に失敗しました。" }
      );

      const committedEmail = asString(payload.email);
      // email が返ってきた場合は変更完了 — フォームを初期化してアイドル状態に戻す
      // If an email is returned, the change is complete — reset and return to idle state
      if (committedEmail) {
        applyCommittedEmail(committedEmail);
        setEmailChangeNewEmail("");
        setEmailChangeCode("");
        setEmailChangeStage("idle");
        setEmailChangeStatus({
          tone: "success",
          message: "メールアドレスを変更しました。"
        });
        return;
      }

      // stage が new_email であれば新しいメールへのコード確認ステップに進む
      // If stage is new_email, advance to confirming the code sent to the new address
      if (asString(payload.stage) === "new_email") {
        setEmailChangeStage("new_email");
        setEmailChangeCode("");
        setEmailChangeStatus({
          tone: "success",
          message: "新しいメールアドレスに確認コードを送信しました。"
        });
        return;
      }

      setEmailChangeStatus({
        tone: "success",
        message: asString(payload.message) || "確認しました。"
      });
    } catch (error) {
      setEmailChangeStatus({
        tone: "error",
        message: error instanceof Error ? error.message : "確認コードの検証に失敗しました。"
      });
    } finally {
      setEmailChangeSubmitting(false);
    }
  }, [applyCommittedEmail, emailChangeCode]);

  // メールアドレス変更フローを中断してアイドル状態に戻す
  // Abort the email-change flow and reset to idle state
  const handleCancelEmailChange = useCallback(() => {
    setEmailChangeStage("idle");
    setEmailChangeCode("");
    setEmailChangeStatus(null);
  }, []);

  // 編集モーダルを開き、対象プロンプトの現在値をフォームに設定する
  // Open the edit modal and populate the form with the selected prompt's current values
  const handleOpenPromptEdit = useCallback((prompt: PromptRecord) => {
    setEditPromptForm({
      id: asId(prompt.id),
      title: prompt.title,
      category: prompt.category,
      content: prompt.content,
      inputExamples: prompt.inputExamples,
      outputExamples: prompt.outputExamples
    });
  }, []);

  // 確認ダイアログを経てプロンプトを削除し、成功後に一覧を再取得する
  // Delete a prompt after user confirmation, then refresh the list on success
  const handleDeletePrompt = useCallback(async (prompt: PromptRecord) => {
    const promptId = asId(prompt.id);
    if (!promptId) {
      showToast("削除対象のプロンプトが見つかりませんでした。", { variant: "error" });
      return;
    }

    const confirmed = await showConfirmModal("このプロンプトを削除しますか？");
    if (!confirmed) {
      return;
    }

    try {
      const { payload } = await fetchJsonOrThrow(
        `/prompt_manage/api/prompts/${promptId}`,
        {
          method: "DELETE",
          credentials: "same-origin"
        },
        {
          defaultMessage: "プロンプトの削除に失敗しました。"
        }
      );
      const response = parsePromptManageMutationResponse(payload);
      showToast(response.message || "削除しました。", { variant: "success" });
      await loadMyPrompts();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "プロンプトの削除に失敗しました。", { variant: "error" });
    }
  }, [loadMyPrompts]);

  // プロンプト編集フォームの汎用入力変更ハンドラ
  // Generic input change handler for the prompt edit form
  const handleEditPromptChange = useCallback((event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = event.target;
    setEditPromptForm((prev) => {
      if (!prev) {
        return prev;
      }
      return {
        ...prev,
        [name]: value
      };
    });
  }, []);

  // プロンプト編集フォームのカテゴリ変更ハンドラ
  // Handler for category changes in the prompt edit form
  const handleEditPromptCategoryChange = useCallback((value: string) => {
    setEditPromptForm((prev) => {
      if (!prev) {
        return prev;
      }
      return {
        ...prev,
        category: value
      };
    });
  }, []);

  // プロンプト編集フォームを送信して更新 API を呼び出す — 必須フィールドのバリデーションも行う
  // Submit the prompt edit form and call the update API — includes required-field validation
  const handleEditPromptSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editPromptForm) {
      return;
    }

    // 必須フィールドが揃っていない場合はサーバーに送らず早期リターンする
    // Guard against empty required fields before sending the request
    if (
      !editPromptForm.id ||
      !editPromptForm.title.trim() ||
      !editPromptForm.category.trim() ||
      editPromptForm.category === "未選択" ||
      !editPromptForm.content.trim()
    ) {
      showToast("編集フォームの値が不足しています。", { variant: "error" });
      return;
    }

    setPromptSaving(true);
    try {
      const { payload } = await fetchJsonOrThrow(
        `/prompt_manage/api/prompts/${editPromptForm.id}`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json"
          },
          credentials: "same-origin",
          body: JSON.stringify({
            title: editPromptForm.title,
            category: editPromptForm.category,
            content: editPromptForm.content,
            input_examples: editPromptForm.inputExamples,
            output_examples: editPromptForm.outputExamples
          })
        },
        {
          defaultMessage: "プロンプトの更新に失敗しました。"
        }
      );
      const response = parsePromptManageMutationResponse(payload);
      showToast(response.message || "更新しました。", { variant: "success" });
      setEditPromptForm(null);
      await loadMyPrompts();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "プロンプトの更新に失敗しました。", { variant: "error" });
    } finally {
      setPromptSaving(false);
    }
  }, [editPromptForm, loadMyPrompts]);

  // 確認ダイアログを経ていいねを解除する
  // Remove a liked prompt after user confirmation
  const handleUnlikePrompt = useCallback(async (entry: LikedPrompt) => {
    const promptId = asId(entry.promptId);
    if (!promptId) {
      showToast("いいね解除対象のプロンプトが見つかりませんでした。", { variant: "error" });
      return;
    }

    const confirmed = await showConfirmModal("このプロンプトのいいねを解除しますか？");
    if (!confirmed) {
      return;
    }

    try {
      const { payload } = await fetchJsonOrThrow(
        "/prompt_share/api/like",
        {
          method: "DELETE",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt_id: promptId })
        },
        {
          defaultMessage: "いいねの解除に失敗しました。"
        }
      );
      const response = parsePromptManageMutationResponse(payload);
      showToast(response.message || "いいねを解除しました。", { variant: "success" });
      setLikedPrompts((current) => current.filter((item) => asId(item.promptId) !== promptId));
    } catch (error) {
      showToast(error instanceof Error ? error.message : "いいねの解除に失敗しました。", { variant: "error" });
    }
  }, []);

  // ブラウザの Passkey 登録フローを起動し、キャンセル時はトーストを出さない
  // Launch the browser passkey registration flow; silently swallow user-cancelled errors
  const handleRegisterPasskey = useCallback(async () => {
    setRegisteringPasskey(true);
    try {
      await registerPasskey();
      showToast("Passkeyを追加しました。", { variant: "success" });
      await loadPasskeys();
    } catch (error) {
      // ユーザーが自らキャンセルした場合はエラートーストを表示しない
      // Do not show an error toast when the user intentionally cancelled the flow
      if (error instanceof PasskeyCancelledError) {
        return;
      }
      showToast(error instanceof Error ? error.message : "Passkey登録に失敗しました。", { variant: "error" });
    } finally {
      setRegisteringPasskey(false);
    }
  }, [loadPasskeys]);

  // 確認ダイアログを経て指定の Passkey を削除する
  // Delete the specified passkey after user confirmation
  const handleDeletePasskey = useCallback(async (passkeyId: number) => {
    const confirmed = await showConfirmModal("このPasskeyを削除しますか？");
    if (!confirmed) {
      return;
    }

    setDeletingPasskeyId(passkeyId);
    try {
      await fetchJsonOrThrow<Record<string, unknown>>(
        "/api/passkeys/delete",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ passkey_id: passkeyId }),
          credentials: "same-origin"
        },
        {
          defaultMessage: "Passkeyの削除に失敗しました。",
          hasApplicationError: (payload) => payload.status === "fail"
        }
      );
      await loadPasskeys();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Passkeyの削除に失敗しました。", { variant: "error" });
    } finally {
      setDeletingPasskeyId(null);
    }
  }, [loadPasskeys]);

  // アカウントを完全削除する — 確認テキスト入力と二段階ダイアログで誤操作を防ぐ
  // Permanently delete the account — guarded by typed confirmation and a two-step dialog
  const handleDeleteAccount = useCallback(async () => {
    const normalizedConfirmation = accountDeleteConfirmation.trim();
    // 入力テキストが正確に一致しない場合はボタンが無効になるが、防衛的にチェックする
    // Button is already disabled unless text matches, but check defensively
    if (normalizedConfirmation !== ACCOUNT_DELETE_CONFIRMATION_TEXT) {
      setAccountDeleteError(`確認のため「${ACCOUNT_DELETE_CONFIRMATION_TEXT}」と入力してください。`);
      return;
    }

    const confirmed = await showConfirmModal(
      "アカウントと保存済みデータを削除します。この操作は取り消せません。本当に削除しますか？"
    );
    if (!confirmed) {
      return;
    }

    setAccountDeleting(true);
    setAccountDeleteError(null);
    try {
      await fetchJsonOrThrow<Record<string, unknown>>(
        "/api/user/account",
        {
          method: "DELETE",
          headers: {
            "Content-Type": "application/json"
          },
          credentials: "same-origin",
          body: JSON.stringify({ confirmation: normalizedConfirmation })
        },
        {
          defaultMessage: "アカウント削除に失敗しました。"
        }
      );
      showToast("アカウントを削除しました。", { variant: "success" });
      // 削除完了後、少し間を置いてからログインページへリダイレクトする
      // Brief delay before redirecting to login so the toast can be seen
      window.setTimeout(() => {
        window.location.assign("/login");
      }, 400);
    } catch (error) {
      setAccountDeleteError(error instanceof Error ? error.message : "アカウント削除に失敗しました。");
      setAccountDeleting(false);
    }
  }, [accountDeleteConfirmation]);

  // 投稿済みプロンプトのカードリストをメモ化して不要な再レンダリングを防ぐ
  // Memoize the authored prompt card list to avoid unnecessary re-renders
  const myPromptCards = useMemo(
    () => myPrompts.map((prompt, index) => {
      const key = asId(prompt.id) || `${prompt.title}-${index}`;
      return (
        <PromptCard
          key={key}
          prompt={prompt}
          onEdit={handleOpenPromptEdit}
          onDelete={handleDeletePrompt}
        />
      );
    }),
    [handleDeletePrompt, handleOpenPromptEdit, myPrompts]
  );

  // いいねしたプロンプトのカードリストをメモ化して不要な再レンダリングを防ぐ
  // Memoize the liked prompt card list to avoid unnecessary re-renders
  const likedPromptCards = useMemo(
    () => likedPrompts.map((entry, index) => {
      const key = asId(entry.id) || `${entry.title}-${index}`;
      return (
        <LikedPromptCard
          key={key}
          entry={entry}
          onDelete={handleUnlikePrompt}
        />
      );
    }),
    [handleUnlikePrompt, likedPrompts]
  );

  return (
    <>
      <SeoHead
        title="ユーザー設定 | Chat Core"
        description="Chat Coreのユーザー設定ページです。"
        canonicalPath="/settings"
        noindex
      >
        <link
          href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&display=swap"
          rel="stylesheet"
        />
        <link rel="stylesheet" href="/static/css/pages/user_settings/index.css" />
      </SeoHead>

      <div className="user-settings-page">
        <action-menu></action-menu>

        <div className="user-settings-layout">
          {/* サイドバーでセクションを切り替え、コンテンツ側で対応パネルを表示する / Sidebar switches sections; the content area shows the corresponding panel */}
          <SettingsSidebar activeSection={activeSection} onSectionSelect={handleSectionSelect} />

          <main className="settings-content">
            <div className="mb-4">
              <button
                type="button"
                className="settings-back-btn"
                onClick={() => window.history.back()}
                data-tooltip="前の画面に戻る"
                data-tooltip-placement="bottom"
              >
                <i className="bi bi-arrow-left"></i>
              </button>
            </div>

            {/* ---- プロフィールセクション / Profile section ---- */}
            <div id="profile-section" className={`settings-section${isSectionActive("profile") ? " active" : ""}`}>
              {/* 保存成功時に settings-card--save-success クラスを付与してアニメーションを発火する / Add save-success class on success to trigger the animation */}
              <div className={`settings-card${profileSaveEffectActive ? " settings-card--save-success" : ""}`}>
                <h2>ユーザープロフィール設定</h2>
                {profileSaveStatus ? (
                  <p
                    key={`${profileSaveStatus.tone}-${profileSaveEffectToken}`}
                    className={`settings-inline-feedback settings-inline-feedback--${profileSaveStatus.tone}${profileSaveStatus.tone === "success" && profileSaveEffectActive ? " settings-inline-feedback--celebrate" : ""}`}
                    role={profileSaveStatus.tone === "error" ? "alert" : "status"}
                    aria-live={profileSaveStatus.tone === "error" ? "assertive" : "polite"}
                  >
                    <i
                      className={`settings-inline-feedback__icon bi ${profileSaveStatus.tone === "success" ? "bi-check-circle-fill" : "bi-exclamation-circle-fill"}`}
                      aria-hidden="true"
                    ></i>
                    {profileSaveStatus.message}
                  </p>
                ) : null}
                <form id="userSettingsForm" onSubmit={handleProfileSubmit}>
                  {/* アバター画像の選択 — hidden input を重ねてスタイル自由なボタンで起動する / Avatar selection — triggers a hidden file input via a custom button */}
                  <div className="form-group avatar-group">
                    <label className="form-label" htmlFor="avatarInput">
                      プロフィール画像
                    </label>
                    <div className="avatar-preview-wrapper">
                      <img
                        id="avatarPreview"
                        src={avatarPreviewUrl}
                        alt="Avatar Preview"
                        className="avatar-preview"
                      />
                      <button
                        type="button"
                        className="change-avatar-btn"
                        id="changeAvatarBtn"
                        data-tooltip="プロフィール画像を選択"
                        data-tooltip-placement="bottom"
                        onClick={() => avatarInputRef.current?.click()}
                      >
                        <i className="bi bi-pencil-fill"></i>
                      </button>
                    </div>
                    <input
                      ref={avatarInputRef}
                      type="file"
                      id="avatarInput"
                      accept="image/*"
                      hidden
                      onChange={handleAvatarFileChange}
                    />
                  </div>

                  <div className="form-group">
                    <label className="form-label" htmlFor="username">
                      ユーザー名
                    </label>
                    <input
                      type="text"
                      id="username"
                      name="username"
                      className="custom-form-control"
                      placeholder="ユーザー名を入力"
                      value={profileForm.username}
                      onChange={handleProfileInputChange}
                    />
                  </div>

                  {/* メールアドレスは読み取り専用 — 変更はセキュリティセクションで行う / Email is read-only here; changes are made in the Security section */}
                  <div className="form-group">
                    <label className="form-label" htmlFor="email">
                      メールアドレス
                    </label>
                    <input
                      type="email"
                      id="email"
                      name="email"
                      className="custom-form-control"
                      placeholder="example@domain.com"
                      value={profileForm.email}
                      readOnly
                    />
                    <p className="form-help-text">
                      変更はセキュリティのメールアドレス変更から行います。
                    </p>
                  </div>

                  <div className="form-group">
                    <label className="form-label" htmlFor="bio">
                      自己紹介
                    </label>
                    <textarea
                      id="bio"
                      name="bio"
                      rows={4}
                      className="custom-form-control"
                      placeholder="自己紹介を入力 (例: 趣味、好きなことなど)"
                      value={profileForm.bio}
                      onChange={handleProfileInputChange}
                    ></textarea>
                  </div>

                  {/* LLM コンテキスト欄 — 未設定時はプロフィールから自動生成した値が入る / LLM context field — auto-populated from profile fields when not explicitly set */}
                  <div className="form-group">
                    <label className="form-label" htmlFor="llmProfileContext">
                      AI に伝えておきたい情報
                    </label>
                    <textarea
                      id="llmProfileContext"
                      name="llmProfileContext"
                      rows={6}
                      className="custom-form-control"
                      placeholder={"例: 私の名前は山田太郎です。\nメールは taro@example.com です。\n普段は日本語で、結論から短く答えてください。"}
                      value={profileForm.llmProfileContext}
                      onChange={handleProfileInputChange}
                    ></textarea>
                    <p className="form-help-text">
                      未設定時はプロフィール情報が初期値として入ります。保存後は、この欄に残っている内容だけが AI に渡されます。
                    </p>
                  </div>

                  <div className="button-group">
                    <button type="button" className="secondary-button" id="cancelBtn" onClick={handleProfileCancel}>
                      キャンセル
                    </button>
                    {/* 保存中・保存直後でボタンラベルとアイコンを切り替えてフィードバックを伝える / Switch button label and icon to reflect saving / saved states */}
                    <button
                      type="submit"
                      className={`primary-button profile-save-button${profileSaveEffectActive ? " profile-save-button--saved" : ""}`}
                      disabled={profileSaving}
                    >
                      <span className="profile-save-button__content">
                        {profileSaving ? <i className="bi bi-arrow-repeat" aria-hidden="true"></i> : null}
                        {!profileSaving && profileSaveEffectActive ? <i className="bi bi-check2-circle" aria-hidden="true"></i> : null}
                        {profileSaving ? "保存中..." : profileSaveEffectActive ? "保存しました" : "変更を保存"}
                      </span>
                    </button>
                  </div>
                </form>
              </div>
            </div>

            {/* ---- 外観セクション / Appearance section ---- */}
            <div id="appearance-section" className={`settings-section${isSectionActive("appearance") ? " active" : ""}`}>
              <div className="settings-card">
                <h2>外観</h2>
                <p className="settings-section-lead">
                  画面のテーマを切り替えます。「システムに合わせる」を選ぶと OS の設定に追従します。
                </p>

                {/* radiogroup ロールでスクリーンリーダーにグループを認識させる / radiogroup role helps screen readers recognize the group of theme choices */}
                <div className="theme-options" role="radiogroup" aria-label="テーマ選択">
                  {THEME_OPTIONS.map((option) => {
                    const isSelected = themePreference === option.value;
                    return (
                      <button
                        key={option.value}
                        type="button"
                        role="radio"
                        aria-checked={isSelected}
                        className={`theme-option${isSelected ? " is-selected" : ""}`}
                        onClick={() => handleThemeSelect(option.value)}
                      >
                        <span className="theme-option__icon" aria-hidden="true">
                          <i className={option.iconClass}></i>
                        </span>
                        <span className="theme-option__body">
                          <span className="theme-option__label">{option.label}</span>
                          <span className="theme-option__description">{option.description}</span>
                        </span>
                        {isSelected ? (
                          <span className="theme-option__check" aria-hidden="true">
                            <i className="bi bi-check-circle-fill"></i>
                          </span>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* ---- 投稿済みプロンプトセクション / Authored prompts section ---- */}
            <div id="prompts-section" className={`settings-section${isSectionActive("prompts") ? " active" : ""}`}>
              <div className="settings-card">
                <h2>投稿したプロンプト</h2>
                <div className="header-bar">
                  <h3 className="section-title">投稿したプロンプト</h3>
                </div>

                {/* ローディング・エラー・空状態の 3 パターンを排他的に表示する / Show loading, error, or empty state exclusively — only one at a time */}
                {myPromptsLoading ? <InlineLoading label="読み込み中..." className="mb-4" /> : null}
                {!myPromptsLoading && myPromptsError ? <p>{myPromptsError}</p> : null}
                {!myPromptsLoading && !myPromptsError && myPrompts.length === 0 ? <p>プロンプトが存在しません。</p> : null}

                <div id="promptList" className="prompt-grid">
                  {myPromptCards}
                </div>
              </div>
            </div>

            {/* ---- いいね済みプロンプトセクション / Liked prompts section ---- */}
            <div id="liked-prompts-section" className={`settings-section${isSectionActive("liked-prompts") ? " active" : ""}`}>
              <div className="settings-card">
                <h2>いいねしたプロンプト</h2>
                <div className="header-bar">
                  <h3 className="section-title">いいねしたプロンプト</h3>
                </div>

                {likedPromptsLoading ? <InlineLoading label="読み込み中..." className="mb-4" /> : null}
                {!likedPromptsLoading && likedPromptsError ? <p>{likedPromptsError}</p> : null}
                {!likedPromptsLoading && !likedPromptsError && likedPrompts.length === 0 ? (
                  <p>いいねしたプロンプトは存在しません。</p>
                ) : null}

                <div id="likedPromptEntries" className="prompt-grid">
                  {likedPromptCards}
                </div>
              </div>
            </div>

            {/* ---- 通知設定セクション（未実装）/ Notifications section (not yet implemented) ---- */}
            <div
              id="notifications-section"
              className={`settings-section${isSectionActive("notifications") ? " active" : ""}`}
            >
              <div className="settings-card">
                <h2>通知設定</h2>
                <p>通知設定機能は準備中です。</p>
              </div>
            </div>

            {/* ---- セキュリティセクション / Security section ---- */}
            <div id="security-section" className={`settings-section${isSectionActive("security") ? " active" : ""}`}>
              <div className="settings-card">
                <h2>セキュリティ</h2>

                <div className="security-stack">
                  {/* メールアドレス変更パネル — 2 段階確認コードフローを含む / Email-change panel — includes two-step verification code flow */}
                  <div className="security-panel">
                    <h3>メールアドレス変更</h3>
                    <p className="security-panel__description">
                      現在のメールアドレスで確認後、新しいメールアドレスにも確認コードを送信します。
                    </p>
                    <p className="email-change-current">
                      現在: <strong>{profileForm.email || "未取得"}</strong>
                    </p>

                    {emailChangeStatus ? (
                      <p
                        className={`settings-inline-feedback settings-inline-feedback--${emailChangeStatus.tone}`}
                        role={emailChangeStatus.tone === "error" ? "alert" : "status"}
                        aria-live={emailChangeStatus.tone === "error" ? "assertive" : "polite"}
                      >
                        <i
                          className={`settings-inline-feedback__icon bi ${emailChangeStatus.tone === "success" ? "bi-check-circle-fill" : "bi-exclamation-circle-fill"}`}
                          aria-hidden="true"
                        ></i>
                        {emailChangeStatus.message}
                      </p>
                    ) : null}

                    {/* 第 1 フォーム: 新しいメールアドレスの入力 — idle 状態のみ送信ボタンを表示する / First form: enter new email — submit button visible only in idle stage */}
                    <form className="email-change-form" onSubmit={handleRequestEmailChange}>
                      <div className="form-group">
                        <label className="form-label" htmlFor="emailChangeNewEmail">
                          新しいメールアドレス
                        </label>
                        <input
                          type="email"
                          id="emailChangeNewEmail"
                          className="custom-form-control"
                          placeholder="new@example.com"
                          value={emailChangeNewEmail}
                          onChange={(event) => {
                            setEmailChangeNewEmail(event.target.value);
                            setEmailChangeStatus(null);
                          }}
                          disabled={emailChangeSubmitting || emailChangeStage !== "idle"}
                        />
                      </div>
                      {emailChangeStage === "idle" ? (
                        <button
                          type="submit"
                          className="primary-button"
                          disabled={emailChangeSubmitting}
                        >
                          現在のメールへ確認コードを送信
                        </button>
                      ) : null}
                    </form>

                    {/* 第 2・第 3 フォーム: 確認コードの入力 — ステージに応じてラベルを切り替える / Second/third form: enter verification code — label reflects current stage */}
                    {emailChangeStage !== "idle" ? (
                      <form className="email-change-form" onSubmit={handleConfirmEmailChange}>
                        <div className="form-group">
                          <label className="form-label" htmlFor="emailChangeCode">
                            {emailChangeStage === "current_email"
                              ? "現在のメールに届いた確認コード"
                              : "新しいメールに届いた確認コード"}
                          </label>
                          <input
                            type="text"
                            inputMode="numeric"
                            autoComplete="one-time-code"
                            id="emailChangeCode"
                            className="custom-form-control"
                            placeholder="6桁の確認コード"
                            value={emailChangeCode}
                            onChange={(event) => {
                              setEmailChangeCode(event.target.value);
                              setEmailChangeStatus(null);
                            }}
                            disabled={emailChangeSubmitting}
                          />
                        </div>
                        <div className="button-group">
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={handleCancelEmailChange}
                            disabled={emailChangeSubmitting}
                          >
                            中止
                          </button>
                          <button
                            type="submit"
                            className="primary-button"
                            disabled={emailChangeSubmitting}
                          >
                            {emailChangeStage === "current_email"
                              ? "現在のメールを確認"
                              : "変更を完了"}
                          </button>
                        </div>
                      </form>
                    ) : null}
                  </div>

                  {/* Passkey 登録パネル — ブラウザ非対応時はボタンを無効化する / Passkey registration panel — buttons disabled when browser lacks support */}
                  <div className="security-panel">
                    <h3>Passkeys</h3>
                    <p id="passkeySupportStatus">{passkeySupportStatus}</p>
                    <div className="button-group">
                      <button
                        type="button"
                        className="primary-button"
                        id="registerPasskeyBtn"
                        disabled={!passkeySupported || registeringPasskey}
                        onClick={() => {
                          void handleRegisterPasskey();
                        }}
                      >
                        この端末にPasskeyを追加
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        id="refreshPasskeysBtn"
                        disabled={!passkeySupported || passkeysLoading}
                        onClick={() => {
                          void loadPasskeys();
                        }}
                      >
                        一覧を更新
                      </button>
                    </div>
                  </div>

                  {/* 登録済み Passkey の一覧パネル — 削除ボタンは操作中のキーのみ無効化する / Registered passkey list panel — only the key being deleted has its button disabled */}
                  <div className="security-panel">
                    <h3>登録済みPasskeys</h3>
                    <div id="passkeyList" className="passkey-list">
                      {passkeys.length === 0 ? (
                        <p className="passkey-empty">まだPasskeyは登録されていません。</p>
                      ) : (
                        passkeys.map((passkey) => (
                          <div key={passkey.id} className="passkey-item">
                            <div>
                              <strong>{passkey.label}</strong>
                              <div className="passkey-meta">
                                端末種別: {passkey.credentialDeviceType}
                                <br />
                                バックアップ: {passkey.credentialBackedUp ? "あり" : "なし"}
                                <br />
                                作成日時: {formatPasskeyDateTime(passkey.createdAt)}
                                <br />
                                最終利用: {formatPasskeyDateTime(passkey.lastUsedAt)}
                              </div>
                            </div>
                            <button
                              type="button"
                              className="secondary-button delete-passkey-btn"
                              data-passkey-id={String(passkey.id)}
                              disabled={deletingPasskeyId === passkey.id}
                              onClick={() => {
                                void handleDeletePasskey(passkey.id);
                              }}
                            >
                              削除
                            </button>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  {/* 危険ゾーン: アカウント削除 — 確認テキスト入力でボタンを解除し、最終確認ダイアログを挟む / Danger zone: account deletion — text confirmation unlocks the button, then a dialog confirms */}
                  <div className="security-panel security-panel--danger">
                    <div className="account-delete-header">
                      <h3>アカウント削除</h3>
                      <p className="account-delete-copy">
                        アカウント、チャット、メモ、プロンプト、Passkey など保存済みデータを削除します。
                      </p>
                    </div>
                    <div className="account-delete-confirmation">
                      <div className="account-delete-field">
                        <label className="form-label" htmlFor="accountDeleteConfirmation">
                          確認:「{ACCOUNT_DELETE_CONFIRMATION_TEXT}」と入力
                        </label>
                        <input
                          type="text"
                          id="accountDeleteConfirmation"
                          className="custom-form-control"
                          value={accountDeleteConfirmation}
                          onChange={(event) => {
                            setAccountDeleteConfirmation(event.target.value);
                            setAccountDeleteError(null);
                          }}
                          disabled={accountDeleting}
                          autoComplete="off"
                          placeholder={ACCOUNT_DELETE_CONFIRMATION_TEXT}
                        />
                      </div>
                      <button
                        type="button"
                        className="danger-button"
                        disabled={
                          accountDeleting ||
                          accountDeleteConfirmation.trim() !== ACCOUNT_DELETE_CONFIRMATION_TEXT
                        }
                        onClick={() => {
                          void handleDeleteAccount();
                        }}
                      >
                        {accountDeleting ? "削除中..." : "アカウントを削除"}
                      </button>
                    </div>
                    {accountDeleteError ? (
                      <p className="settings-inline-feedback settings-inline-feedback--error" role="alert">
                        <i className="settings-inline-feedback__icon bi bi-exclamation-circle-fill" aria-hidden="true"></i>
                        {accountDeleteError}
                      </p>
                    ) : null}
                  </div>
                </div>
              </div>
            </div>
          </main>
        </div>

        {/* プロンプト編集モーダル — editPromptForm が存在する場合のみレンダリングする / Prompt edit modal — rendered only when editPromptForm is non-null */}
        {editPromptForm ? (
          <EditPromptModal
            formState={editPromptForm}
            saving={promptSaving}
            onClose={() => {
              if (!promptSaving) {
                setEditPromptForm(null);
              }
            }}
            onCategoryChange={handleEditPromptCategoryChange}
            onChange={handleEditPromptChange}
            onSubmit={handleEditPromptSubmit}
          />
        ) : null}
      </div>
    </>
  );
}
