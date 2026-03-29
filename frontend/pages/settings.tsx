import Head from "next/head";
import Script from "next/script";
import { useEffect, useState } from "react";

type SettingsNavItem = {
  section: string;
  iconClass: string;
  label: string;
  isActive?: boolean;
};

const SETTINGS_NAV_ITEMS: SettingsNavItem[] = [
  { section: "profile", iconClass: "bi bi-person-circle", label: "プロフィール設定", isActive: true },
  { section: "prompts", iconClass: "bi bi-shield-lock", label: "プロンプト管理" },
  { section: "prompt-list", iconClass: "bi bi-list-stars", label: "プロンプトリスト" },
  { section: "notifications", iconClass: "bi bi-bell", label: "通知設定" },
  { section: "security", iconClass: "bi bi-key", label: "セキュリティ" }
];

function SettingsSidebar() {
  return (
    <nav className="settings-sidebar">
      <div className="sidebar-header">
        <h3>設定</h3>
      </div>

      <ul className="nav-menu">
        {SETTINGS_NAV_ITEMS.map((item) => (
          <li key={item.section}>
            <a
              href="#"
              className={`nav-link${item.isActive ? " active" : ""}`}
              data-section={item.section}
            >
              <i className={item.iconClass}></i> {item.label}
            </a>
          </li>
        ))}
      </ul>

      <div className="sidebar-footer">
        <p>&copy; 2025 YourApp</p>
      </div>
    </nav>
  );
}

