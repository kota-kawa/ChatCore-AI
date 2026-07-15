import { useState } from "react";
import type {
  ChangeEvent,
  FormEvent,
  ReactNode,
  RefObject
} from "react";

import { InlineLoading } from "../ui/inline_loading";
import {
  ACCOUNT_DELETE_CONFIRMATION_TEXT,
  THEME_OPTIONS
} from "../../scripts/user/settings/constants";
import type {
  EmailChangeStage,
  PasskeyRecord,
  ProfileFormState,
  ProfileSaveStatus
} from "../../scripts/user/settings/page_types";
import type {
  McpOAuthClient,
  McpOAuthClientCredentials,
  McpOAuthConnection
} from "../../scripts/user/settings/types";
import type { ThemePreference } from "../../scripts/core/theme";
import { formatPasskeyDateTime } from "../../scripts/user/settings/utils";
import { SettingsProfileSkeleton, SettingsPromptCardSkeletonGrid } from "./settings_skeletons";

export function ProfileSettingsSection({
  isActive,
  profileSaveEffectActive,
  profileSaveStatus,
  profileSaveEffectToken,
  profileLoading,
  profileForm,
  avatarPreviewUrl,
  avatarInputRef,
  profileSaving,
  onProfileSubmit,
  onAvatarFileChange,
  onProfileInputChange,
  onProfileCancel
}: {
  isActive: boolean;
  profileSaveEffectActive: boolean;
  profileSaveStatus: ProfileSaveStatus | null;
  profileSaveEffectToken: number;
  profileLoading: boolean;
  profileForm: ProfileFormState;
  avatarPreviewUrl: string;
  avatarInputRef: RefObject<HTMLInputElement | null>;
  profileSaving: boolean;
  onProfileSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onAvatarFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onProfileInputChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
  onProfileCancel: () => void;
}) {
  return (
    <div id="profile-section" className={`settings-section${isActive ? " active" : ""}`}>
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
        {profileLoading ? (
          <SettingsProfileSkeleton />
        ) : (
        <form id="userSettingsForm" onSubmit={onProfileSubmit}>
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
              onChange={onAvatarFileChange}
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
              onChange={onProfileInputChange}
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
              onChange={onProfileInputChange}
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
              onChange={onProfileInputChange}
            ></textarea>
            <p className="form-help-text">
              未設定時はプロフィール情報が初期値として入ります。保存後は、この欄に残っている内容だけが AI に渡されます。
            </p>
          </div>

          <div className="button-group">
            <button type="button" className="secondary-button" id="cancelBtn" onClick={onProfileCancel}>
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
        )}
      </div>
    </div>
  );
}

export function AppearanceSettingsSection({
  isActive,
  themePreference,
  onThemeSelect
}: {
  isActive: boolean;
  themePreference: ThemePreference;
  onThemeSelect: (preference: ThemePreference) => void;
}) {
  return (
    <div id="appearance-section" className={`settings-section${isActive ? " active" : ""}`}>
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
                onClick={() => onThemeSelect(option.value)}
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
  );
}

// 投稿／いいねプロンプト両セクションで共有するヒーローヘッダー
// Shared hero header for both the authored and liked prompt sections — mirrors the security center layout
function PromptsHero({
  icon,
  eyebrow,
  title,
  lead,
  statLabel,
  statValue
}: {
  icon: string;
  eyebrow: string;
  title: string;
  lead: string;
  statLabel: string;
  statValue: string;
}) {
  return (
    <header className="prompts-hero">
      <div className="prompts-hero__intro">
        <span className="prompts-hero__icon" aria-hidden="true">
          <i className={`bi ${icon}`}></i>
        </span>
        <div>
          <p className="prompts-hero__eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
          <p className="prompts-hero__lead">{lead}</p>
        </div>
      </div>
      <div className="prompts-hero__stat" role="status" aria-live="polite">
        <span className="prompts-hero__stat-label">{statLabel}</span>
        <strong className="prompts-hero__stat-value">{statValue}</strong>
      </div>
    </header>
  );
}

