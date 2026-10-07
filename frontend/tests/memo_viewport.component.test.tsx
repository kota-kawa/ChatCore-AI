import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useMemoMobileLayout, useMemoViewport } from "../hooks/memo_page/use_memo_viewport";

type FakeVisualViewport = EventTarget & {
  height: number;
  offsetTop: number;
  scale: number;
};

type FakeMediaQuery = {
  matches: boolean;
  addEventListener?: (type: "change", listener: EventListenerOrEventListenerObject) => void;
  removeEventListener?: (type: "change", listener: EventListenerOrEventListenerObject) => void;
  dispatchEvent?: (event: Event) => boolean;
};

let innerHeightDescriptor: PropertyDescriptor | undefined;
let visualViewportDescriptor: PropertyDescriptor | undefined;
let matchMediaDescriptor: PropertyDescriptor | undefined;
let requestAnimationFrameDescriptor: PropertyDescriptor | undefined;
let cancelAnimationFrameDescriptor: PropertyDescriptor | undefined;
let visualViewport: FakeVisualViewport;
let frames: Map<number, FrameRequestCallback>;
let nextFrameId: number;

function setInnerHeight(value: number): void {
  Object.defineProperty(window, "innerHeight", { configurable: true, value, writable: true });
}

function setVisualViewport(values: Partial<FakeVisualViewport> = {}): FakeVisualViewport {
  visualViewport = Object.assign(new EventTarget(), {
    height: 844,
    offsetTop: 0,
    scale: 1,
    ...values,
  }) as FakeVisualViewport;
  Object.defineProperty(window, "visualViewport", { configurable: true, value: visualViewport });
  return visualViewport;
}

function cssValue(style: ReturnType<typeof useMemoViewport>, property: string): string | undefined {
  return style?.[property as keyof typeof style] as string | undefined;
}

function flushFrames(): void {
  act(() => {
    const pending = [...frames.values()];
    frames.clear();
    pending.forEach((callback) => callback(0));
  });
}

function dispatchViewportEvent(target: EventTarget, type: string): void {
  act(() => target.dispatchEvent(new Event(type)));
}

