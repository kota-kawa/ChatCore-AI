import { SETTINGS_NAV_ITEMS } from "../../scripts/user/settings/constants";
import type { SettingsSection } from "../../scripts/user/settings/page_types";
import { useTranslation } from "../../contexts/locale_context";

// 設定画面のナビゲーション。デスクトップでは左の縦リスト、768px 以下では上部の折り返すタブ列になる。
// 「戻る」は見出しの左に置き、ページ上に浮かせない。
// Settings navigation: a vertical rail on desktop, a wrapping tab row at the top below 768px.
// The back button sits next to the heading instead of floating over the page.
export function SettingsSidebar({
  activeSection,
  onSectionSelect,
  onBack
}: {
  activeSection: SettingsSection;
  onSectionSelect: (section: SettingsSection) => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const labels: Record<SettingsSection, string> = {
    profile: t("settings.profile"), appearance: t("settings.appearance"), language: t("settings.language"),
    prompts: t("settings.prompts"), "liked-prompts": t("settings.likedPrompts"),
    notifications: t("settings.notifications"), security: t("settings.security")
  };
  return (
    <nav className="settings-sidebar" aria-label={t("settings.heading")}>
      <div className="sidebar-header">
        <button
          type="button"
          className="settings-back-btn"
          onClick={onBack}
          data-tooltip={t("common.back")}
          aria-label={t("common.back")}
          data-tooltip-placement="bottom"
        >
          <i className="bi bi-arrow-left" aria-hidden="true"></i>
        </button>
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
              <i className={item.iconClass} aria-hidden="true"></i> {labels[item.section]}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
