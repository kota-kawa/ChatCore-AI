import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UsageSettingsSection } from "../components/settings/usage_settings_section";
import { LocaleProvider } from "../contexts/locale_context";
import { loadUsageLimits } from "../scripts/user/settings/api";

vi.mock("../scripts/user/settings/api", () => ({ loadUsageLimits: vi.fn() }));

const mockedLoad = vi.mocked(loadUsageLimits);

function renderSection(isActive = true) {
  return render(
    <LocaleProvider initialLocale="ja">
      <UsageSettingsSection isActive={isActive} />
    </LocaleProvider>
  );
}

describe("UsageSettingsSection", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows daily and weekly bars with their reset times", async () => {
    mockedLoad.mockResolvedValue({
      daily: { used_ratio: 0.42, resets_at: "2026-09-24T00:00:00+09:00" },
      weekly: { used_ratio: 1, resets_at: "2026-09-28T00:00:00+09:00" },
      monthly_budget_exhausted: false,
      monthly_resets_at: "2026-10-01T00:00:00+09:00"
    });
    renderSection();

    const bars = await screen.findAllByRole("progressbar");
    expect(bars.map((bar) => bar.getAttribute("aria-valuenow"))).toEqual(["42", "100"]);
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("上限に達しました")).toBeInTheDocument();
    expect(screen.getByText("9月24日(木) 0:00（日本時間）にリセット")).toBeInTheDocument();
    expect(screen.queryByText(/一時停止/)).not.toBeInTheDocument();
  });

  it("explains a paused service and a disabled limit", async () => {
    mockedLoad.mockResolvedValue({
      daily: null,
      weekly: { used_ratio: 0.1, resets_at: "2026-09-28T00:00:00+09:00" },
      monthly_budget_exhausted: true,
      monthly_resets_at: "2026-10-01T00:00:00+09:00"
    });
    renderSection();

    expect(await screen.findByText(/AI機能を一時停止しています/)).toBeInTheDocument();
    expect(screen.getByText("上限なし")).toBeInTheDocument();
    expect(screen.getAllByRole("progressbar")).toHaveLength(1);
  });

  it("offers a retry after a failed load", async () => {
    mockedLoad.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({
      daily: { used_ratio: 0, resets_at: "2026-09-24T00:00:00+09:00" },
      weekly: { used_ratio: 0, resets_at: "2026-09-28T00:00:00+09:00" },
      monthly_budget_exhausted: false,
      monthly_resets_at: "2026-10-01T00:00:00+09:00"
    });
    renderSection();

    fireEvent.click(await screen.findByRole("button", { name: "再試行" }));
    expect(await screen.findAllByRole("progressbar")).toHaveLength(2);
    expect(mockedLoad).toHaveBeenCalledTimes(2);
  });

  it("does not load while the section is closed", () => {
    renderSection(false);
    expect(mockedLoad).not.toHaveBeenCalled();
  });
});