// プロンプト一覧が空のときに表示する案内カード
// Guidance card shown when a prompt list is empty
function PromptsEmptyState({
  icon,
  title,
  description
}: {
  icon: string;
  title: string;
  description: string;
}) {
  return (
    <div className="prompts-empty">
      <span className="prompts-empty__icon" aria-hidden="true">
        <i className={`bi ${icon}`}></i>
      </span>
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}

export function AuthoredPromptsSection({
  isActive,
  loading,
  error,
  promptCount,
  promptCards
}: {
  isActive: boolean;
  loading: boolean;
  error: string | null;
  promptCount: number;
  promptCards: ReactNode;
}) {
  return (
    <div id="prompts-section" className={`settings-section${isActive ? " active" : ""}`}>
      <div className="settings-card settings-card--prompts">
        <PromptsHero
          icon="bi-megaphone"
          eyebrow="Shared prompts"
          title="投稿したプロンプト"
          lead="あなたが公開したプロンプトを一覧で確認し、内容の編集や削除ができます。"
          statLabel="公開数"
          statValue={loading && promptCount === 0 ? "確認中" : `${promptCount}件`}
        />

        {/* ローディング・エラー・空状態の 3 パターンを排他的に表示する / Show loading, error, or empty state exclusively — only one at a time */}
        {loading && promptCount > 0 ? <InlineLoading label="更新中..." className="mb-4" /> : null}
        {!loading && error ? (
          <p className="settings-inline-feedback settings-inline-feedback--error" role="alert">
            <i className="settings-inline-feedback__icon bi bi-exclamation-circle-fill" aria-hidden="true"></i>
            {error}
          </p>
        ) : null}
        {!loading && !error && promptCount === 0 ? (
          <PromptsEmptyState
            icon="bi-file-earmark-plus"
            title="まだ投稿したプロンプトはありません"
            description="共有ページからプロンプトを公開すると、ここに一覧で表示されます。"
          />
        ) : null}

        {(loading && promptCount === 0) || promptCount > 0 ? (
          <div id="promptList" className="prompt-grid">
            {loading && promptCount === 0 ? <SettingsPromptCardSkeletonGrid /> : null}
            {promptCards}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function LikedPromptsSection({
  isActive,
  loading,
  error,
  promptCount,
  promptCards
}: {
  isActive: boolean;
  loading: boolean;
  error: string | null;
  promptCount: number;
  promptCards: ReactNode;
}) {
  return (
    <div id="liked-prompts-section" className={`settings-section${isActive ? " active" : ""}`}>
      <div className="settings-card settings-card--prompts">
        <PromptsHero
          icon="bi-heart-fill"
          eyebrow="Liked prompts"
          title="いいねしたプロンプト"
          lead="気に入って保存したプロンプトの一覧です。内容を見返したり、いいねを解除できます。"
          statLabel="保存数"
          statValue={loading && promptCount === 0 ? "確認中" : `${promptCount}件`}
        />

        {loading && promptCount > 0 ? <InlineLoading label="更新中..." className="mb-4" /> : null}
        {!loading && error ? (
          <p className="settings-inline-feedback settings-inline-feedback--error" role="alert">
            <i className="settings-inline-feedback__icon bi bi-exclamation-circle-fill" aria-hidden="true"></i>
            {error}
          </p>
        ) : null}
        {!loading && !error && promptCount === 0 ? (
          <PromptsEmptyState
            icon="bi-heart"
            title="いいねしたプロンプトはありません"
            description="気になるプロンプトにいいねすると、ここにまとまって表示されます。"
          />
        ) : null}

        {(loading && promptCount === 0) || promptCount > 0 ? (
          <div id="likedPromptEntries" className="prompt-grid">
            {loading && promptCount === 0 ? <SettingsPromptCardSkeletonGrid /> : null}
            {promptCards}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function NotificationsSettingsSection({ isActive }: { isActive: boolean }) {
  return (
    <div
      id="notifications-section"
      className={`settings-section${isActive ? " active" : ""}`}
    >
      <div className="settings-card">
        <h2>通知設定</h2>
        <p>通知設定機能は準備中です。</p>
      </div>
    </div>
  );
}

function SecurityCredentialField({
  id,
  label,
  value,
  secret = false
}: {
  id: string;
  label: string;
  value: string;
  secret?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  const copyValue = async () => {
    if (!navigator.clipboard) {
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="form-group security-credential-field">
      <label className="form-label" htmlFor={id}>{label}</label>
      <div className="security-credential-field__control">
        <input
          id={id}
          className="custom-form-control"
          value={value}
          readOnly
          autoComplete={secret ? "off" : undefined}
        />
        <button
          type="button"
          className={`security-copy-button${copied ? " is-copied" : ""}`}
          aria-label={`${label}をコピー`}
          onClick={() => {
            void copyValue();
          }}
        >
          <i className={`bi ${copied ? "bi-check2" : "bi-copy"}`} aria-hidden="true"></i>
          {copied ? "コピー済み" : "コピー"}
        </button>
      </div>
    </div>
  );
}

function EditableSecurityName({
  value,
  fallbackValue,
  inputId,
  inputLabel,
  onSave
}: {
  value: string;
  fallbackValue: string;
  inputId: string;
  inputLabel: string;
  onSave: (value: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draftValue, setDraftValue] = useState(value);
  const [saving, setSaving] = useState(false);
  const displayValue = value || fallbackValue;

  const saveName = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    try {
      await onSave(draftValue);
      setEditing(false);
    } catch {
      // The parent presents the API error as a toast; keep the field open for correction.
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <form className="editable-security-name editable-security-name--editing" onSubmit={saveName}>
        <label className="sr-only" htmlFor={inputId}>{inputLabel}</label>
        <input
          id={inputId}
          type="text"
          className="custom-form-control"
          value={draftValue}
          maxLength={100}
          autoFocus
          disabled={saving}
          onChange={(event) => {
            setDraftValue(event.target.value);
          }}
        />
        <div className="editable-security-name__actions">
          <button type="button" className="ghost-button" disabled={saving} onClick={() => setEditing(false)}>
            キャンセル
          </button>
          <button type="submit" className="primary-button" disabled={saving}>
            {saving ? "保存中..." : "保存"}
          </button>
        </div>
      </form>
    );
  }

  return (
    <div className="editable-security-name">
      <strong className="passkey-item__title">{displayValue}</strong>
      <button
        type="button"
        className="editable-security-name__edit"
        aria-label={`${inputLabel}を編集`}
        onClick={() => {
          setDraftValue(value || fallbackValue);
          setEditing(true);
        }}
      >
        <i className="bi bi-pencil" aria-hidden="true"></i>
        編集
      </button>
    </div>
  );
}

export function SecuritySettingsSection({
  isActive,
  profileEmail,
  emailChangeStatus,
  emailChangeStage,
  emailChangeNewEmail,
  emailChangeCode,
  emailChangeSubmitting,
  passkeySupportStatus,
  passkeySupported,
  passkeys,
  passkeysLoading,
  registeringPasskey,
  deletingPasskeyId,
  mcpOAuthConnections,
  mcpOAuthConnectionsLoading,
  deletingMcpOAuthConnectionId,
  mcpOAuthClients,
  mcpOAuthClientsLoading,
  mcpOAuthClientIssuing,
  mcpOAuthClientLabel,
  mcpOAuthClientRedirectUri,
  mcpOAuthClientSecretRequired,
  deletingMcpOAuthClientId,
  mcpOAuthClientCredentials,
  accountDeleteConfirmation,
  accountDeleting,
  accountDeleteError,
  onRequestEmailChange,
  onConfirmEmailChange,
  onCancelEmailChange,
  onEmailChangeNewEmailChange,
  onEmailChangeCodeChange,
  onRegisterPasskey,
  onRefreshPasskeys,
  onDeletePasskey,
  onRefreshMcpOAuthConnections,
  onDeleteMcpOAuthConnection,
  onUpdateMcpOAuthConnectionDisplayName,
  onRefreshMcpOAuthClients,
  onMcpOAuthClientLabelChange,
  onMcpOAuthClientRedirectUriChange,
  onMcpOAuthClientSecretRequiredChange,
  onIssueMcpOAuthClient,
  onDeleteMcpOAuthClient,
  onUpdateMcpOAuthClientLabel,
  onAccountDeleteConfirmationChange,
  onDeleteAccount
}: {
  isActive: boolean;
  profileEmail: string;
  emailChangeStatus: ProfileSaveStatus | null;
  emailChangeStage: EmailChangeStage;
  emailChangeNewEmail: string;
  emailChangeCode: string;
  emailChangeSubmitting: boolean;
  passkeySupportStatus: string;
  passkeySupported: boolean;
  passkeys: PasskeyRecord[];
  passkeysLoading: boolean;
  registeringPasskey: boolean;
  deletingPasskeyId: number | null;
  mcpOAuthConnections: McpOAuthConnection[];
  mcpOAuthConnectionsLoading: boolean;
  deletingMcpOAuthConnectionId: string | null;
  mcpOAuthClients: McpOAuthClient[];
  mcpOAuthClientsLoading: boolean;
  mcpOAuthClientIssuing: boolean;
  mcpOAuthClientLabel: string;
  mcpOAuthClientRedirectUri: string;
  mcpOAuthClientSecretRequired: boolean;
  deletingMcpOAuthClientId: string | null;
  mcpOAuthClientCredentials: McpOAuthClientCredentials | null;
  accountDeleteConfirmation: string;
  accountDeleting: boolean;
  accountDeleteError: string | null;
  onRequestEmailChange: (event: FormEvent<HTMLFormElement>) => void;
  onConfirmEmailChange: (event: FormEvent<HTMLFormElement>) => void;
  onCancelEmailChange: () => void;
  onEmailChangeNewEmailChange: (value: string) => void;
  onEmailChangeCodeChange: (value: string) => void;
  onRegisterPasskey: () => void;
  onRefreshPasskeys: () => void;
  onDeletePasskey: (passkeyId: number) => void;
  onRefreshMcpOAuthConnections: () => void;
  onDeleteMcpOAuthConnection: (connection: McpOAuthConnection) => void;
  onUpdateMcpOAuthConnectionDisplayName: (connection: McpOAuthConnection, displayName: string) => Promise<void>;
  onRefreshMcpOAuthClients: () => void;
  onMcpOAuthClientLabelChange: (value: string) => void;
  onMcpOAuthClientRedirectUriChange: (value: string) => void;
  onMcpOAuthClientSecretRequiredChange: (value: boolean) => void;
  onIssueMcpOAuthClient: () => void;
  onDeleteMcpOAuthClient: (client: McpOAuthClient) => void;
  onUpdateMcpOAuthClientLabel: (client: McpOAuthClient, label: string) => Promise<void>;
  onAccountDeleteConfirmationChange: (value: string) => void;
  onDeleteAccount: () => void;
}) {
  return (
    <div id="security-section" className={`settings-section${isActive ? " active" : ""}`}>
      <div className="settings-card settings-card--security">
        <header className="security-hero">
          <div className="security-hero__intro">
            <span className="security-hero__icon" aria-hidden="true">
              <i className="bi bi-shield-check"></i>
            </span>
            <div>
              <p className="security-hero__eyebrow">Security center</p>
              <h2>アカウントを安全に保つ</h2>
              <p className="security-hero__lead">
                サインイン方法、登録メール、外部サービスのアクセス権を一か所で確認・管理できます。
              </p>
            </div>
          </div>

          <div className="security-overview" role="list" aria-label="セキュリティ設定の概要">
            <div className="security-overview__item" role="listitem">
              <span className="security-overview__icon" aria-hidden="true">
                <i className="bi bi-envelope-check"></i>
              </span>
              <span className="security-overview__copy">
                <span>登録メール</span>
                <strong>{profileEmail ? "設定済み" : "未設定"}</strong>
              </span>
            </div>
            <div
              className={`security-overview__item${passkeys.length === 0 ? " is-attention" : ""}`}
              role="listitem"
            >
              <span className="security-overview__icon" aria-hidden="true">
                <i className="bi bi-fingerprint"></i>
              </span>
              <span className="security-overview__copy">
                <span>Passkey</span>
                <strong>
                  {passkeysLoading ? "確認中" : passkeys.length > 0 ? `${passkeys.length}件登録` : "未登録"}
                </strong>
              </span>
            </div>
            <div className="security-overview__item" role="listitem">
              <span className="security-overview__icon" aria-hidden="true">
                <i className="bi bi-plug"></i>
              </span>
              <span className="security-overview__copy">
                <span>外部サービス</span>
                <strong>
                  {mcpOAuthConnectionsLoading
                    ? "確認中"
                    : mcpOAuthConnections.length > 0
                      ? `${mcpOAuthConnections.length}件接続`
                      : "接続なし"}
                </strong>
              </span>
            </div>
          </div>
        </header>

        <nav className="security-jump-nav" aria-label="セキュリティ設定内のメニュー">
          <a href="#security-sign-in">
            <i className="bi bi-person-lock" aria-hidden="true"></i>サインインと本人確認
          </a>
          <a href="#security-connections">
            <i className="bi bi-nodes" aria-hidden="true"></i>外部サービス連携
          </a>
          <a href="#security-danger-zone">
            <i className="bi bi-exclamation-diamond" aria-hidden="true"></i>危険な操作
          </a>
        </nav>

        <div className="security-stack">
          <section id="security-sign-in" className="security-group" aria-labelledby="security-sign-in-title">
            <div className="security-group__heading">
              <span className="security-group__number">01</span>
              <div>
                <h3 id="security-sign-in-title">サインインと本人確認</h3>
                <p>ログインに使う情報と、安全な認証方法を管理します。</p>
              </div>
            </div>
            <div className="security-grid security-grid--account">
          {/* メールアドレス変更パネル — 2 段階確認コードフローを含む / Email-change panel — includes two-step verification code flow */}
          <div className="security-panel security-panel--email">
            <div className="security-panel__head">
              <span className="security-panel__icon" aria-hidden="true">
                <i className="bi bi-envelope-at"></i>
              </span>
              <div className="security-panel__heading">
                <h3>メールアドレス変更</h3>
                <p className="security-panel__description">
                  現在のメールアドレスで確認後、新しいメールアドレスにも確認コードを送信します。
                </p>
              </div>
            </div>
            <p className="email-change-current">
              <span className="email-change-current__label">現在のアドレス</span>
              <strong>{profileEmail || "未取得"}</strong>
            </p>

            <ol className="email-change-steps" aria-label="メールアドレス変更の手順">
              <li className={emailChangeStage === "idle" ? "is-current" : "is-complete"}>
                <span>1</span>
                <small>新しいアドレス</small>
              </li>
              <li
                className={emailChangeStage === "current_email"
                  ? "is-current"
                  : emailChangeStage === "new_email"
                    ? "is-complete"
                    : ""}
              >
                <span>2</span>
                <small>本人確認</small>
              </li>
              <li className={emailChangeStage === "new_email" ? "is-current" : ""}>
                <span>3</span>
                <small>変更を確定</small>
              </li>
            </ol>

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
            <form className="email-change-form" onSubmit={onRequestEmailChange}>
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
                    onEmailChangeNewEmailChange(event.target.value);
                  }}
                  disabled={emailChangeSubmitting || emailChangeStage !== "idle"}
                />
              </div>
              {emailChangeStage === "idle" ? (
                <button
                  type="submit"
                  className="primary-button security-action"
                  disabled={emailChangeSubmitting}
                >
                  <i className="bi bi-send" aria-hidden="true"></i>
                  送信
                </button>
              ) : null}
            </form>

            {/* 第 2・第 3 フォーム: 確認コードの入力 — ステージに応じてラベルを切り替える / Second/third form: enter verification code — label reflects current stage */}
            {emailChangeStage !== "idle" ? (
              <form className="email-change-form" onSubmit={onConfirmEmailChange}>
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
                      onEmailChangeCodeChange(event.target.value);
                    }}
                    disabled={emailChangeSubmitting}
                  />
                </div>
                <div className="button-group">
                  <button
                    type="button"
                    className="ghost-button security-action"
                    onClick={onCancelEmailChange}
                    disabled={emailChangeSubmitting}
                  >
                    <i className="bi bi-x-lg" aria-hidden="true"></i>
                    中止
                  </button>
                  <button
                    type="submit"
                    className="primary-button security-action"
                    disabled={emailChangeSubmitting}
                  >
                    <i className="bi bi-check2" aria-hidden="true"></i>
                    {emailChangeStage === "current_email"
                      ? "確認"
                      : "完了"}
                  </button>
                </div>
              </form>
            ) : null}
          </div>

          {/* Passkey 登録パネル — ブラウザ非対応時はボタンを無効化する / Passkey registration panel — buttons disabled when browser lacks support */}
          <div className="security-panel security-panel--passkeys">
            <div className="security-panel__head">
              <span className="security-panel__icon" aria-hidden="true">
                <i className="bi bi-fingerprint"></i>
              </span>
              <div className="security-panel__heading">
                <h3>Passkey</h3>
                <p className="security-panel__description">
                  パスワードの代わりに、指紋・顔認証や端末のロック解除でサインインできます。
                </p>
                <span
                  className={`security-status-pill security-status-pill--${passkeySupported ? "ok" : "muted"}`}
                  id="passkeySupportStatus"
                >
                  <i
                    className={`bi ${passkeySupported ? "bi-check-circle-fill" : "bi-info-circle-fill"}`}
                    aria-hidden="true"
                  ></i>
                  {passkeySupportStatus}
                </span>
              </div>
            </div>
            <div className="security-actions">
              <button
                type="button"
                className="primary-button security-action"
                id="registerPasskeyBtn"
                disabled={!passkeySupported || registeringPasskey}
                onClick={() => {
                  void onRegisterPasskey();
                }}
              >
                <i className="bi bi-plus-lg" aria-hidden="true"></i>
                {registeringPasskey ? "追加中..." : "追加"}
              </button>
              <button
                type="button"
                className="ghost-button security-action"
                id="refreshPasskeysBtn"
                disabled={!passkeySupported || passkeysLoading}
                onClick={() => {
                  void onRefreshPasskeys();
                }}
              >
                <i
                  className={`bi bi-arrow-clockwise${passkeysLoading ? " security-action__spin" : ""}`}
                  aria-hidden="true"
                ></i>
                更新
              </button>
            </div>
            <div className="security-panel__subhead">
              <div>
                <span className="security-panel__kicker">Trusted devices</span>
                <h4>登録済みの端末</h4>
              </div>
              <span className="security-count" aria-label={`登録済みPasskey ${passkeys.length}件`}>
                {passkeys.length}
              </span>
            </div>
            <div id="passkeyList" className="passkey-list" aria-live="polite" aria-busy={passkeysLoading}>
              {passkeysLoading && passkeys.length === 0 ? (
                <div className="passkey-empty">
                  <i className="bi bi-arrow-repeat security-action__spin" aria-hidden="true"></i>
                  <span>登録済みの端末を確認しています。</span>
                </div>
              ) : passkeys.length === 0 ? (
                <div className="passkey-empty">
                  <i className="bi bi-shield-slash" aria-hidden="true"></i>
                  <span><strong>まだPasskeyはありません</strong>追加すると、パスワードを入力せず安全にログインできます。</span>
                </div>
              ) : (
                passkeys.map((passkey) => (
                  <div key={passkey.id} className="passkey-item">
                    <span className="passkey-item__icon" aria-hidden="true">
                      <i className="bi bi-shield-lock-fill"></i>
                    </span>
                    <div className="passkey-item__body">
                      <strong className="passkey-item__title">{passkey.label}</strong>
                      <dl className="security-meta">
                        <div className="security-meta__row">
                          <dt>端末種別</dt>
                          <dd>{passkey.credentialDeviceType}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>バックアップ</dt>
                          <dd>{passkey.credentialBackedUp ? "あり" : "なし"}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>作成日時</dt>
                          <dd>{formatPasskeyDateTime(passkey.createdAt)}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>最終利用</dt>
                          <dd>{formatPasskeyDateTime(passkey.lastUsedAt)}</dd>
                        </div>
                      </dl>
                    </div>
                    <button
                      type="button"
                      className="danger-ghost-button delete-passkey-btn"
                      data-passkey-id={String(passkey.id)}
                      disabled={deletingPasskeyId === passkey.id}
                      onClick={() => {
                        void onDeletePasskey(passkey.id);
                      }}
                    >
                      <i className="bi bi-trash3" aria-hidden="true"></i>
                      {deletingPasskeyId === passkey.id ? "削除中..." : "削除"}
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
            </div>
          </section>

          <section id="security-connections" className="security-group" aria-labelledby="security-connections-title">
            <div className="security-group__heading">
              <span className="security-group__number">02</span>
              <div>
                <h3 id="security-connections-title">外部サービス連携</h3>
                <p>AIサービスに許可したアクセスと、連携用の認証情報を管理します。</p>
              </div>
            </div>
            <div className="security-grid">

          <div className="security-panel" id="connected-ai-services">
            <div className="security-panel__head">
              <span className="security-panel__icon" aria-hidden="true">
                <i className="bi bi-robot"></i>
              </span>
              <div className="security-panel__heading">
                <h3>接続中のAIサービス</h3>
                <p className="security-panel__description">
                  外部AIサービスに、公開プロンプトを投稿する権限を付与した連携です。不要になった連携は解除できます。
                </p>
              </div>
            </div>
            <div className="security-actions">
              <button
                type="button"
                className="ghost-button security-action"
                disabled={mcpOAuthConnectionsLoading}
                onClick={() => {
                  void onRefreshMcpOAuthConnections();
                }}
              >
                <i
                  className={`bi bi-arrow-clockwise${mcpOAuthConnectionsLoading ? " security-action__spin" : ""}`}
                  aria-hidden="true"
                ></i>
                更新
              </button>
            </div>
            <div className="passkey-list" aria-live="polite" aria-busy={mcpOAuthConnectionsLoading}>
              {mcpOAuthConnectionsLoading ? (
                <div className="passkey-empty">
                  <i className="bi bi-arrow-repeat" aria-hidden="true"></i>
                  <span>AIサービス連携を読み込んでいます。</span>
                </div>
              ) : mcpOAuthConnections.length === 0 ? (
                <div className="passkey-empty">
                  <i className="bi bi-plug" aria-hidden="true"></i>
                  <span>接続中のAIサービスはありません。</span>
                </div>
              ) : (
                mcpOAuthConnections.map((connection) => (
                  <div key={connection.id} className="passkey-item">
                    <span className="passkey-item__icon" aria-hidden="true">
                      <i className="bi bi-robot"></i>
                    </span>
                    <div className="passkey-item__body">
                      <EditableSecurityName
                        value={connection.display_name || ""}
                        fallbackValue={connection.client_name}
                        inputId={`mcpOAuthConnection-${connection.id}`}
                        inputLabel={`${connection.client_name}の表示名`}
                        onSave={(displayName) => onUpdateMcpOAuthConnectionDisplayName(connection, displayName)}
                      />
                      <dl className="security-meta">
                        <div className="security-meta__row">
                          <dt>連携先の名称</dt>
                          <dd>{connection.client_name}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>接続先</dt>
                          <dd>{connection.client_host || "不明"}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>接続日時</dt>
                          <dd>{formatPasskeyDateTime(connection.created_at)}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>最終利用</dt>
                          <dd>{connection.last_used_at ? formatPasskeyDateTime(connection.last_used_at) : "未使用"}</dd>
                        </div>
                      </dl>
                    </div>
                    <button
                      type="button"
                      className="danger-ghost-button delete-passkey-btn"
                      disabled={deletingMcpOAuthConnectionId === connection.id}
                      onClick={() => {
                        void onDeleteMcpOAuthConnection(connection);
                      }}
                    >
                      <i className="bi bi-x-circle" aria-hidden="true"></i>
                      {deletingMcpOAuthConnectionId === connection.id ? "解除中..." : "解除"}
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="security-panel security-panel--advanced">
            <div className="security-panel__head">
              <span className="security-panel__icon" aria-hidden="true">
                <i className="bi bi-key-fill"></i>
              </span>
              <div className="security-panel__heading">
                <span className="security-panel__kicker">Advanced</span>
                <h3>連携用の認証情報</h3>
                <p className="security-panel__description">
                  通常は接続先の自動設定を使い、手動設定が必要な場合だけ認証情報を発行します。
                </p>
              </div>
            </div>
            <div className="security-advisory">
              <i className="bi bi-info-circle" aria-hidden="true"></i>
              <p>対応するMCPクライアントは自動的に認証を設定します。OAuthクライアントIDやシークレットをここで発行する必要はありません。</p>
            </div>
            <div className="security-client-form">
              <div className="security-client-form__intro">
                <h4>手動設定用の認証情報を発行</h4>
                <p className="security-panel__description">
                  事前登録を要求するサービスだけに使います。コールバックURLを指定しない場合は既定値を使用します。
                </p>
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="mcpOAuthClientLabel">認証情報の名前 <span>必須</span></label>
                <input
                  id="mcpOAuthClientLabel"
                  type="text"
                  className="custom-form-control"
                  value={mcpOAuthClientLabel}
                  maxLength={100}
                  placeholder="例: 社内AIコネクター"
                  required
                  disabled={mcpOAuthClientIssuing}
                  onChange={(event) => {
                    onMcpOAuthClientLabelChange(event.target.value);
                  }}
                />
              </div>
              <div className="form-group security-client-form__uri">
                <label className="form-label" htmlFor="mcpOAuthClientRedirectUri">コールバックURL（リダイレクトURI） <span>任意</span></label>
                <input
                  id="mcpOAuthClientRedirectUri"
                  type="url"
                  className="custom-form-control"
                  value={mcpOAuthClientRedirectUri}
                  maxLength={2048}
                  placeholder="https://service.example/callback"
                  disabled={mcpOAuthClientIssuing}
                  onChange={(event) => {
                    onMcpOAuthClientRedirectUriChange(event.target.value);
                  }}
                />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="mcpOAuthClientSecretRequired">
                  <input
                    id="mcpOAuthClientSecretRequired"
                    type="checkbox"
                    checked={mcpOAuthClientSecretRequired}
                    disabled={mcpOAuthClientIssuing}
                    onChange={(event) => {
                      onMcpOAuthClientSecretRequiredChange(event.target.checked);
                    }}
                  />
                  OAuthクライアントシークレットを発行する
                </label>
                <p className="security-panel__description">接続先がクライアントシークレットを要求する場合だけ選択してください。未選択時はPKCE対応の公開クライアントとして発行します。</p>
              </div>
              <button
                type="button"
                className="primary-button security-action"
                disabled={mcpOAuthClientsLoading || mcpOAuthClientIssuing || !mcpOAuthClientLabel.trim()}
                onClick={onIssueMcpOAuthClient}
              >
                <i className="bi bi-key" aria-hidden="true"></i>
                {mcpOAuthClientIssuing ? "発行中..." : "手動用の認証情報を発行"}
              </button>
            </div>
            {mcpOAuthClientCredentials ? (
              <div className="security-credentials-result">
                <p className="settings-inline-feedback settings-inline-feedback--success" role="status">
                  <i className="settings-inline-feedback__icon bi bi-check-circle-fill" aria-hidden="true"></i>
                  <span><strong>認証情報を発行しました</strong>{mcpOAuthClientCredentials.client_secret ? "シークレットはページを離れると再表示できません。今すぐ安全な場所へコピーしてください。" : "公開クライアントとして発行しました。シークレットは不要です。"}</span>
                </p>
                <div className="security-credentials-result__grid">
                  <SecurityCredentialField id="mcpOAuthServerUrl" label="MCPサーバーURL" value={mcpOAuthClientCredentials.mcp_server_url} />
                  <SecurityCredentialField id="mcpOAuthRedirectUri" label="コールバックURL（リダイレクトURI）" value={mcpOAuthClientCredentials.redirect_uri} />
                  <SecurityCredentialField id="mcpOAuthClientId" label="OAuthクライアントID" value={mcpOAuthClientCredentials.client_id} />
                  {mcpOAuthClientCredentials.client_secret ? (
                    <SecurityCredentialField id="mcpOAuthClientSecret" label="OAuthクライアントシークレット" value={mcpOAuthClientCredentials.client_secret} secret />
                  ) : null}
                </div>
              </div>
            ) : null}
            <div className="security-panel__subhead">
              <div>
                <span className="security-panel__kicker">Credentials</span>
                <h4>保存済みの認証情報</h4>
              </div>
              <button
                type="button"
                className="security-icon-button"
                aria-label="認証情報の一覧を更新"
                disabled={mcpOAuthClientsLoading}
                onClick={() => {
                  void onRefreshMcpOAuthClients();
                }}
              >
                <i className={`bi bi-arrow-clockwise${mcpOAuthClientsLoading ? " security-action__spin" : ""}`} aria-hidden="true"></i>
              </button>
            </div>
            <div className="passkey-list" aria-live="polite" aria-busy={mcpOAuthClientsLoading}>
              {mcpOAuthClientsLoading ? (
                <div className="passkey-empty">
                  <i className="bi bi-arrow-repeat" aria-hidden="true"></i>
                  <span>連携用認証情報を読み込んでいます。</span>
                </div>
              ) : mcpOAuthClients.length === 0 ? (
                <div className="passkey-empty">
                  <i className="bi bi-key" aria-hidden="true"></i>
                  <span>保存済みの認証情報はありません。</span>
                </div>
              ) : (
                mcpOAuthClients.map((client) => (
                  <div key={client.client_id} className="passkey-item">
                    <span className="passkey-item__icon" aria-hidden="true">
                      <i className="bi bi-key-fill"></i>
                    </span>
                    <div className="passkey-item__body">
                      <EditableSecurityName
                        value={client.label}
                        fallbackValue="（名前なし）"
                        inputId={`mcpOAuthClient-${client.client_id}`}
                        inputLabel={`${client.label || "認証情報"}の名前`}
                        onSave={(label) => onUpdateMcpOAuthClientLabel(client, label)}
                      />
                      <dl className="security-meta">
                        <div className="security-meta__row">
                          <dt>クライアントID</dt>
                          <dd>{client.client_id}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>コールバックURL</dt>
                          <dd>{client.redirect_uri}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>クライアント種別</dt>
                          <dd>{client.token_endpoint_auth_method === "none" ? "公開クライアント（シークレットなし）" : "機密クライアント（シークレットあり）"}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>発行日時</dt>
                          <dd>{formatPasskeyDateTime(client.created_at)}</dd>
                        </div>
                      </dl>
                    </div>
                    <button
                      type="button"
                      className="danger-ghost-button delete-passkey-btn"
                      disabled={deletingMcpOAuthClientId === client.client_id}
                      onClick={() => {
                        void onDeleteMcpOAuthClient(client);
                      }}
                    >
                      <i className="bi bi-trash3" aria-hidden="true"></i>
                      {deletingMcpOAuthClientId === client.client_id ? "削除中..." : "削除"}
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
            </div>
          </section>

          {/* 危険ゾーン: アカウント削除 — 確認テキスト入力でボタンを解除し、最終確認ダイアログを挟む / Danger zone: account deletion — text confirmation unlocks the button, then a dialog confirms */}
          <section id="security-danger-zone" className="security-group security-group--danger" aria-labelledby="security-danger-title">
            <div className="security-group__heading">
              <span className="security-group__number">03</span>
              <div>
                <h3 id="security-danger-title">危険な操作</h3>
                <p>アカウント全体に影響する、取り消しできない操作です。</p>
              </div>
            </div>
          <div className="security-panel security-panel--danger">
            <div className="account-delete-header">
              <span className="security-panel__icon security-panel__icon--danger" aria-hidden="true">
                <i className="bi bi-exclamation-triangle"></i>
              </span>
              <div className="account-delete-header__text">
                <h3>アカウント削除</h3>
                <p className="account-delete-copy">
                  アカウント、チャット、メモ、プロンプト、Passkey など保存済みデータを削除します。この操作は取り消せません。
                </p>
              </div>
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
                    onAccountDeleteConfirmationChange(event.target.value);
                  }}
                  disabled={accountDeleting}
                  autoComplete="off"
                  placeholder={ACCOUNT_DELETE_CONFIRMATION_TEXT}
                />
              </div>
              <button
                type="button"
                className="danger-button security-action"
                disabled={
                  accountDeleting ||
                  accountDeleteConfirmation.trim() !== ACCOUNT_DELETE_CONFIRMATION_TEXT
                }
                onClick={() => {
                  void onDeleteAccount();
                }}
              >
                <i className="bi bi-trash3" aria-hidden="true"></i>
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
          </section>
        </div>
      </div>
    </div>
  );
}