function ProfileSection() {
  return (
    <div id="profile-section" className="settings-section active">
      <div className="settings-card">
        <h2>ユーザープロフィール設定</h2>
        <form id="userSettingsForm">
          <div className="form-group avatar-group">
            <label className="form-label" htmlFor="avatarInput">
              プロフィール画像
            </label>
            <div className="avatar-preview-wrapper">
              <img
                id="avatarPreview"
                src="/static/user-icon.png"
                alt="Avatar Preview"
                className="avatar-preview"
              />
              <button
                type="button"
                className="change-avatar-btn"
                id="changeAvatarBtn"
                data-tooltip="プロフィール画像を選択"
                data-tooltip-placement="bottom"
              >
                <i className="bi bi-pencil-fill"></i>
              </button>
            </div>
            <input type="file" id="avatarInput" accept="image/*" hidden />
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
            />
          </div>

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
            />
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
            ></textarea>
          </div>

          <div className="button-group">
            <button type="button" className="secondary-button" id="cancelBtn">
              キャンセル
            </button>
            <button type="submit" className="primary-button">
              変更を保存
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function PromptManageSection() {
  return (
    <div id="prompts-section" className="settings-section">
      <div className="settings-card">
        <h2>プロンプト管理</h2>
        <div className="header-bar">
          <h3 className="section-title">My Prompts</h3>
        </div>
        <div id="promptList" className="prompt-grid"></div>
      </div>
    </div>
  );
}

function PromptListSection() {
  return (
    <div id="prompt-list-section" className="settings-section">
      <div className="settings-card">
        <h2>プロンプトリスト</h2>
        <div className="header-bar">
          <h3 className="section-title">Prompt List</h3>
        </div>
        <div id="promptListEntries" className="prompt-grid"></div>
      </div>
    </div>
  );
}

function NotificationsSection() {
  return (
    <div id="notifications-section" className="settings-section">
      <div className="settings-card">
        <h2>通知設定</h2>
        <p>通知設定機能は準備中です。</p>
      </div>
    </div>
  );
}

function SecuritySection() {
  return (
    <div id="security-section" className="settings-section">
      <div className="settings-card">
        <h2>セキュリティ</h2>

        <div className="security-stack">
          <div className="security-panel">
            <h3>Passkeys</h3>
            <p id="passkeySupportStatus">このブラウザの対応状況を確認しています。</p>
            <div className="button-group">
              <button type="button" className="primary-button" id="registerPasskeyBtn">
                この端末にPasskeyを追加
              </button>
              <button type="button" className="secondary-button" id="refreshPasskeysBtn">
                一覧を更新
              </button>
            </div>
          </div>

          <div className="security-panel">
            <h3>登録済みPasskeys</h3>
            <div id="passkeyList" className="passkey-list">
              <p className="passkey-empty">まだPasskeyは登録されていません。</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function EditPromptModal() {
  return (
    <div id="editModal" className="modal" tabIndex={-1}>
      <div className="modal-dialog modal-dialog-centered modal-dialog-scrollable">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">
              <i className="bi bi-pencil-square me-2"></i>プロンプト編集
            </h5>
            <button type="button" className="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>

          <div className="modal-body">
            <form id="editForm" className="modal-form">
              <input type="hidden" id="editPromptId" />

              <div className="form-group">
                <label htmlFor="editTitle" className="form-label">
                  タイトル
                </label>
                <input type="text" className="form-control input-field" id="editTitle" required />
              </div>

              <div className="form-group">
                <label htmlFor="editCategory" className="form-label">
                  カテゴリ
                </label>
                <input type="text" className="form-control input-field" id="editCategory" required />
              </div>

              <div className="form-group">
                <label htmlFor="editContent" className="form-label">
                  内容
                </label>
                <textarea className="form-control input-field" id="editContent" rows={5} required></textarea>
              </div>

              <div className="form-group">
                <label htmlFor="editInputExamples" className="form-label">
                  入力例
                </label>
                <textarea className="form-control input-field" id="editInputExamples" rows={3}></textarea>
              </div>

              <div className="form-group">
                <label htmlFor="editOutputExamples" className="form-label">
                  出力例
                </label>
                <textarea className="form-control input-field" id="editOutputExamples" rows={3}></textarea>
              </div>

              <div className="form-actions">
                <button type="submit" className="btn btn-primary w-100">
                  <i className="bi bi-save me-2"></i>更新する
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

function SettingsMainContent() {
  return (
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

      <ProfileSection />
      <PromptManageSection />
      <PromptListSection />
      <NotificationsSection />
      <SecuritySection />
    </main>
  );
}

function SettingsPageContent() {
  return (
    <>
      <div className="user-settings-layout">
        <SettingsSidebar />
        <SettingsMainContent />
      </div>
      <EditPromptModal />
    </>
  );
}

export default function UserSettingsPage() {
  const [bootstrapReady, setBootstrapReady] = useState(false);

  useEffect(() => {
    document.body.classList.add("settings-page");
    return () => {
      document.body.classList.remove("settings-page");
    };
  }, []);

  useEffect(() => {
    if (bootstrapReady) {
      import("../scripts/entries/settings");
    }
  }, [bootstrapReady]);

  return (
    <>
      <Head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>ユーザー設定</title>
        <link rel="icon" type="image/webp" href="/static/favicon.webp" />
        <link rel="icon" type="image/png" href="/static/favicon.png" />
        <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png" />
        <link
          href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&display=swap"
          rel="stylesheet"
        />
        <link
          href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
          rel="stylesheet"
        />
        <link
          href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css"
          rel="stylesheet"
        />
        <style>{`
          .user-settings-page {
            min-height: 100vh;
            background: #f4f7f6;
          }
          .user-settings-layout {
            display: flex;
            min-height: 100vh;
          }
          .settings-sidebar {
            width: 260px;
            position: fixed;
            top: 0;
            left: 0;
            bottom: 0;
          }
          .settings-content {
            flex: 1;
            margin-left: 260px;
            padding: 2rem;
          }
          .settings-section {
            display: none;
          }
          .settings-section.active {
            display: block;
          }
          .security-stack {
            display: grid;
            gap: 1rem;
          }
          .security-panel {
            padding: 1rem 1.1rem;
            border: 1px solid rgba(0, 0, 0, 0.08);
            border-radius: 16px;
            background: #fff;
          }
          .passkey-list {
            display: grid;
            gap: 0.75rem;
          }
          .passkey-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 1rem;
            padding: 0.9rem 1rem;
            border-radius: 14px;
            background: #f7faf8;
          }
          .passkey-meta {
            color: #5f6b66;
            font-size: 0.92rem;
            line-height: 1.5;
          }
          .passkey-empty {
            margin: 0;
            color: #5f6b66;
          }
          @media (max-width: 768px) {
            .user-settings-layout {
              flex-direction: column;
            }
            .settings-sidebar {
              width: 100%;
              position: static;
            }
            .settings-content {
              margin-left: 0;
              padding: 1.5rem;
            }
          }
        `}</style>
        <link rel="stylesheet" href="/static/css/pages/user_settings/index.bundle.css" />
      </Head>

      <div className="user-settings-page">
        <SettingsPageContent />
      </div>

      <Script
        src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"
        strategy="afterInteractive"
        onLoad={() => setBootstrapReady(true)}
      />
    </>
  );
}
