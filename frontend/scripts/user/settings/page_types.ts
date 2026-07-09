import type { ThemePreference } from "../../core/theme";

// 設定画面のどのセクションを表示するかを識別するユニオン型
// Union type identifying which section of the settings page is currently visible
export type SettingsSection = "profile" | "appearance" | "prompts" | "liked-prompts" | "notifications" | "security";

// テーマ選択肢の定義型 — アイコン・ラベル・説明を束ねる
// Type for a single theme option bundling icon, label, and description
export type ThemeOption = {
  value: ThemePreference;
  iconClass: string;
  label: string;
  description: string;
};

// サイドバーナビゲーション項目の型
// Type for a sidebar navigation item
export type SettingsNavItem = {
  section: SettingsSection;
  iconClass: string;
  label: string;
};

// プロフィールフォームの入力値をまとめた型 — 送信前の一時的な状態を保持する
// Type holding the current (unsaved) values of the profile form
export type ProfileFormState = {
  username: string;
  email: string;
  bio: string;
  llmProfileContext: string;
};

// プロフィール保存後のフィードバック表示に使う型
// Type used to display inline feedback after a profile save attempt
export type ProfileSaveStatus = {
  tone: "success" | "error";
  message: string;
};

// メールアドレス変更フローの進行ステージ
// Progress stage of the email-change two-step verification flow
export type EmailChangeStage = "idle" | "current_email" | "new_email";

// プロンプト編集モーダルで管理するフォーム状態
// Form state managed inside the prompt-edit modal
export type EditPromptFormState = {
  id: string;
  title: string;
  category: string;
  content: string;
  inputExamples: string;
  outputExamples: string;
};

// 登録済み Passkey 1 件の情報を表す型
// Represents a single registered passkey record
export type PasskeyRecord = {
  id: number;
  label: string;
  credentialDeviceType: string;
  credentialBackedUp: boolean;
  createdAt: string;
  lastUsedAt: string;
};
