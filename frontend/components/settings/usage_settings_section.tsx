import { useCallback, useEffect, useState } from "react";

import { InlineLoading } from "../ui/inline_loading";
import { SettingsSectionHeader } from "./settings_sections";
import { useTranslation } from "../../contexts/locale_context";
import { loadUsageLimits } from "../../scripts/user/settings/api";
import type { UsageLimits } from "../../scripts/user/settings/types";
import { formatUsageExpiryDate, formatUsageResetTime, usagePercent } from "../../scripts/user/settings/usage";

type UsageWindow = { used_ratio: number };

// 1つの枠（今日・今週・デモ）の使用率をバーで示す。金額は出さず割合だけを見せる。
// footnote は枠ごとの補足（リセット時刻、デモの期限）。
// One allowance (today / this week / demo) shown as a bar: only the share of the limit, never amounts.
// The footnote is the per-allowance note (reset time, demo expiry).
function UsageMeter({ id, label, window, footnote }: { id: string; label: string; window: UsageWindow | null; footnote: string }) {
  const { t } = useTranslation();
  const labelId = `${id}-label`;

  if (!window) {
    return (
      <div className="usage-meter">
        <div className="usage-meter__head">
          <span className="usage-meter__label">{label}</span>
          <span className="usage-meter__value">{t("settings.usageUnlimited")}</span>
        </div>
      </div>
    );
  }

  const percent = usagePercent(window.used_ratio);
  const reached = percent >= 100;
  return (
    <div className="usage-meter">
      <div className="usage-meter__head">
        <span className="usage-meter__label" id={labelId}>{label}</span>
        <span className="usage-meter__value">{reached ? t("settings.usageLimitReached") : `${percent}%`}</span>
      </div>
      <div
        className="usage-meter__track"
        role="progressbar"
        aria-labelledby={labelId}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={`${percent}%`}
      >
        <div className="usage-meter__fill" style={{ width: `${percent}%` }} />
      </div>
      <p className="usage-meter__reset">{footnote}</p>
    </div>
  );
}

// 設定画面の「利用状況」。セクションを開くたびに最新の値を読み直す。
// The settings "Usage" section; it reloads the latest figures every time it is opened.
export function UsageSettingsSection({ isActive }: { isActive: boolean }) {
  const { t, locale } = useTranslation();
  const [usage, setUsage] = useState<UsageLimits | null>(null);
  const [failed, setFailed] = useState(false);

  const reload = useCallback(async () => {
    setFailed(false);
    try {
      setUsage(await loadUsageLimits());
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    if (isActive) void reload();
  }, [isActive, reload]);

  const resetNote = (window: { resets_at: string } | null) =>
    window ? t("settings.usageResetsAt", { time: formatUsageResetTime(window.resets_at, locale) }) : "";

  let body;
  if (failed) {
    body = (
      <div className="usage-settings__error" role="alert">
        <p>{t("settings.usageLoadFailed")}</p>
        <button type="button" className="ghost-button" onClick={() => void reload()}>
          {t("common.retry")}
        </button>
      </div>
    );
  } else if (!usage) {
    body = <InlineLoading label={t("common.loading")} />;
  } else {
    body = (
      <>
        {usage.monthly_budget_exhausted ? (
          <p className="usage-settings__notice" role="status">
            {t("settings.usageMonthlyPaused", { time: formatUsageResetTime(usage.monthly_resets_at, locale) })}
          </p>
        ) : null}
        {usage.demo ? (
          <UsageMeter
            id="usage-demo"
            label={t("settings.usageDemo")}
            window={usage.demo}
            footnote={t("settings.usageDemoUntil", { date: formatUsageExpiryDate(usage.demo.expires_at, locale) })}
          />
        ) : null}
        <UsageMeter
          id="usage-daily"
          label={t("settings.usageDaily")}
          window={usage.daily}
          footnote={resetNote(usage.daily)}
        />
        <UsageMeter
          id="usage-weekly"
          label={t("settings.usageWeekly")}
          window={usage.weekly}
          footnote={resetNote(usage.weekly)}
        />
      </>
    );
  }

  return (
    <section id="usage-section" className={`settings-section${isActive ? " active" : ""}`}>
      <SettingsSectionHeader title={t("settings.usage")} lead={t("settings.usageLead")} />
      <div className="settings-card usage-settings">{body}</div>
    </section>
  );
}
