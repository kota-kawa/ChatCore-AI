import { SETTINGS_NAV_ITEMS } from "../../scripts/user/settings/constants";
import type { SettingsSection } from "../../scripts/user/settings/page_types";
import { useTranslation } from "../../contexts/locale_context";

// 設定画面の左側に表示するナビゲーションサイドバー
// Navigation sidebar displayed on the left side of the settings page
export function SettingsSidebar({
  activeSection,
  onSectionSelect
}: {
  activeSection: SettingsSection;
  onSectionSelect: (section: SettingsSection) => void;
}) {
  const { t } = useTranslation();
  const labels: Record<SettingsSection, string> = {
    profile: t("settings.profile"), appearance: t("settings.appearance"), language: t("settings.language"),
    prompts: t("settings.prompts"), "liked-prompts": t("settings.likedPrompts"),
    notifications: t("settings.notifications"), security: t("settings.security")
  };
  return (
    <nav className="settings-sidebar">
      <div className="sidebar-header">
        <h3>{t("settings.heading")}</h3>
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
              <i className={item.iconClass}></i> {labels[item.section]}
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
