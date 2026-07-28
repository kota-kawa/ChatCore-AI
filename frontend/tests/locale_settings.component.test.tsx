import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { LanguageSettingsSection } from "../components/settings/settings_sections";
import { LocaleProvider, useTranslation } from "../contexts/locale_context";
import type { Locale } from "../lib/i18n/config";

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
});
