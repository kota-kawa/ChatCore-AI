// 記憶の画面を /memo?view=context で直接開けることを検証する（チャットの「記憶しました」通知のリンク先）。
// Tests that the memory view opens directly from /memo?view=context (the link target of the chat's "remembered" notice).

import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useMemoPageLayout } from "../hooks/memo_page/use_memo_page_layout";

const { routerState } = vi.hoisted(() => ({ routerState: { isReady: true, query: {} as Record<string, string | undefined> } }));

vi.mock("next/router", () => ({ useRouter: () => routerState }));

describe("useMemoPageLayout", () => {
  it("starts on the memo list by default", () => {
    routerState.isReady = true;
    routerState.query = {};
    const { result } = renderHook(() => useMemoPageLayout());
    expect(result.current.activeView).toBe("memos");
  });

  it("opens the memory view when the route asks for view=context", () => {
    routerState.isReady = true;
    routerState.query = { view: "context" };
    const { result } = renderHook(() => useMemoPageLayout());
    expect(result.current.activeView).toBe("context");
  });

  it("waits for the router before switching and ignores other view values", () => {
    routerState.isReady = false;
    routerState.query = { view: "context" };
    const { result, rerender } = renderHook(() => useMemoPageLayout());
    expect(result.current.activeView).toBe("memos");

    routerState.isReady = true;
    routerState.query = { view: "other" };
    rerender();
    expect(result.current.activeView).toBe("memos");
  });
});
