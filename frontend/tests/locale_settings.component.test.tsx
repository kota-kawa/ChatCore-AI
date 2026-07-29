import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { LanguageSettingsSection } from "../components/settings/settings_sections";
import { LocaleProvider, translate, useTranslation } from "../contexts/locale_context";
import { LOCALE_COOKIE_NAME, type Locale } from "../lib/i18n/config";

function LocaleHarness() {
  const { locale, setLocale, t } = useTranslation();
  return (
    <>
      <output data-testid="locale">{locale}</output>
      <p>{t("settings.languageDescription")}</p>
      <button type="button" onClick={() => setLocale("en")}>switch</button>
    </>
  );
}

function SettingsHarness({ onSave = () => undefined }: { onSave?: (locale: Locale) => void }) {
  const [locale, setLocale] = useState<Locale>("ja");
  return (
    <LocaleProvider initialLocale={locale}>
      <LanguageSettingsSection
        isActive
        locale={locale}
        saving={false}
        onLocaleSelect={(nextLocale) => {
          setLocale(nextLocale);
          onSave(nextLocale);
        }}
      />
    </LocaleProvider>
  );
}

describe("locale switching", () => {
  it("updates the active catalogue and persists the selected locale", () => {
    render(<LocaleProvider initialLocale="ja"><LocaleHarness /></LocaleProvider>);

    fireEvent.click(screen.getByRole("button", { name: "switch" }));

    expect(screen.getByTestId("locale")).toHaveTextContent("en");
    expect(screen.getByText("Choose the language used for Chat Core menus, buttons, and guidance.")).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute("lang", "en");
    expect(window.localStorage.getItem("chatcore.locale")).toBe("en");
  });

  it("offers Japanese and English as accessible settings choices", () => {
    const onSave = vi.fn();
    render(<SettingsHarness onSave={onSave} />);

    const english = screen.getByRole("radio", { name: /English/ });
    expect(screen.getByRole("radio", { name: /日本語/ })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(english);

    expect(onSave).toHaveBeenCalledWith("en");
    expect(english).toHaveAttribute("aria-checked", "true");
  });

  // 選択状態のスタイルは CSS の .is-selected に依存するため、クラス名の付け替えを検知できるようにする
  // The selected styling hangs off the .is-selected CSS class, so guard against the class name drifting
  it("marks the selected language card with the styling hook the stylesheet expects", () => {
    render(<SettingsHarness />);

    const japanese = screen.getByRole("radio", { name: /日本語/ });
    const english = screen.getByRole("radio", { name: /English/ });
    expect(japanese).toHaveClass("language-option", "is-selected");
    expect(english).toHaveClass("language-option");
    expect(english).not.toHaveClass("is-selected");

    fireEvent.click(english);

    expect(english).toHaveClass("is-selected");
    expect(japanese).not.toHaveClass("is-selected");
  });

  // 切り替え直後に表示する確認メッセージは、await後に古いクロージャの`t`ではなく
  // 切り替え後のロケールで文言を取得する必要がある（設定保存トーストが旧言語のまま
  // 表示されていた不具合の回帰防止）。
  // The confirmation message shown right after switching must resolve copy for the new
  // locale, not a stale pre-switch `t` closure (regression guard for the settings save
  // toast staying in the old language).
  it("resolves a locale-explicit translation independent of any stale `t` closure", () => {
    expect(translate("ja", "settings.languageSaved")).toBe("表示言語を変更しました。");
    expect(translate("en", "settings.languageSaved")).toBe("Display language updated.");
  });

  // 設定画面への遷移はプレーンリンクによるフルページ遷移のため、ブラウザバック時に
  // bfcacheから元ページが復元されるとJSが再実行されず古い言語のままになっていた。
  // pageshow(persisted)で永続化済みの値へ再同期し、リロードなしで反映されることを検証する。
  // Navigating to Settings is a full-page load, so a bfcache-restored previous page kept
  // showing the old language until reload. Verify pageshow(persisted) resyncs from the
  // persisted value without requiring a reload.
  it("resyncs the locale from the persisted cookie when the page is restored from bfcache", () => {
    render(<LocaleProvider initialLocale="ja"><LocaleHarness /></LocaleProvider>);

    expect(screen.getByTestId("locale")).toHaveTextContent("ja");

    // 別ページ（設定画面）でロケールがenへ変更され、cookieへ永続化された状態を模す
    // Simulate another page (Settings) having changed the locale and persisted it to the cookie
    document.cookie = `${LOCALE_COOKIE_NAME}=en; Path=/`;

    act(() => {
      const event = new Event("pageshow") as PageTransitionEvent;
      Object.defineProperty(event, "persisted", { value: true });
      window.dispatchEvent(event);
    });

    expect(screen.getByTestId("locale")).toHaveTextContent("en");
  });
});
