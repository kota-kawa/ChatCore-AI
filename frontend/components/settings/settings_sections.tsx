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
  ClaudeOAuthClientCredentials,
  ClaudeOAuthClientStatus,
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
      <div className="settings-card">
        <h2>投稿したプロンプト</h2>
        <div className="header-bar">
          <h3 className="section-title">投稿したプロンプト</h3>
        </div>

        {/* ローディング・エラー・空状態の 3 パターンを排他的に表示する / Show loading, error, or empty state exclusively — only one at a time */}
        {loading && promptCount > 0 ? <InlineLoading label="更新中..." className="mb-4" /> : null}
        {!loading && error ? <p>{error}</p> : null}
        {!loading && !error && promptCount === 0 ? <p>プロンプトが存在しません。</p> : null}

        <div id="promptList" className="prompt-grid">
          {loading && promptCount === 0 ? <SettingsPromptCardSkeletonGrid /> : null}
          {promptCards}
        </div>
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
      <div className="settings-card">
        <h2>いいねしたプロンプト</h2>
        <div className="header-bar">
          <h3 className="section-title">いいねしたプロンプト</h3>
        </div>

        {loading && promptCount > 0 ? <InlineLoading label="更新中..." className="mb-4" /> : null}
        {!loading && error ? <p>{error}</p> : null}
        {!loading && !error && promptCount === 0 ? (
          <p>いいねしたプロンプトは存在しません。</p>
        ) : null}

        <div id="likedPromptEntries" className="prompt-grid">
          {loading && promptCount === 0 ? <SettingsPromptCardSkeletonGrid /> : null}
          {promptCards}
        </div>
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
  claudeOAuthClient,
  claudeOAuthClientLoading,
  claudeOAuthClientIssuing,
  claudeOAuthClientCredentials,
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
  onIssueClaudeOAuthClient,
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
  claudeOAuthClient: ClaudeOAuthClientStatus | null;
  claudeOAuthClientLoading: boolean;
  claudeOAuthClientIssuing: boolean;
  claudeOAuthClientCredentials: ClaudeOAuthClientCredentials | null;
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
  onIssueClaudeOAuthClient: () => void;
  onAccountDeleteConfirmationChange: (value: string) => void;
  onDeleteAccount: () => void;
}) {
  return (
    <div id="security-section" className={`settings-section${isActive ? " active" : ""}`}>
      <div className="settings-card">
        <h2>セキュリティ</h2>

        <div className="security-stack">
          {/* メールアドレス変更パネル — 2 段階確認コードフローを含む / Email-change panel — includes two-step verification code flow */}
          <div className="security-panel">
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
                  className="primary-button"
                  disabled={emailChangeSubmitting}
                >
                  現在のメールへ確認コードを送信
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
                    className="secondary-button"
                    onClick={onCancelEmailChange}
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
            <div className="security-panel__head">
              <span className="security-panel__icon" aria-hidden="true">
                <i className="bi bi-fingerprint"></i>
              </span>
              <div className="security-panel__heading">
                <h3>Passkeys</h3>
                <p className="security-panel__description">
                  パスワードの代わりに、指紋・顔認証や端末のロック解除でサインインできます。
                </p>
              </div>
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
            <div className="button-group">
              <button
                type="button"
                className="primary-button"
                id="registerPasskeyBtn"
                disabled={!passkeySupported || registeringPasskey}
                onClick={() => {
                  void onRegisterPasskey();
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
                  void onRefreshPasskeys();
                }}
              >
                一覧を更新
              </button>
            </div>
          </div>

          {/* 登録済み Passkey の一覧パネル — 削除ボタンは操作中のキーのみ無効化する / Registered passkey list panel — only the key being deleted has its button disabled */}
          <div className="security-panel">
            <div className="security-panel__head">
              <span className="security-panel__icon" aria-hidden="true">
                <i className="bi bi-shield-lock"></i>
              </span>
              <div className="security-panel__heading">
                <h3>登録済みPasskeys</h3>
                <p className="security-panel__description">
                  この端末やアカウントに登録されているPasskeyの一覧です。
                </p>
              </div>
            </div>
            <div id="passkeyList" className="passkey-list">
              {passkeys.length === 0 ? (
                <div className="passkey-empty">
                  <i className="bi bi-shield-slash" aria-hidden="true"></i>
                  <span>まだPasskeyは登録されていません。</span>
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
                      className="secondary-button delete-passkey-btn"
                      data-passkey-id={String(passkey.id)}
                      disabled={deletingPasskeyId === passkey.id}
                      onClick={() => {
                        void onDeletePasskey(passkey.id);
                      }}
                    >
                      削除
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="security-panel">
            <div className="security-panel__head">
              <span className="security-panel__icon" aria-hidden="true">
                <i className="bi bi-robot"></i>
              </span>
              <div className="security-panel__heading">
                <h3>AIサービス連携</h3>
                <p className="security-panel__description">
                  外部AIサービスに、公開プロンプトを投稿する権限を付与した連携です。不要になった連携は解除できます。
                </p>
              </div>
            </div>
            <div className="button-group">
              <button
                type="button"
                className="secondary-button"
                disabled={mcpOAuthConnectionsLoading}
                onClick={() => {
                  void onRefreshMcpOAuthConnections();
                }}
              >
                一覧を更新
              </button>
            </div>
            <div className="passkey-list" aria-live="polite">
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
                      <strong className="passkey-item__title">{connection.client_name}</strong>
                      <dl className="security-meta">
                        <div className="security-meta__row">
                          <dt>接続先</dt>
                          <dd>{connection.client_host}</dd>
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
                      className="secondary-button delete-passkey-btn"
                      disabled={deletingMcpOAuthConnectionId === connection.id}
                      onClick={() => {
                        void onDeleteMcpOAuthConnection(connection);
                      }}
                    >
                      {deletingMcpOAuthConnectionId === connection.id ? "解除中..." : "連携を解除"}
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="security-panel">
            <div className="security-panel__head">
              <span className="security-panel__icon" aria-hidden="true">
                <i className="bi bi-key-fill"></i>
              </span>
              <div className="security-panel__heading">
                <h3>Claude接続用認証情報</h3>
                <p className="security-panel__description">
                  Claudeで接続に失敗する場合に、詳細設定へ入力する専用のOAuth認証情報を発行します。再発行すると、以前の認証情報と連携は失効します。
                </p>
              </div>
            </div>
            {claudeOAuthClientLoading ? (
              <p className="security-panel__description">Claude用認証情報を確認しています。</p>
            ) : claudeOAuthClient?.configured ? (
              <dl className="security-meta">
                <div className="security-meta__row">
                  <dt>クライアントID</dt>
                  <dd>{claudeOAuthClient.client_id}</dd>
                </div>
                <div className="security-meta__row">
                  <dt>MCPサーバーURL</dt>
                  <dd>{claudeOAuthClient.mcp_server_url}</dd>
                </div>
                <div className="security-meta__row">
                  <dt>発行日時</dt>
                  <dd>{formatPasskeyDateTime(claudeOAuthClient.created_at)}</dd>
                </div>
              </dl>
            ) : (
              <p className="security-panel__description">Claude用認証情報はまだ発行されていません。</p>
            )}
            <div className="button-group">
              <button
                type="button"
                className="primary-button"
                disabled={claudeOAuthClientLoading || claudeOAuthClientIssuing}
                onClick={onIssueClaudeOAuthClient}
              >
                {claudeOAuthClientIssuing
                  ? "発行中..."
                  : claudeOAuthClient?.configured
                    ? "認証情報を再発行"
                    : "Claude用認証情報を発行"}
              </button>
            </div>
            {claudeOAuthClientCredentials ? (
              <div className="security-stack">
                <p className="settings-inline-feedback settings-inline-feedback--success" role="status">
                  <i className="settings-inline-feedback__icon bi bi-check-circle-fill" aria-hidden="true"></i>
                  Claudeの「詳細設定」に、次の認証情報をコピーしてください。シークレットはページを再読み込みすると再表示できません。
                </p>
                <div className="form-group">
                  <label className="form-label" htmlFor="claudeMcpServerUrl">MCPサーバーURL</label>
                  <input id="claudeMcpServerUrl" className="custom-form-control" value={claudeOAuthClientCredentials.mcp_server_url} readOnly />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="claudeOAuthClientId">OAuthクライアントID</label>
                  <input id="claudeOAuthClientId" className="custom-form-control" value={claudeOAuthClientCredentials.client_id} readOnly />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="claudeOAuthClientSecret">OAuthクライアントシークレット</label>
                  <input id="claudeOAuthClientSecret" className="custom-form-control" value={claudeOAuthClientCredentials.client_secret} readOnly autoComplete="off" />
                </div>
              </div>
            ) : null}
          </div>

          {/* 危険ゾーン: アカウント削除 — 確認テキスト入力でボタンを解除し、最終確認ダイアログを挟む / Danger zone: account deletion — text confirmation unlocks the button, then a dialog confirms */}
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
                className="danger-button"
                disabled={
                  accountDeleting ||
                  accountDeleteConfirmation.trim() !== ACCOUNT_DELETE_CONFIRMATION_TEXT
                }
                onClick={() => {
                  void onDeleteAccount();
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
  );
}
