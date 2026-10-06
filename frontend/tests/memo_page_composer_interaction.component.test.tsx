import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import type { KeyedMutator } from "swr";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MemoComposer } from "../components/memo/MemoComposer";
import { MemoNewFab } from "../components/memo/MemoNewFab";
import { MemoPageContextProvider } from "../contexts/memo_page/memo_page_context";
import { useMemoPageComposer } from "../hooks/memo_page/use_memo_page_composer";
import { createMemo } from "../lib/memo/api";
import type { FlashState, MemoListState } from "../lib/memo/types";
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

  it("does not autosave an empty checklist marker, then saves once after text is entered", async () => {
    render(<ComposerHarness />);

    fireEvent.click(screen.getByRole("button", { name: "チェックリストを作成" }));
    expect(screen.getByRole("button", { name: "完了" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "outside" }));
    expect(createMemo).not.toHaveBeenCalled();

    fireEvent.change(screen.getByRole("textbox", { name: "本文" }), { target: { value: "- [ ] 牛乳を買う" } });
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
      expect(dialog?.querySelector("textarea")?.style.height).toBe("");

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
      expect(bodyInput).toHaveValue("- [ ] ");
      expect(createMemo).not.toHaveBeenCalled();

      fireEvent.change(bodyInput, { target: { value: "- [ ] 牛乳を買う" } });
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
});
