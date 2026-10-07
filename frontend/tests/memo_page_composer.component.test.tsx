import { act, renderHook } from "@testing-library/react";
import type { FormEvent } from "react";
import type { KeyedMutator } from "swr";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMemoPageComposer } from "../hooks/memo_page/use_memo_page_composer";
import { createMemo, suggestMemoTitle } from "../lib/memo/api";
import type { MemoListState } from "../lib/memo/types";
import { STORAGE_KEYS } from "../scripts/core/constants";

vi.mock("../lib/memo/api", () => ({
  createMemo: vi.fn(),
  suggestMemoTitle: vi.fn(),
}));

const emptyForm = { ai_response: "", title: "", collection_id: null, background_color: null };

function makeSubmitEvent() {
  return { preventDefault: vi.fn() } as unknown as FormEvent<HTMLFormElement>;
}

// モックは再レンダーを跨いで同一インスタンスである必要がある（SWR の mutate は安定参照のため）
// Mocks must stay stable across re-renders, mirroring SWR's stable mutate reference
const mutateMock = vi.fn(async () => undefined);
const mutate = mutateMock as unknown as KeyedMutator<MemoListState>;
const showFlash = vi.fn();
const setFlashState = vi.fn();

function useComposerHarness(draftOwnerId: string | null = "1") {
  return useMemoPageComposer({ draftOwnerId, mutate, showFlash, setFlashState });
}

describe("useMemoPageComposer", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(createMemo).mockResolvedValue(undefined);
    vi.mocked(suggestMemoTitle).mockResolvedValue({ title: "提案タイトル" });
  });

  it("rejects an empty body without calling the API", async () => {
    const { result } = renderHook(() => useComposerHarness());

    await act(async () => {
      await result.current.handleSubmitMemo(makeSubmitEvent());
    });

    expect(createMemo).not.toHaveBeenCalled();
    expect(showFlash).toHaveBeenCalledWith("error", expect.any(String));
    expect(result.current.submitting).toBe(false);
  });

  it("creates the memo, resets the form and collapses the composer", async () => {
    const { result } = renderHook(() => useComposerHarness());

    act(() => {
      result.current.openTextComposer();
      result.current.setFormState({ ...emptyForm, ai_response: "hello", title: "t" });
    });
    expect(result.current.composeIsExpanded).toBe(true);
    expect(result.current.hasComposeDraft).toBe(true);

    await act(async () => {
      await result.current.handleSubmitMemo(makeSubmitEvent());
    });

    expect(createMemo).toHaveBeenCalledWith(
      { ai_response: "hello", title: "t", collection_id: null, background_color: null },
      expect.any(String),
    );
    expect(result.current.formState).toEqual(emptyForm);
    expect(result.current.composeIsExpanded).toBe(false);
    expect(result.current.hasComposeDraft).toBe(false);
    expect(setFlashState).toHaveBeenCalledWith(null);
    expect(showFlash).toHaveBeenCalledWith("success", expect.any(String));
    expect(mutateMock).toHaveBeenCalled();
  });

  it("surfaces the API error message and keeps the draft", async () => {
    vi.mocked(createMemo).mockRejectedValueOnce(new Error("保存に失敗"));
    const { result } = renderHook(() => useComposerHarness());

    act(() => {
      result.current.setFormState({ ...emptyForm, ai_response: "hello" });
    });
    await act(async () => {
      await result.current.handleSubmitMemo(makeSubmitEvent());
    });

    expect(showFlash).toHaveBeenCalledWith("error", "保存に失敗");
    expect(result.current.formState.ai_response).toBe("hello");
    expect(result.current.submitting).toBe(false);
  });

  it("applies the suggested title and keeps the existing one when none comes back", async () => {
    const { result } = renderHook(() => useComposerHarness());

    act(() => {
      result.current.setFormState({ ...emptyForm, ai_response: "body" });
    });
    await act(async () => {
      await result.current.handleAiSuggest();
    });
    expect(suggestMemoTitle).toHaveBeenCalledWith("body", expect.any(String));
    expect(result.current.formState.title).toBe("提案タイトル");

    vi.mocked(suggestMemoTitle).mockResolvedValueOnce({});
    await act(async () => {
      await result.current.handleAiSuggest();
    });
    expect(result.current.formState.title).toBe("提案タイトル");
    expect(result.current.aiSuggesting).toBe(false);
  });

  it("starts a checklist line and appends to an existing body", () => {
    const { result } = renderHook(() => useComposerHarness());

    act(() => {
      result.current.openChecklistComposer();
    });
    expect(result.current.formState.ai_response).toBe("- [ ] ");
    expect(result.current.formState.title).not.toBe("");
    expect(result.current.composeIsExpanded).toBe(true);

    act(() => {
      result.current.setFormState((prev) => ({ ...prev, ai_response: "abc  " }));
    });
    act(() => {
      result.current.openChecklistComposer();
    });
    expect(result.current.formState.ai_response).toBe("abc\n- [ ] ");
  });

  it("restores an unsaved draft after a remount and forgets it once saved", async () => {
    const first = renderHook(() => useComposerHarness());
    act(() => {
      first.result.current.setFormState({ ...emptyForm, ai_response: "書きかけ", title: "下書き", collection_id: 7 });
    });
    first.unmount();

    const second = renderHook(() => useComposerHarness());
    expect(second.result.current.formState).toEqual({ ...emptyForm, ai_response: "書きかけ", title: "下書き" });
    expect(second.result.current.composeIsExpanded).toBe(true);

    await act(async () => {
      await second.result.current.handleSubmitMemo(makeSubmitEvent());
    });
    expect(localStorage.getItem(STORAGE_KEYS.memoComposeDraft)).toBeNull();
    second.unmount();

    const third = renderHook(() => useComposerHarness());
    expect(third.result.current.formState).toEqual(emptyForm);
  });

  it("ignores a stored draft that is not valid", () => {
    localStorage.setItem(STORAGE_KEYS.memoComposeDraft, JSON.stringify({ owner: "1", ai_response: 3, background_color: "red" }));
    const { result } = renderHook(() => useComposerHarness());
    expect(result.current.formState).toEqual(emptyForm);
  });

  it("never shows one user's draft to another user or to a guest", () => {
    const owner = renderHook(() => useComposerHarness("1"));
    act(() => {
      owner.result.current.setFormState({ ...emptyForm, ai_response: "ユーザー1の書きかけ" });
    });
    owner.unmount();

    // 利用者が確認できるまで（および未ログイン）は復元も上書きもしない
    // Nothing is restored or overwritten until the user is confirmed (and for guests)
    const guest = renderHook(() => useComposerHarness(null));
    expect(guest.result.current.formState).toEqual(emptyForm);
    expect(localStorage.getItem(STORAGE_KEYS.memoComposeDraft)).toContain("ユーザー1の書きかけ");
    guest.unmount();

    const other = renderHook(() => useComposerHarness("2"));
    expect(other.result.current.formState).toEqual(emptyForm);
    expect(localStorage.getItem(STORAGE_KEYS.memoComposeDraft)).toBeNull();
  });

  it("restores the draft once the user is confirmed after the first render", () => {
    localStorage.setItem(STORAGE_KEYS.memoComposeDraft, JSON.stringify({ owner: "1", title: "", ai_response: "後から復元", background_color: null }));
    const { result, rerender } = renderHook(({ owner }: { owner: string | null }) => useComposerHarness(owner), {
      initialProps: { owner: null as string | null },
    });
    expect(result.current.formState).toEqual(emptyForm);
    rerender({ owner: "1" });
    expect(result.current.formState.ai_response).toBe("後から復元");
  });
});
