import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMemoPageList } from "../hooks/memo_page/use_memo_page_list";
import { loadMemoList } from "../lib/memo/api";
import { DEFAULT_LIMIT } from "../lib/memo/constants";
import type { MemoSummary } from "../lib/memo/types";

vi.mock("../lib/memo/api", () => ({
  loadMemoList: vi.fn(),
}));

const TOTAL_MEMOS = 130;
const allMemos: MemoSummary[] = Array.from({ length: TOTAL_MEMOS }, (_, index) => ({ id: index + 1 }));

// モックは再レンダーを跨いで同一インスタンスにする（毎回作り直すと呼び出し履歴が消える）
// The fetch spy stays a single instance across re-renders; recreating it would drop the call history
const requestedUrls: string[] = [];

function lastRequestedUrl() {
  return requestedUrls[requestedUrls.length - 1] ?? "";
}

// SWR のキャッシュをテストごとに捨てて、前のテストのデータを引き継がないようにする
// A fresh SWR cache per test so data never leaks from the previous test
function Wrapper({ children }: { children: ReactNode }) {
  return <SWRConfig value={{ provider: () => new Map() }}>{children}</SWRConfig>;
}

describe("useMemoPageList", () => {
  beforeEach(() => {
    requestedUrls.length = 0;
    vi.mocked(loadMemoList).mockImplementation(async (url: string) => {
      requestedUrls.push(url);
      const params = new URLSearchParams(url.split("?")[1] ?? "");
      const limit = Number(params.get("limit"));
      return { memos: allMemos.slice(0, limit), total: TOTAL_MEMOS };
    });
  });

  it("starts at the default limit and offers the remaining memos", async () => {
    const { result } = renderHook(() => useMemoPageList(), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.memos).toHaveLength(DEFAULT_LIMIT));
    expect(lastRequestedUrl()).toContain(`limit=${DEFAULT_LIMIT}`);
    expect(result.current.canLoadMoreMemos).toBe(true);
    expect(result.current.remainingMemoCount).toBe(TOTAL_MEMOS - DEFAULT_LIMIT);
  });

  it("raises the limit by one step per load more until nothing is left", async () => {
    const { result } = renderHook(() => useMemoPageList(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.memos).toHaveLength(DEFAULT_LIMIT));

    act(() => result.current.loadMoreMemos());
    await waitFor(() => expect(result.current.memos).toHaveLength(DEFAULT_LIMIT * 2));
    expect(lastRequestedUrl()).toContain(`limit=${DEFAULT_LIMIT * 2}`);

    act(() => result.current.loadMoreMemos());
    await waitFor(() => expect(result.current.memos).toHaveLength(TOTAL_MEMOS));
    expect(lastRequestedUrl()).toContain(`limit=${DEFAULT_LIMIT * 3}`);
    expect(result.current.canLoadMoreMemos).toBe(false);
    expect(result.current.remainingMemoCount).toBe(0);
  });

  it("keeps the already loaded memos on screen while the next page is fetched", async () => {
    const { result } = renderHook(() => useMemoPageList(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.memos).toHaveLength(DEFAULT_LIMIT));

    let release = () => {};
    vi.mocked(loadMemoList).mockImplementationOnce(async (url: string) => {
      requestedUrls.push(url);
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      return { memos: allMemos.slice(0, DEFAULT_LIMIT * 2), total: TOTAL_MEMOS };
    });

    act(() => result.current.loadMoreMemos());
    await waitFor(() => expect(result.current.isLoadingMoreMemos).toBe(true));
    expect(result.current.memos).toHaveLength(DEFAULT_LIMIT);

    await act(async () => {
      release();
    });
    await waitFor(() => expect(result.current.memos).toHaveLength(DEFAULT_LIMIT * 2));
  });

  it.each([
    ["sort order", (result: { setSortMode: (value: string) => void }) => result.setSortMode("recent"), "sort=recent"],
    [
      "archive scope",
      (result: { setArchiveScope: (value: string) => void }) => result.setArchiveScope("archived"),
      "only_archived=1",
    ],
    [
      "collection",
      (result: { setActiveCollectionId: (value: number | null) => void }) => result.setActiveCollectionId(4),
      "collection_id=4",
    ],
  ])("resets the limit to the default when the %s changes", async (_label, changeFilter, expectedParam) => {
    const { result } = renderHook(() => useMemoPageList(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.memos).toHaveLength(DEFAULT_LIMIT));

    act(() => result.current.loadMoreMemos());
    await waitFor(() => expect(lastRequestedUrl()).toContain(`limit=${DEFAULT_LIMIT * 2}`));

    act(() => changeFilter(result.current));
    await waitFor(() => expect(lastRequestedUrl()).toContain(expectedParam));
    expect(lastRequestedUrl()).toContain(`limit=${DEFAULT_LIMIT}&`);
    expect(result.current.memos).toHaveLength(DEFAULT_LIMIT);
  });

  it("resets the limit to the default when the search query changes", async () => {
    const { result } = renderHook(() => useMemoPageList(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.memos).toHaveLength(DEFAULT_LIMIT));

    act(() => result.current.loadMoreMemos());
    await waitFor(() => expect(lastRequestedUrl()).toContain(`limit=${DEFAULT_LIMIT * 2}`));

    act(() => result.current.setQuery("roadmap"));
    // 検索語は 300ms のデバウンス後にフェッチへ反映される
    // The query reaches the fetch after the 300ms debounce
    await waitFor(() => expect(lastRequestedUrl()).toContain("q=roadmap"), { timeout: 2000 });
    expect(lastRequestedUrl()).toContain(`limit=${DEFAULT_LIMIT}&`);
  });
});
