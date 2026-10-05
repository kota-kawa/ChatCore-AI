import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useMemoPageFlash } from "../hooks/memo_page/use_memo_page_flash";

// ?saved=1 の処理は router を使うので、クエリの無い固定の router を渡す
// The ?saved=1 handling reads the router, so provide a fixed one without the query
const routerMock = vi.hoisted(() => ({ isReady: true, pathname: "/memo", query: {}, replace: vi.fn() }));
vi.mock("next/router", () => ({ useRouter: () => routerMock }));

describe("useMemoPageFlash", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("hides a plain notice after 4 seconds", () => {
    const { result } = renderHook(() => useMemoPageFlash());
    act(() => result.current.showFlash("success", "保存しました"));
    expect(result.current.flashState).toEqual({ type: "success", text: "保存しました" });

    act(() => vi.advanceTimersByTime(3999));
    expect(result.current.flashState).not.toBeNull();
    act(() => vi.advanceTimersByTime(1));
    expect(result.current.flashState).toBeNull();
  });

  it("keeps a notice with an undo for 6 seconds", () => {
    const onAction = vi.fn();
    const { result } = renderHook(() => useMemoPageFlash());
    act(() => result.current.showFlash("success", "移動しました", { label: "元に戻す", onAction }));

    act(() => vi.advanceTimersByTime(5999));
    expect(result.current.flashState?.action?.label).toBe("元に戻す");
    act(() => vi.advanceTimersByTime(1));
    expect(result.current.flashState).toBeNull();
  });

  it("runs the undo once and hides the notice, even when it is pressed twice", () => {
    const onAction = vi.fn();
    const { result } = renderHook(() => useMemoPageFlash());
    act(() => result.current.showFlash("success", "移動しました", { label: "元に戻す", onAction }));

    act(() => {
      result.current.runFlashAction();
      result.current.runFlashAction();
    });

    expect(onAction).toHaveBeenCalledTimes(1);
    expect(result.current.flashState).toBeNull();
  });

  it("drops the previous undo when a newer notice replaces it", () => {
    const first = vi.fn();
    const { result } = renderHook(() => useMemoPageFlash());
    act(() => result.current.showFlash("success", "1 件目", { label: "元に戻す", onAction: first }));
    act(() => result.current.showFlash("error", "失敗しました"));

    act(() => result.current.runFlashAction());

    expect(first).not.toHaveBeenCalled();
    expect(result.current.flashState).toEqual({ type: "error", text: "失敗しました" });
  });

  it("does not let the first notice's timer hide a newer one", () => {
    const { result } = renderHook(() => useMemoPageFlash());
    act(() => result.current.showFlash("success", "1 件目"));
    act(() => vi.advanceTimersByTime(3000));
    act(() => result.current.showFlash("success", "2 件目"));
    act(() => vi.advanceTimersByTime(3000));
    expect(result.current.flashState?.text).toBe("2 件目");
  });

  it("can start another undoable action from inside an undo", () => {
    const second = vi.fn();
    const { result } = renderHook(() => useMemoPageFlash());
    act(() =>
      result.current.showFlash("success", "移動しました", {
        label: "元に戻す",
        onAction: () => result.current.showFlash("success", "戻しました", { label: "やり直す", onAction: second }),
      }),
    );

    act(() => result.current.runFlashAction());
    expect(result.current.flashState?.text).toBe("戻しました");

    act(() => result.current.runFlashAction());
    expect(second).toHaveBeenCalledTimes(1);
  });
});
