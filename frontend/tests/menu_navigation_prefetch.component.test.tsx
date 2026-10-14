import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { NextRouter } from "next/router";

import { useMenuNavigationPrefetch } from "../hooks/use_menu_navigation_prefetch";

const styles = vi.hoisted(() => ({ preinit: vi.fn() }));
vi.mock("react-dom", async (importOriginal) => ({
  ...await importOriginal<typeof import("react-dom")>(),
  preinit: styles.preinit,
}));

const paths = ["/", "/memo", "/prompt_share"];
type PrefetchRouter = Pick<NextRouter, "pathname" | "locale" | "prefetch">;

function Harness({ router }: { router: PrefetchRouter }) {
  useMenuNavigationPrefetch(router, paths);
  return <input aria-label="Page input" />;
}

function makeMenu(tag: "action-menu" | "chat-action-menu") {
  const menu = document.createElement(tag);
  const shadow = menu.attachShadow({ mode: "open" });
  const button = document.createElement("button");
  shadow.append(button);
  document.body.append(menu);
  return { menu, button };
}

describe("menu route preparation", () => {
  afterEach(() => {
    styles.preinit.mockClear();
    vi.useRealTimers();
    document.querySelectorAll("action-menu, chat-action-menu").forEach((menu) => menu.remove());
    document.querySelectorAll("link[data-menu-route-style]").forEach((link) => link.remove());
  });

  it("keeps other routes out of initial loading and ordinary page input", () => {
    const prefetch = vi.fn().mockResolvedValue(undefined);
    const { getByRole } = render(<Harness router={{ pathname: "/settings", locale: "ja", prefetch }} />);
    fireEvent.pointerOver(getByRole("textbox"));
    fireEvent.pointerDown(getByRole("textbox"));
    fireEvent.focusIn(getByRole("textbox"));
    expect(prefetch).not.toHaveBeenCalled();
    expect(styles.preinit).not.toHaveBeenCalled();
  });

  it.each(["action-menu", "chat-action-menu"] as const)("prepares other routes once on %s touch intent", (tag) => {
    const prefetch = vi.fn().mockResolvedValue(undefined);
    render(<Harness router={{ pathname: "/memo", locale: "ja", prefetch }} />);
    const { button } = makeMenu(tag);
    act(() => {
      button.dispatchEvent(new Event("pointerdown", { bubbles: true, composed: true }));
      button.dispatchEvent(new Event("pointerover", { bubbles: true, composed: true }));
    });
    expect(prefetch.mock.calls.map(([path]) => path)).toEqual(["/", "/prompt_share"]);
    expect(styles.preinit).not.toHaveBeenCalled();
  });

  it("supports keyboard focus and removes listeners on unmount", () => {
    const prefetch = vi.fn().mockResolvedValue(undefined);
    const { unmount } = render(<Harness router={{ pathname: "/settings", locale: "ja", prefetch }} />);
    const { button } = makeMenu("action-menu");
    act(() => button.dispatchEvent(new Event("focusin", { bubbles: true, composed: true })));
    expect(prefetch).toHaveBeenCalledTimes(3);
    expect(styles.preinit).toHaveBeenCalledWith("/memo/static/css/memo_form.css", { as: "style", precedence: "memo" });
    expect(document.querySelector('link[rel="preload"][as="style"][href="/memo/static/css/memo_form.css"]')).not.toBeNull();
    prefetch.mockClear();
    unmount();
    button.dispatchEvent(new Event("pointerdown", { bubbles: true, composed: true }));
    expect(prefetch).not.toHaveBeenCalled();
    expect(styles.preinit).toHaveBeenCalledTimes(1);
  });

  it("allows a failed preparation to retry on the next menu interaction", async () => {
    const prefetch = vi.fn().mockRejectedValueOnce(new Error("Offline")).mockResolvedValue(undefined);
    render(<Harness router={{ pathname: "/memo", locale: "ja", prefetch }} />);
    const { button } = makeMenu("action-menu");
    await act(async () => button.dispatchEvent(new Event("pointerdown", { bubbles: true, composed: true })));
    act(() => button.dispatchEvent(new Event("pointerdown", { bubbles: true, composed: true })));
    expect(prefetch.mock.calls.map(([path]) => path)).toEqual(["/", "/prompt_share", "/"]);
  });

  it("warms one route at a time after a quiet period and defers remaining work during input", async () => {
    vi.useFakeTimers();
    const prefetch = vi.fn().mockResolvedValue(undefined);
    makeMenu("action-menu");
    const { getByRole } = render(<Harness router={{ pathname: "/settings", locale: "ja", prefetch }} />);
    await act(() => vi.advanceTimersByTimeAsync(800));
    expect(prefetch.mock.calls.map(([path]) => path)).toEqual(["/"]);
    await act(() => vi.advanceTimersByTimeAsync(400));
    fireEvent.input(getByRole("textbox"));
    await act(() => vi.advanceTimersByTimeAsync(799));
    expect(prefetch).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(prefetch.mock.calls.map(([path]) => path)).toEqual(["/", "/memo"]);
    expect(styles.preinit).not.toHaveBeenCalled();
  });

  it("does not repeatedly retry an offline route in the background", async () => {
    vi.useFakeTimers();
    const prefetch = vi.fn().mockRejectedValue(new Error("Offline"));
    makeMenu("action-menu");
    render(<Harness router={{ pathname: "/memo", locale: "ja", prefetch }} />);
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(prefetch.mock.calls.map(([path]) => path)).toEqual(["/", "/prompt_share"]);
  });
});
