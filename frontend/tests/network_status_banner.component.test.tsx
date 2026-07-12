import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NetworkStatusBanner } from "../components/NetworkStatusBanner";

function setOnline(value: boolean) {
  Object.defineProperty(navigator, "onLine", { configurable: true, value });
}

describe("NetworkStatusBanner", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setOnline(true);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("announces an offline state and a temporary recovery state", () => {
    setOnline(false);
    render(<NetworkStatusBanner />);

    const status = screen.getByRole("status", { hidden: true });
    expect(status).toHaveTextContent("オフラインです。接続を確認しています…");
    expect(status).toHaveAttribute("data-variant", "offline");
    expect(status).toHaveClass("is-visible");

    setOnline(true);
    act(() => window.dispatchEvent(new Event("online")));
    expect(status).toHaveTextContent("オンラインに復帰しました");
    expect(status).toHaveAttribute("data-variant", "recovered");

    act(() => vi.advanceTimersByTime(2400));
    expect(status).toHaveAttribute("aria-hidden", "true");
    expect(status).not.toHaveClass("is-visible");
  });

  it("announces a slow connection reported by the Network Information API", () => {
    Object.defineProperty(navigator, "connection", {
      configurable: true,
      value: { effectiveType: "2g", saveData: false },
    });
    render(<NetworkStatusBanner />);

    const status = screen.getByRole("status", { hidden: true });
    expect(status).toHaveTextContent("通信が遅くなっています");
    expect(status).toHaveAttribute("data-variant", "slow");
  });
});
