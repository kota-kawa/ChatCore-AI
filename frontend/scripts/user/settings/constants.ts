import type { SettingsNavItem, ThemeOption } from "./page_types";

// 選択可能なテーマの一覧 — ライト・ダーク・システム追従の 3 択
// Available theme choices — light, dark, and system-follow
export const THEME_OPTIONS: ThemeOption[] = [
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

// サイドバーに表示するナビゲーション項目の定義
// Definition of navigation items shown in the settings sidebar
export const SETTINGS_NAV_ITEMS: SettingsNavItem[] = [
  { section: "profile", iconClass: "bi bi-person-circle", label: "プロフィール設定" },
  { section: "appearance", iconClass: "bi bi-palette", label: "外観" },
  { section: "prompts", iconClass: "bi bi-shield-lock", label: "投稿したプロンプト" },
  { section: "liked-prompts", iconClass: "bi bi-heart", label: "いいねしたプロンプト" },
  { section: "notifications", iconClass: "bi bi-bell", label: "通知設定" },
  { section: "security", iconClass: "bi bi-key", label: "セキュリティ" }
];

// アバター未設定時に表示するデフォルト画像のパス
// Path to the default avatar image shown when no avatar is set
export const DEFAULT_AVATAR_URL = "/static/user-icon.png";

// Passkey 対応状況チェック開始前に表示する初期メッセージ
// Initial message shown while checking passkey browser support
export const PASSKEY_INITIAL_SUPPORT_TEXT = "このブラウザの対応状況を確認しています。";

// 保存成功アニメーションの表示時間（ミリ秒）
// Duration in milliseconds to show the save-success animation
export const PROFILE_SAVE_EFFECT_DURATION_MS = 2200;

// アカウント削除を確定させるためにユーザーが入力すべき文字列
// Exact string the user must type to confirm account deletion
export const ACCOUNT_DELETE_CONFIRMATION_TEXT = "DELETE ACCOUNT";

// MCP OAuth の各スコープを、同意画面で利用者が判断できる説明へ対応付ける。
// Map each MCP OAuth scope to a user-facing description for informed consent.
export const MCP_OAUTH_SCOPE_DEFINITIONS: Record<string, {
  label: string;
  description: string;
  iconClass: string;
}> = {
  "prompts:read": {
    label: "公開プロンプトとSKILLを検索・閲覧する",
    description: "公開されているプロンプトとSKILLを検索し、内容を閲覧できます。",
    iconClass: "bi bi-search"
  },
  "prompts:write": {
    label: "公開プロンプトを投稿する",
    description: "あなたの名前で公開プロンプトやSKILLを投稿できます。",
    iconClass: "bi bi-send"
  },
  "memos:read": {
    label: "保存したメモを検索・閲覧する",
    description: "あなたの非公開メモのタイトルと内容を検索・閲覧できます。",
    iconClass: "bi bi-journal-text"
  },
  "memos:write": {
    label: "保存したメモを編集する",
    description: "あなたの非公開メモのタイトルと内容を変更できます。",
    iconClass: "bi bi-pencil-square"
  }
};

// Existing imports keep working while the consent page moves to the complete map.
export const MCP_PROMPTS_WRITE_SCOPE_LABEL = MCP_OAUTH_SCOPE_DEFINITIONS["prompts:write"].label;
