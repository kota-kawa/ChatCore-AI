import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import type { KeyedMutator } from "swr";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MemoComposer } from "../components/memo/MemoComposer";
import { MemoNewFab } from "../components/memo/MemoNewFab";
import { MemoPageContextProvider } from "../contexts/memo_page/memo_page_context";
import { useMemoPageComposer } from "../hooks/memo_page/use_memo_page_composer";
import { createMemo } from "../lib/memo/api";
import type { FlashState, MemoListState } from "../lib/memo/types";
import { changeMemoEditor, memoEditor, memoEditorValue } from "./memo_editor_harness";
import { createMemoPageControllerStub } from "./memo_page_context_harness";

vi.mock("../lib/memo/api", () => ({
  createMemo: vi.fn(),
  suggestMemoTitle: vi.fn(),
}));

class HiddenComposerObserver {
  constructor(private readonly callback: IntersectionObserverCallback) {}

  observe(target: Element) {
    this.callback(
      [{ isIntersecting: false, target } as IntersectionObserverEntry],
      this as unknown as IntersectionObserver,
    );
  }

  disconnect() {}
  unobserve() {}
  takeRecords() { return []; }
}

const mutate = vi.fn(async () => undefined) as unknown as KeyedMutator<MemoListState>;
const showFlash = vi.fn();

function ComposerHarness() {
  const [, setFlashState] = useState<FlashState | null>(null);
  const composer = useMemoPageComposer({
    draftOwnerId: null,
    mutate,
    showFlash,
    setFlashState,
  });
  const controller = createMemoPageControllerStub(composer);

  return (
    <MemoPageContextProvider controller={controller}>
      <MemoComposer />
      <MemoNewFab />
      <button type="button">outside</button>
    </MemoPageContextProvider>
  );
}

