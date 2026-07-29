import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageSettingsSection } from "../components/settings/settings_sections";
import { LocaleProvider, translate, useTranslation } from "../contexts/locale_context";
import { LOCALE_COOKIE_NAME, type Locale } from "../lib/i18n/config";
import { LOCALE_TRANSITION_ATTRIBUTE, LOCALE_TRANSITION_SESSION_KEY } from "../lib/i18n/locale_transition";

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
  // 演出用の属性は <html> に付くため testing-library の cleanup では消えない
  // The transition attribute lives on <html>, which testing-library's cleanup does not reset
  afterEach(() => {
    document.documentElement.removeAttribute(LOCALE_TRANSITION_ATTRIBUTE);
  });

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

  // bfcache復元をシミュレートする（ブラウザバックで元ページが凍結解除された状態）
  // Simulate a bfcache restore (the previous page unfrozen by a browser back navigation)
  function dispatchBfcacheRestore() {
    act(() => {
      const event = new Event("pageshow") as PageTransitionEvent;
      Object.defineProperty(event, "persisted", { value: true });
      window.dispatchEvent(event);
    });
  }

  // 設定画面への遷移はプレーンリンクによるフルページ遷移のため、ブラウザバック時に
  // bfcacheから復元される元ページは、SSR済みHTML・バニラJSのDOM・取得済みAPIデータが
  // すべて旧言語のまま。Reactのstateだけを差し替えると言語が混在して表示が崩れるため、
  // ページ全体を再読み込みして一貫した状態に戻すことを検証する。
  // Navigating to Settings is a full-page load, so the previous page restored from
  // bfcache still has its SSR'd HTML, vanilla-rendered DOM, and fetched API data in the
  // old language. Swapping only the React state yields a mixed-language, broken layout,
  // so verify the provider reloads the page to restore a consistent state.
  it("reloads a bfcache-restored page when the locale changed in another document", () => {
    vi.useFakeTimers();
    const reload = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, reload } as Location);
    render(<LocaleProvider initialLocale="ja"><LocaleHarness /></LocaleProvider>);

    // 別ページ（設定画面）でロケールがenへ変更され、cookieへ永続化された状態を模す
    // Simulate another page (Settings) having changed the locale and persisted it to the cookie
    document.cookie = `${LOCALE_COOKIE_NAME}=en; Path=/`;
    dispatchBfcacheRestore();

    // 白い画面の差し込みを目立たせないよう、先にフェードアウトしてから再読み込みする
    // Fade out first so the blank frame of the reload is far less noticeable
    expect(document.documentElement).toHaveAttribute(LOCALE_TRANSITION_ATTRIBUTE, "leave");
    expect(reload).not.toHaveBeenCalled();

    act(() => { vi.runAllTimers(); });

    expect(reload).toHaveBeenCalledTimes(1);
    // 次の文書でフェードインから始めるためのフラグを残す
    // Leave the flag that makes the next document start from a fade-in
    expect(window.sessionStorage.getItem(LOCALE_TRANSITION_SESSION_KEY)).toBe("1");
    vi.useRealTimers();
  });

  // 言語が変わっていない通常のブラウザバックまで再読み込みすると、入力中の内容が
  // 失われ体験を損なうため、差分があるときだけ再読み込みすることを検証する。
  // Reloading on every back navigation would discard in-progress input, so verify the
  // reload only happens when the persisted locale actually differs.
  it("leaves a bfcache-restored page untouched when the locale did not change", () => {
    const reload = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, reload } as Location);
    document.cookie = `${LOCALE_COOKIE_NAME}=ja; Path=/`;
    render(<LocaleProvider initialLocale="ja"><LocaleHarness /></LocaleProvider>);

    dispatchBfcacheRestore();

    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByTestId("locale")).toHaveTextContent("ja");
  });

  // 同一文書内で切り替えた直後の復元では、既にその言語で描画済みなので再読み込みしない。
  // A restore right after an in-document switch must not reload — the page already renders
  // in that language.
  it("does not reload after an in-document locale switch", () => {
    const reload = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, reload } as Location);
    render(<LocaleProvider initialLocale="ja"><LocaleHarness /></LocaleProvider>);

    fireEvent.click(screen.getByRole("button", { name: "switch" }));
    expect(screen.getByTestId("locale")).toHaveTextContent("en");

    dispatchBfcacheRestore();

    expect(reload).not.toHaveBeenCalled();
  });

  // 文言が一斉に入れ替わるだけでは「ちらついた」ようにしか見えないため、切り替えが
  // 意図した変化だと伝わる短いフェードを添える。
  // Swapping every label at once merely looks like a glitch, so a short fade marks the
  // switch as an intentional change.
  it("plays a settle transition when the language actually changes", () => {
    render(<LocaleProvider initialLocale="ja"><LocaleHarness /></LocaleProvider>);
    expect(document.documentElement).not.toHaveAttribute(LOCALE_TRANSITION_ATTRIBUTE);

    fireEvent.click(screen.getByRole("button", { name: "switch" }));

    expect(document.documentElement).toHaveAttribute(LOCALE_TRANSITION_ATTRIBUTE, "settle");
  });

  // 同じ言語での setLocale（設定画面は初期化時に呼ぶ）まで演出すると、用のない
  // ちらつきになるため再生しない。
  // setLocale with the already-active language (the settings page does this while
  // initializing) must not animate, or the screen flickers for no reason.
  it("does not play a transition when the language is unchanged", () => {
    render(<LocaleProvider initialLocale="en"><LocaleHarness /></LocaleProvider>);

    fireEvent.click(screen.getByRole("button", { name: "switch" }));

    expect(document.documentElement).not.toHaveAttribute(LOCALE_TRANSITION_ATTRIBUTE);
  });

  // 連続で切り替えても取りこぼさないこと。演出のために状態更新を遅延させると、
  // 続けて押したときに前の更新が捨てられ「切り替わらない」不具合になる。
  // Rapid switches must never be dropped: deferring the state update for the sake of the
  // animation loses the earlier update and reads as "the switch did nothing".
  it("applies every switch immediately when toggled repeatedly", () => {
    function ToggleHarness() {
      const { locale, setLocale } = useTranslation();
      return (
        <>
          <output data-testid="locale">{locale}</output>
          <button type="button" onClick={() => setLocale(locale === "ja" ? "en" : "ja")}>toggle</button>
        </>
      );
    }

    render(<LocaleProvider initialLocale="ja"><ToggleHarness /></LocaleProvider>);
    const toggle = screen.getByRole("button", { name: "toggle" });

    fireEvent.click(toggle);
    expect(screen.getByTestId("locale")).toHaveTextContent("en");
    fireEvent.click(toggle);
    expect(screen.getByTestId("locale")).toHaveTextContent("ja");
    fireEvent.click(toggle);
    expect(screen.getByTestId("locale")).toHaveTextContent("en");
    expect(window.localStorage.getItem("chatcore.locale")).toBe("en");
  });
});