beforeEach(() => {
  innerHeightDescriptor = Object.getOwnPropertyDescriptor(window, "innerHeight");
  visualViewportDescriptor = Object.getOwnPropertyDescriptor(window, "visualViewport");
  matchMediaDescriptor = Object.getOwnPropertyDescriptor(window, "matchMedia");
  requestAnimationFrameDescriptor = Object.getOwnPropertyDescriptor(window, "requestAnimationFrame");
  cancelAnimationFrameDescriptor = Object.getOwnPropertyDescriptor(window, "cancelAnimationFrame");
  setInnerHeight(844);
  setVisualViewport();
  frames = new Map();
  nextFrameId = 1;
  Object.defineProperty(window, "requestAnimationFrame", {
    configurable: true,
    writable: true,
    value: (callback: FrameRequestCallback) => {
      const id = nextFrameId++;
      frames.set(id, callback);
      return id;
    },
  });
  Object.defineProperty(window, "cancelAnimationFrame", {
    configurable: true,
    writable: true,
    value: (id: number) => {
      frames.delete(id);
    },
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();

  if (innerHeightDescriptor) Object.defineProperty(window, "innerHeight", innerHeightDescriptor);
  if (visualViewportDescriptor) Object.defineProperty(window, "visualViewport", visualViewportDescriptor);
  else Reflect.deleteProperty(window, "visualViewport");
  if (matchMediaDescriptor) Object.defineProperty(window, "matchMedia", matchMediaDescriptor);
  else Reflect.deleteProperty(window, "matchMedia");
  if (requestAnimationFrameDescriptor) Object.defineProperty(window, "requestAnimationFrame", requestAnimationFrameDescriptor);
  else Reflect.deleteProperty(window, "requestAnimationFrame");
  if (cancelAnimationFrameDescriptor) Object.defineProperty(window, "cancelAnimationFrame", cancelAnimationFrameDescriptor);
  else Reflect.deleteProperty(window, "cancelAnimationFrame");
});

describe("useMemoViewport", () => {
  it("preserves the editing surface while the visual viewport shrinks and pans", () => {
    const input = document.createElement("textarea");
    document.body.append(input);
    input.focus();
    const { result, unmount } = renderHook(() => useMemoViewport(true, true));
    setVisualViewport({ height: 500, offsetTop: 60 });
    dispatchViewportEvent(window, "resize");
    flushFrames();
    expect(cssValue(result.current, "--memo-surface-height")).toBe("844px");
    expect(cssValue(result.current, "--memo-surface-inset")).toBe("344px");
    expect(cssValue(result.current, "--memo-viewport-height")).toBe("500px");
    expect(cssValue(result.current, "--memo-viewport-top")).toBe("60px");
    unmount();
    input.remove();
  });

  it("keeps the editing height when Android also shrinks the layout viewport", () => {
    const input = document.createElement("textarea");
    document.body.append(input);
    input.focus();
    const { result, unmount } = renderHook(() => useMemoViewport(true, true));
    setInnerHeight(500);
    setVisualViewport({ height: 500 });
    dispatchViewportEvent(window, "resize");
    flushFrames();
    expect(cssValue(result.current, "--memo-surface-height")).toBe("844px");
    expect(cssValue(result.current, "--memo-surface-inset")).toBe("344px");
    input.blur();
    dispatchViewportEvent(window, "resize");
    flushFrames();
    expect(cssValue(result.current, "--memo-surface-height")).toBe("844px");
    setInnerHeight(844);
    setVisualViewport();
    dispatchViewportEvent(window, "resize");
    flushFrames();
    expect(cssValue(result.current, "--memo-surface-height")).toBe("844px");
    expect(cssValue(result.current, "--memo-surface-inset")).toBe("0px");
    unmount();
    input.remove();
  });

  it("uses the iOS visual height and calculates the keyboard inset", () => {
    setVisualViewport({ height: 500 });
    const { result } = renderHook(() => useMemoViewport(true));

    expect(cssValue(result.current, "--memo-viewport-height")).toBe("500px");
    expect(cssValue(result.current, "--memo-viewport-top")).toBe("0px");
    expect(cssValue(result.current, "--memo-viewport-bottom")).toBe("344px");
  });

  it("tracks visual viewport panning in the top and bottom values", () => {
    setVisualViewport({ height: 600, offsetTop: 100 });
    const { result } = renderHook(() => useMemoViewport(true));

    expect(cssValue(result.current, "--memo-viewport-height")).toBe("600px");
    expect(cssValue(result.current, "--memo-viewport-top")).toBe("100px");
    expect(cssValue(result.current, "--memo-viewport-bottom")).toBe("144px");
  });

  it("calculates the keyboard inset when Android shrinks both viewports", () => {
    setInnerHeight(500);
    setVisualViewport({ height: 420 });
    const { result } = renderHook(() => useMemoViewport(true));

    expect(cssValue(result.current, "--memo-viewport-height")).toBe("420px");
    expect(cssValue(result.current, "--memo-viewport-bottom")).toBe("80px");
  });

  it("updates the bottom value when only the layout viewport height changes", () => {
    setVisualViewport({ height: 600 });
    const { result } = renderHook(() => useMemoViewport(true));
    expect(cssValue(result.current, "--memo-viewport-bottom")).toBe("244px");

    setInnerHeight(700);
    dispatchViewportEvent(window, "resize");
    flushFrames();

    expect(cssValue(result.current, "--memo-viewport-height")).toBe("600px");
    expect(cssValue(result.current, "--memo-viewport-bottom")).toBe("100px");
  });

  it("falls back to the layout viewport while pinch zoom is active", () => {
    setInnerHeight(800);
    setVisualViewport({ height: 500, offsetTop: 30, scale: 1.2 });
    const { result } = renderHook(() => useMemoViewport(true));

    expect(cssValue(result.current, "--memo-viewport-height")).toBe("800px");
    expect(cssValue(result.current, "--memo-viewport-top")).toBe("0px");
    expect(cssValue(result.current, "--memo-viewport-bottom")).toBe("0px");
  });

  it("falls back to innerHeight when visualViewport is unavailable", () => {
    Reflect.deleteProperty(window, "visualViewport");
    setInnerHeight(720);
    const { result } = renderHook(() => useMemoViewport(true));

    expect(cssValue(result.current, "--memo-viewport-height")).toBe("720px");
    expect(cssValue(result.current, "--memo-viewport-top")).toBe("0px");
    expect(cssValue(result.current, "--memo-viewport-bottom")).toBe("0px");
  });

  it("returns undefined when disabled and cancels scheduled work on cleanup", () => {
    const disabled = renderHook(() => useMemoViewport(false));
    expect(disabled.result.current).toBeUndefined();
    disabled.unmount();

    const { unmount } = renderHook(() => useMemoViewport(true));
    dispatchViewportEvent(visualViewport, "resize");
    expect(frames.size).toBe(1);
    unmount();
    expect(frames.size).toBe(0);

    dispatchViewportEvent(visualViewport, "resize");
    expect(frames.size).toBe(0);
  });

  it("re-measures after focusout settles", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { result } = renderHook(() => useMemoViewport(true));
    expect(cssValue(result.current, "--memo-viewport-bottom")).toBe("0px");

    setVisualViewport({ height: 600 });
    act(() => document.dispatchEvent(new Event("focusout")));
    act(() => vi.advanceTimersByTime(250));
    flushFrames();

    expect(cssValue(result.current, "--memo-viewport-bottom")).toBe("244px");
  });
});

describe("useMemoMobileLayout", () => {
  it("starts false for SSR and subscribes to the mobile media query", () => {
    const mediaQuery = Object.assign(new EventTarget(), { matches: false }) as FakeMediaQuery;
    const removeListener = vi.spyOn(mediaQuery, "removeEventListener");
    const matchMedia = vi.fn((query: string) => {
      expect(query).toBe("(max-width: 768px)");
      return mediaQuery as MediaQueryList;
    });
    Object.defineProperty(window, "matchMedia", { configurable: true, value: matchMedia });

    const { result, unmount } = renderHook(() => useMemoMobileLayout());
    expect(result.current).toBe(false);

    mediaQuery.matches = true;
    act(() => mediaQuery.dispatchEvent?.(new Event("change")));
    expect(result.current).toBe(true);
    expect(matchMedia).toHaveBeenCalledTimes(1);
    unmount();
    expect(removeListener).toHaveBeenCalledWith("change", expect.any(Function));
  });

  it("handles matchMedia implementations without event listener methods", () => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn(() => ({ matches: true })),
    });

    const { result, unmount } = renderHook(() => useMemoMobileLayout());
    expect(result.current).toBe(true);
    expect(() => unmount()).not.toThrow();
  });
});
