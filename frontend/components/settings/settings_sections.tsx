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
  LANGUAGE_OPTIONS,
  MCP_OAUTH_SCOPE_DEFINITIONS,
  MCP_OAUTH_SCOPE_DEFINITIONS_EN,
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
import { SettingsProfileSkeleton, SettingsPromptCardSkeletonGrid } from "./settings_skeletons";
import { useTranslation } from "../../contexts/locale_context";
import type { Locale } from "../../lib/i18n/config";

export function LanguageSettingsSection({
  isActive,
  locale,
  saving,
  onLocaleSelect
}: {
  isActive: boolean;
  locale: Locale;
  saving: boolean;
  onLocaleSelect: (locale: Locale) => void;
}) {
  const { t } = useTranslation();
  return (
    <section
      id="language-section"
      className={`settings-section${isActive ? " active" : ""}`}
      data-section="language"
      hidden={!isActive}
    >
      <div className="settings-card">
        <h2>{t("settings.languageHeading")}</h2>
        <p className="settings-section-lead">{t("settings.languageDescription")}</p>

        {/* radiogroup ロールでスクリーンリーダーに言語の選択グループを認識させる / radiogroup role helps screen readers recognize the group of language choices */}
        <div
          className="language-options"
          role="radiogroup"
          aria-label={t("settings.languageHeading")}
          aria-busy={saving}
        >
          {LANGUAGE_OPTIONS.map((option) => {
            const isSelected = locale === option.value;
            return (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={isSelected}
                className={`language-option${isSelected ? " is-selected" : ""}`}
                data-agent-id={`settings.language.${option.value}`}
                lang={option.value}
                // 保存中も操作を受け付ける。無効化すると保存が終わるまでのクリックが
                // 捨てられ、続けて切り替えたときに反応しないように見えるため、進行中で
                // あることは radiogroup の aria-busy でのみ伝える。
                // Stay clickable while saving. Disabling drops clicks until the save
                // settles, which makes rapid switches look unresponsive, so progress is
                // conveyed through the radiogroup's aria-busy alone.
                onClick={() => onLocaleSelect(option.value)}
              >
                {/* 書記体系のグリフを大きく見せることで、言語が読めなくてもカードを判別できる / A large script glyph keeps each card identifiable even when its language is unreadable */}
                <span className="language-option__glyph" aria-hidden="true">{option.glyph}</span>
                <span className="language-option__body">
                  <span className="language-option__label">
                    {t(option.labelKey)}
                    <span className="language-option__code" aria-hidden="true">{option.code}</span>
                  </span>
                  <span className="language-option__description">{t(option.descriptionKey)}</span>
                </span>
                <span className="language-option__check" aria-hidden="true">
                  <i className="bi bi-check-circle-fill"></i>
                </span>
              </button>
            );
          })}
        </div>

        {saving ? <InlineLoading className="language-options__status" label={t("common.saving")} /> : null}
      </div>
    </section>
  );
}

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
  const { t } = useTranslation();
  return (
    <div id="profile-section" className={`settings-section${isActive ? " active" : ""}`}>
      {/* 保存成功時に settings-card--save-success クラスを付与してアニメーションを発火する / Add save-success class on success to trigger the animation */}
      <div className={`settings-card${profileSaveEffectActive ? " settings-card--save-success" : ""}`}>
        <h2>{t("settings.profileHeading")}</h2>
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
              {t("settings.avatar")}
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
                data-tooltip={t("settings.chooseAvatar")}
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
              {t("settings.username")}
            </label>
            <input
              type="text"
              id="username"
              name="username"
              className="custom-form-control"
              placeholder={t("settings.usernamePlaceholder")}
              value={profileForm.username}
              onChange={onProfileInputChange}
            />
          </div>

          {/* メールアドレスは読み取り専用 — 変更はセキュリティセクションで行う / Email is read-only here; changes are made in the Security section */}
          <div className="form-group">
            <label className="form-label" htmlFor="email">
              {t("settings.email")}
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
              {t("settings.emailHelp")}
            </p>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="bio">
              {t("settings.bio")}
            </label>
            <textarea
              id="bio"
              name="bio"
              rows={4}
              className="custom-form-control"
              placeholder={t("settings.bioPlaceholder")}
              value={profileForm.bio}
              onChange={onProfileInputChange}
            ></textarea>
          </div>

          {/* LLM コンテキスト欄 — 未設定時はプロフィールから自動生成した値が入る / LLM context field — auto-populated from profile fields when not explicitly set */}
          <div className="form-group">
            <label className="form-label" htmlFor="llmProfileContext">
              {t("settings.aiContext")}
            </label>
            <textarea
              id="llmProfileContext"
              name="llmProfileContext"
              rows={6}
              className="custom-form-control"
              placeholder={t("settings.aiContextPlaceholder")}
              value={profileForm.llmProfileContext}
              onChange={onProfileInputChange}
            ></textarea>
            <p className="form-help-text">
              {t("settings.aiContextHelp")}
            </p>
          </div>

          <div className="button-group">
            <button type="button" className="secondary-button" id="cancelBtn" onClick={onProfileCancel}>
              {t("common.cancel")}
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
                {profileSaving ? t("common.saving") : profileSaveEffectActive ? t("settings.saved") : t("settings.saveChanges")}
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
  const { t } = useTranslation();
  const themeCopy: Record<ThemePreference, { label: string; description: string }> = {
    light: { label: t("settings.themeLight"), description: t("settings.themeLightDescription") },
    dark: { label: t("settings.themeDark"), description: t("settings.themeDarkDescription") },
    auto: { label: t("settings.themeSystem"), description: t("settings.themeSystemDescription") }
  };
  return (
    <div id="appearance-section" className={`settings-section${isActive ? " active" : ""}`}>
      <div className="settings-card">
        <h2>{t("settings.appearance")}</h2>
        <p className="settings-section-lead">
          {t("settings.appearanceDescription")}
        </p>

        {/* radiogroup ロールでスクリーンリーダーにグループを認識させる / radiogroup role helps screen readers recognize the group of theme choices */}
        <div className="theme-options" role="radiogroup" aria-label={t("settings.themeSelection")}>
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
                  <span className="theme-option__label">{themeCopy[option.value].label}</span>
                  <span className="theme-option__description">{themeCopy[option.value].description}</span>
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
  const { t } = useTranslation();
  return (
    <div id="prompts-section" className={`settings-section${isActive ? " active" : ""}`}>
      <div className="settings-card settings-card--prompts">
        <PromptsHero
          icon="bi-megaphone"
          eyebrow="Shared prompts"
          title={t("settings.prompts")}
          lead={t("settings.publishedLead")}
          statLabel={t("settings.publishedCount")}
          statValue={loading && promptCount === 0 ? t("settings.checking") : t("settings.items", { count: promptCount })}
        />

        {/* ローディング・エラー・空状態の 3 パターンを排他的に表示する / Show loading, error, or empty state exclusively — only one at a time */}
        {loading && promptCount > 0 ? <InlineLoading label={t("settings.updating")} className="mb-4" /> : null}
        {!loading && error ? (
          <p className="settings-inline-feedback settings-inline-feedback--error" role="alert">
            <i className="settings-inline-feedback__icon bi bi-exclamation-circle-fill" aria-hidden="true"></i>
            {error}
          </p>
        ) : null}
        {!loading && !error && promptCount === 0 ? (
          <PromptsEmptyState
            icon="bi-file-earmark-plus"
            title={t("settings.noPublished")}
            description={t("settings.noPublishedHelp")}
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
  const { t } = useTranslation();
  return (
    <div id="liked-prompts-section" className={`settings-section${isActive ? " active" : ""}`}>
      <div className="settings-card settings-card--prompts">
        <PromptsHero
          icon="bi-heart-fill"
          eyebrow="Liked prompts"
          title={t("settings.likedPrompts")}
          lead={t("settings.likedLead")}
          statLabel={t("settings.savedCount")}
          statValue={loading && promptCount === 0 ? t("settings.checking") : t("settings.items", { count: promptCount })}
        />

        {loading && promptCount > 0 ? <InlineLoading label={t("settings.updating")} className="mb-4" /> : null}
        {!loading && error ? (
          <p className="settings-inline-feedback settings-inline-feedback--error" role="alert">
            <i className="settings-inline-feedback__icon bi bi-exclamation-circle-fill" aria-hidden="true"></i>
            {error}
          </p>
        ) : null}
        {!loading && !error && promptCount === 0 ? (
          <PromptsEmptyState
            icon="bi-heart"
            title={t("settings.noLiked")}
            description={t("settings.noLikedHelp")}
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
  const { t } = useTranslation();
  return (
    <div
      id="notifications-section"
      className={`settings-section${isActive ? " active" : ""}`}
    >
      <div className="settings-card">
        <h2>{t("settings.notifications")}</h2>
        <p>{t("settings.notificationsComingSoon")}</p>
      </div>
    </div>
  );
}

function SecurityCredentialField({
  id,
  label,
  value,
  secret = false,
  placeholder
}: {
  id: string;
  label: string;
  value: string;
  secret?: boolean;
  placeholder?: string;
}) {
  const { t } = useTranslation();
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
          placeholder={placeholder}
          readOnly
          autoComplete={secret ? "off" : undefined}
        />
        <button
          type="button"
          className={`security-copy-button${copied ? " is-copied" : ""}`}
          aria-label={copied ? t("settings.copiedField", { label }) : t("settings.copyField", { label })}
          title={copied ? t("common.copied") : t("common.copy")}
          disabled={!value}
          onClick={() => {
            void copyValue();
          }}
        >
          <i className={`bi ${copied ? "bi-check2" : "bi-copy"}`} aria-hidden="true"></i>
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
  const { t } = useTranslation();
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
            {t("common.cancel")}
          </button>
          <button type="submit" className="primary-button" disabled={saving}>
            {saving ? t("common.saving") : t("common.save")}
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
        aria-label={t("settings.editField", { label: inputLabel })}
        onClick={() => {
          setDraftValue(value || fallbackValue);
          setEditing(true);
        }}
      >
        <i className="bi bi-pencil" aria-hidden="true"></i>
        {t("common.edit")}
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
  mcpOAuthServerUrl,
  mcpOAuthClientIssuing,
  mcpOAuthClientLabel,
  mcpOAuthClientRedirectUri,
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
  mcpOAuthServerUrl: string;
  mcpOAuthClientIssuing: boolean;
  mcpOAuthClientLabel: string;
  mcpOAuthClientRedirectUri: string;
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
  onIssueMcpOAuthClient: () => void;
  onDeleteMcpOAuthClient: (client: McpOAuthClient) => void;
  onUpdateMcpOAuthClientLabel: (client: McpOAuthClient, label: string) => Promise<void>;
  onAccountDeleteConfirmationChange: (value: string) => void;
  onDeleteAccount: () => void;
}) {
  const { t, locale, formatDate } = useTranslation();
  const formatSecurityDate = (value: string) => value
    ? formatDate(value, { dateStyle: "medium", timeStyle: "short" })
    : t("settings.neverUsed");
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
              <h2>{t("settings.securityHeading")}</h2>
              <p className="security-hero__lead">
                {t("settings.securityLead")}
              </p>
            </div>
          </div>

          <div className="security-overview" role="list" aria-label={t("settings.securityOverview")}>
            <div className="security-overview__item" role="listitem">
              <span className="security-overview__icon" aria-hidden="true">
                <i className="bi bi-envelope-check"></i>
              </span>
              <span className="security-overview__copy">
                <span>{t("settings.registeredEmail")}</span>
                <strong>{profileEmail ? t("settings.configured") : t("settings.notConfigured")}</strong>
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
                  {passkeysLoading ? t("settings.checking") : passkeys.length > 0 ? t("settings.registeredCount", { count: passkeys.length }) : t("settings.notRegistered")}
                </strong>
              </span>
            </div>
            <div className="security-overview__item" role="listitem">
              <span className="security-overview__icon" aria-hidden="true">
                <i className="bi bi-plug"></i>
              </span>
              <span className="security-overview__copy">
                <span>{t("settings.externalServices")}</span>
                <strong>
                  {mcpOAuthConnectionsLoading
                    ? t("settings.checking")
                    : mcpOAuthConnections.length > 0
                      ? t("settings.connectedCount", { count: mcpOAuthConnections.length })
                      : t("settings.notConnected")}
                </strong>
              </span>
            </div>
          </div>
        </header>

        <nav className="security-jump-nav" aria-label={t("settings.securityMenu")}>
          <a href="#security-sign-in">
            <i className="bi bi-person-lock" aria-hidden="true"></i>{t("settings.signInVerification")}
          </a>
          <a href="#security-connections">
            <i className="bi bi-nodes" aria-hidden="true"></i>{t("settings.connections")}
          </a>
          <a href="#security-danger-zone">
            <i className="bi bi-exclamation-diamond" aria-hidden="true"></i>{t("settings.dangerousActions")}
          </a>
        </nav>

        <div className="security-stack">
          <section id="security-sign-in" className="security-group" aria-labelledby="security-sign-in-title">
            <div className="security-group__heading">
              <span className="security-group__number">01</span>
              <div>
                <h3 id="security-sign-in-title">{t("settings.signInVerification")}</h3>
                <p>{t("settings.signInHelp")}</p>
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
                <h3>{t("settings.changeEmail")}</h3>
                <p className="security-panel__description">
                  {t("settings.changeEmailDescription")}
                </p>
              </div>
            </div>
            <p className="email-change-current">
              <span className="email-change-current__label">{t("settings.currentAddress")}</span>
              <strong>{profileEmail || t("settings.notLoaded")}</strong>
            </p>

            <ol className="email-change-steps" aria-label={t("settings.changeEmailSteps")}>
              <li className={emailChangeStage === "idle" ? "is-current" : "is-complete"}>
                <span>1</span>
                <small>{t("settings.newAddress")}</small>
              </li>
              <li
                className={emailChangeStage === "current_email"
                  ? "is-current"
                  : emailChangeStage === "new_email"
                    ? "is-complete"
                    : ""}
              >
                <span>2</span>
                <small>{t("settings.identityCheck")}</small>
              </li>
              <li className={emailChangeStage === "new_email" ? "is-current" : ""}>
                <span>3</span>
                <small>{t("settings.confirmChange")}</small>
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
                  {t("settings.newEmail")}
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
                  {t("settings.send")}
                </button>
              ) : null}
            </form>

            {/* 第 2・第 3 フォーム: 確認コードの入力 — ステージに応じてラベルを切り替える / Second/third form: enter verification code — label reflects current stage */}
            {emailChangeStage !== "idle" ? (
              <form className="email-change-form" onSubmit={onConfirmEmailChange}>
                <div className="form-group">
                  <label className="form-label" htmlFor="emailChangeCode">
                    {emailChangeStage === "current_email"
                      ? t("settings.currentEmailCode")
                      : t("settings.newEmailCode")}
                  </label>
                  <input
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    id="emailChangeCode"
                    className="custom-form-control"
                    placeholder={t("settings.codePlaceholder")}
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
                    {t("settings.abort")}
                  </button>
                  <button
                    type="submit"
                    className="primary-button security-action"
                    disabled={emailChangeSubmitting}
                  >
                    <i className="bi bi-check2" aria-hidden="true"></i>
                    {emailChangeStage === "current_email"
                      ? t("settings.verify")
                      : t("settings.complete")}
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
                  {t("settings.passkeyDescription")}
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
                {registeringPasskey ? t("settings.adding") : t("settings.add")}
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
                {t("settings.refresh")}
              </button>
            </div>
            <div className="security-panel__subhead">
              <div>
                <span className="security-panel__kicker">Trusted devices</span>
                <h4>{t("settings.registeredDevices")}</h4>
              </div>
              <span className="security-count" aria-label={t("settings.passkeysCount", { count: passkeys.length })}>
                {passkeys.length}
              </span>
            </div>
            <div id="passkeyList" className="passkey-list" aria-live="polite" aria-busy={passkeysLoading}>
              {passkeysLoading && passkeys.length === 0 ? (
                <div className="passkey-empty">
                  <i className="bi bi-arrow-repeat security-action__spin" aria-hidden="true"></i>
                  <span>{t("settings.loadingDevices")}</span>
                </div>
              ) : passkeys.length === 0 ? (
                <div className="passkey-empty">
                  <i className="bi bi-shield-slash" aria-hidden="true"></i>
                  <span><strong>{t("settings.noPasskeys")}</strong>{t("settings.noPasskeysHelp")}</span>
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
                          <dt>{t("settings.deviceType")}</dt>
                          <dd>{passkey.credentialDeviceType}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>{t("settings.backup")}</dt>
                          <dd>{passkey.credentialBackedUp ? t("settings.available") : t("settings.unavailable")}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>{t("settings.createdAt")}</dt>
                          <dd>{formatSecurityDate(passkey.createdAt)}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>{t("settings.lastUsed")}</dt>
                          <dd>{formatSecurityDate(passkey.lastUsedAt)}</dd>
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
                      {deletingPasskeyId === passkey.id ? t("settings.deleting") : t("common.delete")}
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
                <h3 id="security-connections-title">{t("settings.connections")}</h3>
                <p>{t("settings.connectionsHelp")}</p>
              </div>
            </div>
            <div className="security-grid">

          <div className="security-panel" id="connected-ai-services">
            <div className="security-panel__head">
              <span className="security-panel__icon" aria-hidden="true">
                <i className="bi bi-robot"></i>
              </span>
              <div className="security-panel__heading">
                <h3>{t("settings.connectedAi")}</h3>
                <p className="security-panel__description">
                  {locale === "en" ? "Review the Chat Core capabilities granted to external AI services and disconnect access you no longer need." : "外部AIサービスに許可したChat-Core機能を確認できます。不要になった連携は解除できます。"}
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
                {t("settings.refresh")}
              </button>
            </div>
            <div className="passkey-list" aria-live="polite" aria-busy={mcpOAuthConnectionsLoading}>
              {mcpOAuthConnectionsLoading ? (
                <div className="passkey-empty">
                  <i className="bi bi-arrow-repeat" aria-hidden="true"></i>
                  <span>{locale === "en" ? "Loading AI service connections." : "AIサービス連携を読み込んでいます。"}</span>
                </div>
              ) : mcpOAuthConnections.length === 0 ? (
                <div className="passkey-empty">
                  <i className="bi bi-plug" aria-hidden="true"></i>
                  <span>{t("settings.noConnectedAi")}</span>
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
                        inputLabel={t("settings.displayName", { name: connection.client_name })}
                        onSave={(displayName) => onUpdateMcpOAuthConnectionDisplayName(connection, displayName)}
                      />
                      <dl className="security-meta">
                        <div className="security-meta__row">
                          <dt>{t("settings.serviceName")}</dt>
                          <dd>{connection.client_name}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>{t("settings.destination")}</dt>
                          <dd>{connection.client_host || t("settings.unknown")}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>{t("settings.permissions")}</dt>
                          <dd>
                            {connection.scopes.map((scope) => (
                              <span key={scope} className="d-block">
                                {(locale === "en" ? MCP_OAUTH_SCOPE_DEFINITIONS_EN : MCP_OAUTH_SCOPE_DEFINITIONS)[scope]?.label || scope}
                              </span>
                            ))}
                          </dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>{t("settings.connectedAt")}</dt>
                          <dd>{formatSecurityDate(connection.created_at)}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>{t("settings.lastUsed")}</dt>
                          <dd>{formatSecurityDate(connection.last_used_at || "")}</dd>
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
                      {deletingMcpOAuthConnectionId === connection.id ? t("settings.disconnecting") : t("settings.disconnect")}
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="security-panel security-panel--advanced">
            <div className="security-panel__head">
              <span className="security-panel__icon" aria-hidden="true">
                <i className="bi bi-plug-fill"></i>
              </span>
              <div className="security-panel__heading">
                <h3>{locale === "en" ? "MCP connection" : "MCP接続"}</h3>
                <p className="security-panel__description">
                  {t("settings.mcpDescription")}
                </p>
              </div>
            </div>
            <div className="security-server-endpoint">
              <SecurityCredentialField
                id="mcpOAuthServerUrl"
                label={t("settings.mcpServerUrl")}
                value={mcpOAuthServerUrl}
                placeholder={mcpOAuthClientsLoading ? t("common.loading") : t("settings.urlUnavailable")}
              />
              <p className="security-server-endpoint__description">
                {locale === "en" ? "This endpoint is shared by MCP-compatible clients. Paste the URL into the client’s MCP server settings." : "MCP対応クライアントに共通して使用する接続先です。このURLをクライアントのMCPサーバー設定に貼り付けてください。"}
              </p>
            </div>
            <details className="security-client-details">
              <summary>
                <span>{t("settings.oauthDetails")}</span>
                <i className="bi bi-chevron-down" aria-hidden="true"></i>
              </summary>
              <div className="security-client-details__body">
                <div className="security-advisory">
                  <i className="bi bi-info-circle" aria-hidden="true"></i>
                  <p>{t("settings.oauthGuidance")}</p>
                </div>
                <div className="security-client-form">
                  <div className="security-client-form__intro">
                    <h4>{locale === "en" ? "Issue OAuth credentials" : "OAuth認証情報を発行"}</h4>
                    <p className="security-panel__description">
                      {locale === "en" ? "Enter a name for the credential. The default callback URL is used when you leave it blank." : "認証情報の名前を入力してください。コールバックURLを指定しない場合は既定値を使用します。"}
                    </p>
                  </div>
                  <div className="form-group security-client-form__name">
                    <label className="form-label" htmlFor="mcpOAuthClientLabel">{t("settings.oauthName")} <span>{t("settings.required")}</span></label>
                    <input
                      id="mcpOAuthClientLabel"
                      type="text"
                      className="custom-form-control"
                      value={mcpOAuthClientLabel}
                      maxLength={100}
                      placeholder={t("settings.oauthNamePlaceholder")}
                      required
                      disabled={mcpOAuthClientIssuing}
                      onChange={(event) => {
                        onMcpOAuthClientLabelChange(event.target.value);
                      }}
                    />
                  </div>
                  <div className="form-group security-client-form__uri">
                    <label className="form-label" htmlFor="mcpOAuthClientRedirectUri">{t("settings.callbackUrl")} <span>{t("settings.optional")}</span></label>
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
                  <button
                    type="button"
                    className="primary-button security-action security-client-form__submit"
                    disabled={mcpOAuthClientsLoading || mcpOAuthClientIssuing || !mcpOAuthClientLabel.trim()}
                    onClick={onIssueMcpOAuthClient}
                  >
                    <i className="bi bi-key" aria-hidden="true"></i>
                    {mcpOAuthClientIssuing ? t("settings.issuing") : t("settings.issue")}
                  </button>
                </div>
                {mcpOAuthClientCredentials ? (
                  <div className="security-credentials-result">
                    <p className="settings-inline-feedback settings-inline-feedback--success" role="status">
                      <i className="settings-inline-feedback__icon bi bi-check-circle-fill" aria-hidden="true"></i>
                      <span><strong>{t("settings.credentialsIssued")}</strong>{t("settings.credentialsIssuedHelp")}</span>
                    </p>
                    <div className="security-credentials-result__grid">
                      <SecurityCredentialField id="mcpOAuthRedirectUri" label={t("settings.callbackUrl")} value={mcpOAuthClientCredentials.redirect_uri} />
                      <SecurityCredentialField id="mcpOAuthClientId" label={locale === "en" ? "OAuth client ID" : "OAuthクライアントID"} value={mcpOAuthClientCredentials.client_id} />
                      {mcpOAuthClientCredentials.client_secret ? (
                        <SecurityCredentialField id="mcpOAuthClientSecret" label={locale === "en" ? "OAuth client secret" : "OAuthクライアントシークレット"} value={mcpOAuthClientCredentials.client_secret} secret />
                      ) : null}
                    </div>
                  </div>
                ) : null}
              </div>
            </details>
            <div className="security-panel__subhead">
              <div>
                <span className="security-panel__kicker">Credentials</span>
                <h4>{t("settings.savedCredentials")}</h4>
              </div>
              <button
                type="button"
                className="security-icon-button"
                aria-label={t("settings.refresh")}
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
                  <span>{t("settings.loadingCredentials")}</span>
                </div>
              ) : mcpOAuthClients.length === 0 ? (
                <div className="passkey-empty">
                  <i className="bi bi-key" aria-hidden="true"></i>
                  <span>{t("settings.noCredentials")}</span>
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
                        fallbackValue={locale === "en" ? "(unnamed)" : "（名前なし）"}
                        inputId={`mcpOAuthClient-${client.client_id}`}
                        inputLabel={t("settings.credentialName", { name: client.label || t("settings.oauthName") })}
                        onSave={(label) => onUpdateMcpOAuthClientLabel(client, label)}
                      />
                      <dl className="security-meta">
                        <div className="security-meta__row">
                          <dt>{t("settings.clientId")}</dt>
                          <dd>{client.client_id}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>{t("settings.callbackUrl")}</dt>
                          <dd>{client.redirect_uri}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>{t("settings.clientType")}</dt>
                          <dd>{client.token_endpoint_auth_method === "none" ? t("settings.publicClient") : t("settings.confidentialClient")}</dd>
                        </div>
                        <div className="security-meta__row">
                          <dt>{t("settings.issuedAt")}</dt>
                          <dd>{formatSecurityDate(client.created_at)}</dd>
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
                      {deletingMcpOAuthClientId === client.client_id ? t("settings.deleting") : t("common.delete")}
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
                <h3 id="security-danger-title">{t("settings.dangerousActions")}</h3>
                <p>{t("settings.dangerLead")}</p>
              </div>
            </div>
          <div className="security-panel security-panel--danger">
            <div className="account-delete-header">
              <span className="security-panel__icon security-panel__icon--danger" aria-hidden="true">
                <i className="bi bi-exclamation-triangle"></i>
              </span>
              <div className="account-delete-header__text">
                <h3>{t("settings.deleteAccount")}</h3>
                <p className="account-delete-copy">
                  {t("settings.deleteAccountDescription")}
                </p>
              </div>
            </div>
            <div className="account-delete-confirmation">
              <div className="account-delete-field">
                <label className="form-label" htmlFor="accountDeleteConfirmation">
                  {t("settings.confirmDelete", { text: ACCOUNT_DELETE_CONFIRMATION_TEXT })}
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
                {accountDeleting ? t("settings.deleting") : t("settings.deleteAccount")}
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