describe("MemoComposer interactions", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(createMemo).mockResolvedValue(undefined);
    vi.clearAllMocks();
  });

  it("keeps a native collapsed text click inside the composer after it expands", () => {
    render(<ComposerHarness />);

    fireEvent.click(screen.getByRole("button", { name: "テキストメモを作成" }));

    expect(screen.getByRole("textbox", { name: "本文" })).toBeInTheDocument();
    expect(createMemo).not.toHaveBeenCalled();
  });

  it("opens the palette from its collapsed shortcut without submitting the opening click", () => {
    render(<ComposerHarness />);

    fireEvent.click(screen.getByRole("button", { name: "色を選択" }));

    expect(screen.getByRole("listbox", { name: "メモの背景色" })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("button", { name: "色を選択" }), { key: "Escape" });
    expect(screen.queryByRole("listbox", { name: "メモの背景色" })).toBeNull();
    expect(screen.getByRole("textbox", { name: "本文" })).toBeInTheDocument();
    expect(createMemo).not.toHaveBeenCalled();
  });

  it("focuses after the new checklist marker once the editor mounts", async () => {
    render(<ComposerHarness />);
    fireEvent.click(screen.getByRole("button", { name: "チェックリストを作成" }));
    const body = screen.getByRole("textbox", { name: "本文" });
    await waitFor(() => expect(body).toHaveFocus());
    expect(memoEditorValue(body)).toBe("- [ ] ");
    await waitFor(() => expect(memoEditor(body).state.selection.main.head).toBe("- [ ] ".length));
  });

  it("does not replay a fulfilled body focus request after choosing a color", async () => {
    render(<ComposerHarness />);
    fireEvent.click(screen.getByRole("button", { name: "テキストメモを作成" }));
    const body = screen.getByRole("textbox", { name: "本文" });
    await waitFor(() => expect(body).toHaveFocus());
    changeMemoEditor(body, "本文の途中");
    act(() => { memoEditor(body).dispatch({ selection: { anchor: 2 } }); });
    fireEvent.click(screen.getByText("その他", { selector: "summary" }));
    const palette = screen.getByRole("button", { name: "色を選択" });
    palette.focus();
    fireEvent.click(palette);
    fireEvent.click(await screen.findByRole("option", { name: "レモン" }));
    expect(body).not.toHaveFocus();
    expect(memoEditor(body).state.selection.main.head).toBe(2);
  });

  it("does not autosave an empty checklist marker, then saves once after text is entered", async () => {
    render(<ComposerHarness />);

    fireEvent.click(screen.getByRole("button", { name: "チェックリストを作成" }));
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "outside" }));
    expect(createMemo).not.toHaveBeenCalled();

    changeMemoEditor(screen.getByRole("textbox", { name: "本文" }), "- [ ] 牛乳を買う");
    fireEvent.click(screen.getByRole("button", { name: "outside" }));

    await waitFor(() => expect(createMemo).toHaveBeenCalledTimes(1));
    expect(createMemo).toHaveBeenCalledWith(
      { ai_response: "- [ ] 牛乳を買う", title: expect.any(String), collection_id: null, background_color: null },
      expect.any(String),
    );
  });

  it("uses a mobile dialog and preserves a marker-only draft when the backdrop closes it", async () => {
    const originalMatchMedia = window.matchMedia;
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = vi.fn();
    vi.stubGlobal("IntersectionObserver", HiddenComposerObserver);
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn((media: string) => ({
        matches: media === "(max-width: 768px)",
        media,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    });

    try {
      render(<ComposerHarness />);
      fireEvent.click(screen.getByRole("button", { name: "チェックリストを作成" }));

      await waitFor(() => expect(document.body.classList.contains("memo-compose-open")).toBe(true));
      const dialog = document.querySelector<HTMLElement>(".memo-compose-mobile-modal");
      expect(dialog).toHaveClass("is-open");
      expect(dialog?.querySelector(".memo-compose-sheet .memo-quick-capture.is-expanded")).toBeInTheDocument();
      expect(dialog?.querySelector(".cm-content")).toHaveAttribute("contenteditable", "true");

      fireEvent.click(dialog!);
      await waitFor(() => expect(document.body.classList.contains("memo-compose-open")).toBe(false));
      expect(dialog).not.toHaveClass("is-open");
      expect(createMemo).not.toHaveBeenCalled();

      const newFab = await waitFor(() => {
        const trigger = document.querySelector<HTMLButtonElement>("[data-memo-composer-trigger]");
        expect(trigger).toBeInTheDocument();
        return trigger!;
      });
      fireEvent.click(newFab);
      await waitFor(() => expect(document.querySelector(".memo-compose-mobile-modal")?.classList.contains("is-open")).toBe(true));
      const bodyInput = screen.getByRole("textbox", { name: "本文" });
      expect(memoEditorValue(bodyInput)).toBe("- [ ] ");
      expect(createMemo).not.toHaveBeenCalled();

      changeMemoEditor(bodyInput, "- [ ] 牛乳を買う");
      fireEvent.click(document.querySelector(".memo-compose-mobile-modal")!);
      await waitFor(() => expect(createMemo).toHaveBeenCalledTimes(1));
      expect(createMemo).toHaveBeenCalledWith(
        { ai_response: "- [ ] 牛乳を買う", title: expect.any(String), collection_id: null, background_color: null },
        expect.any(String),
      );
    } finally {
      if (originalMatchMedia) {
        Object.defineProperty(window, "matchMedia", { configurable: true, value: originalMatchMedia });
      } else {
        Reflect.deleteProperty(window, "matchMedia");
      }
      if (originalScrollIntoView) {
        HTMLElement.prototype.scrollIntoView = originalScrollIntoView;
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
      }
      vi.unstubAllGlobals();
      document.body.classList.remove("memo-compose-open");
    }
  });

  it("lets a phone composer format the current line on demand without submitting", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    try {
      render(<ComposerHarness />);
      fireEvent.click(screen.getByRole("button", { name: "テキストメモを作成" }));
      const body = screen.getByRole("textbox", { name: "本文" });
      changeMemoEditor(body, "最初の行\n次の行");
      const editor = memoEditor(body);
      act(() => { editor.dispatch({ selection: { anchor: editor.state.doc.length } }); editor.focus(); });
      const toggle = screen.getByRole("button", { name: "書式" });
      expect(screen.queryByRole("toolbar", { name: "書式" })).toBeNull();
      fireEvent.mouseDown(toggle);
      fireEvent.click(toggle);
      expect(screen.getByRole("toolbar", { name: "書式" })).toBeVisible();
      fireEvent.click(screen.getByRole("button", { name: "見出し" }));
      expect(memoEditorValue(body)).toBe("最初の行\n## 次の行");
      expect(body).toHaveFocus();
      fireEvent.click(toggle);
      expect(screen.queryByRole("toolbar", { name: "書式" })).toBeNull();
      expect(createMemo).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: "保存" }));
      await waitFor(() => expect(createMemo).toHaveBeenCalledWith(
        expect.objectContaining({ ai_response: "最初の行\n## 次の行" }), expect.any(String),
      ));
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
