// メモ作成欄の「その他」メニューと色パレットが、外側の押下で閉じるだけになることを検証する。
// Tests that the composer's "More" menu and color palette only close on an outside press.

import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { MemoComposer } from "../components/memo/MemoComposer";
import { MemoPageContextProvider } from "../contexts/memo_page/memo_page_context";
import type { MemoComposeFormState } from "../lib/memo/types";
import { createMemoPageControllerStub } from "./memo_page_context_harness";

const onSubmit = vi.fn();
const onOutsideClick = vi.fn();

function ComposerHarness({ initial }: { initial: MemoComposeFormState }) {
  const [formState, setFormState] = useState(initial);
  const [isComposeExpanded, setIsComposeExpanded] = useState(true);
  const [isComposePaletteOpen, setIsComposePaletteOpen] = useState(false);
  const hasComposeDraft = Boolean(formState.ai_response.trim() || formState.title.trim() || formState.background_color);
  const controller = createMemoPageControllerStub({
    formState,
    setFormState,
    hasComposeDraft,
    composeIsExpanded: isComposeExpanded || hasComposeDraft,
    setIsComposeExpanded,
    isComposePaletteOpen,
    setIsComposePaletteOpen,
    openComposePalette: () => setIsComposePaletteOpen((open) => !open),
    collections: [{ id: 1, name: "仕事", color: "#6b7280" }] as never,
    handleFormChange: (event) => setFormState((prev) => ({ ...prev, [event.target.name]: event.target.value })),
    handleSubmitMemo: async (event) => {
      event.preventDefault();
      onSubmit();
    },
  });
  return (
    <MemoPageContextProvider controller={controller}>
      <MemoComposer />
      <button type="button" onClick={onOutsideClick}>outside</button>
      <output data-testid="background-color">{formState.background_color ?? ""}</output>
      <output data-testid="collection-id">{String(formState.collection_id ?? "")}</output>
    </MemoPageContextProvider>
  );
}

const draft: MemoComposeFormState = { ai_response: "書きかけ", title: "題", collection_id: null, background_color: null };

// 実ブラウザのマウス操作と同じ順に、押してから離すまでのイベントを送る
// Dispatch a whole mouse press in the order a real browser does
function pressWithMouse(element: Element) {
  fireEvent.pointerDown(element);
  const mouseDown = fireEvent.mouseDown(element);
  fireEvent.pointerUp(element);
  fireEvent.mouseUp(element);
  const click = fireEvent.click(element, { detail: 1 });
  return { mouseDown, click };
}

function renderWithMoreOpen() {
  render(<ComposerHarness initial={draft} />);
  fireEvent.click(screen.getByText("その他", { selector: "summary" }));
  expect(screen.getByRole("button", { name: "Markdown原文" })).toBeVisible();
}

function renderWithPaletteOpen() {
  renderWithMoreOpen();
  fireEvent.click(screen.getByRole("button", { name: "色を選択" }));
  expect(screen.getByRole("listbox", { name: "メモの背景色" })).toBeInTheDocument();
}

const moreOpen = () => screen.getByText("その他", { selector: "summary" }).closest("details")!.open;
const paletteOpen = () => screen.queryByRole("listbox", { name: "メモの背景色" }) !== null;

describe("MemoComposer menus: outside press", () => {
  it.each([
    ["本文", () => screen.getByRole("textbox", { name: "本文" })],
    ["タイトル", () => screen.getByRole("textbox", { name: "タイトル" })],
    ["作成欄の外", () => screen.getByRole("button", { name: "outside" })],
  ])("closes the More panel only when %s is pressed", (_label, getTarget) => {
    onSubmit.mockClear();
    onOutsideClick.mockClear();
    renderWithMoreOpen();

    const { mouseDown, click } = pressWithMouse(getTarget());

    expect(moreOpen()).toBe(false);
    // fireEvent は既定動作が打ち消されたとき false を返す / fireEvent returns false when the default was prevented
    expect(mouseDown).toBe(false);
    expect(click).toBe(false);
    expect(onOutsideClick).not.toHaveBeenCalled();
    // 外側クリックの自動保存は、メニューを閉じた押下では起きない / The outside-click autosave does not run for the press that closed the menu
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("autosaves on the next outside press once the menu is closed", () => {
    onSubmit.mockClear();
    renderWithMoreOpen();
    pressWithMouse(screen.getByRole("button", { name: "outside" }));
    expect(onSubmit).not.toHaveBeenCalled();

    const { click } = pressWithMouse(screen.getByRole("button", { name: "outside" }));

    expect(click).toBe(true);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("does not intercept presses on the title while no menu is open", () => {
    render(<ComposerHarness initial={draft} />);

    const { mouseDown, click } = pressWithMouse(screen.getByRole("textbox", { name: "タイトル" }));

    expect(mouseDown).toBe(true);
    expect(click).toBe(true);
  });

  it("keeps the panel open for presses inside it, including the MemoSelect dropdown", () => {
    renderWithMoreOpen();

    const { mouseDown } = pressWithMouse(document.querySelector(".memo-quick-capture__bottom-row")!);
    expect(mouseDown).toBe(true);
    expect(moreOpen()).toBe(true);

    pressWithMouse(screen.getByRole("button", { name: /コレクションなし/ }));
    const option = screen.getByRole("option", { name: "仕事" });
    const press = pressWithMouse(option);

    expect(press.mouseDown).toBe(true);
    expect(screen.getByTestId("collection-id")).toHaveTextContent("1");
    expect(moreOpen()).toBe(true);
  });

  it("closes only the palette when the press is outside it but inside the panel", () => {
    renderWithPaletteOpen();

    const { mouseDown } = pressWithMouse(document.querySelector(".memo-quick-capture__bottom-row")!);

    expect(mouseDown).toBe(false);
    expect(paletteOpen()).toBe(false);
    expect(moreOpen()).toBe(true);
  });

  it("closes both the palette and the panel when the press is outside the panel", () => {
    renderWithPaletteOpen();

    const { mouseDown, click } = pressWithMouse(screen.getByRole("textbox", { name: "本文" }));

    expect(mouseDown).toBe(false);
    expect(click).toBe(false);
    expect(paletteOpen()).toBe(false);
    expect(moreOpen()).toBe(false);
  });

  it("treats the palette trigger and menu as inside the palette", () => {
    renderWithPaletteOpen();

    const option = screen.getByRole("option", { name: "レモン" });
    const { mouseDown } = pressWithMouse(option);

    expect(mouseDown).toBe(true);
    expect(screen.getByTestId("background-color")).not.toBeEmptyDOMElement();
    expect(paletteOpen()).toBe(false);
  });

  it("lets the palette trigger toggle the palette instead of dismissing it first", () => {
    renderWithPaletteOpen();

    const { mouseDown } = pressWithMouse(screen.getByRole("button", { name: "色を選択" }));

    expect(mouseDown).toBe(true);
    expect(paletteOpen()).toBe(false);
    expect(moreOpen()).toBe(false);
  });

  // スマホ用ダイアログでは、背景を押してもダイアログごと閉じず、メニューだけを閉じる。
  // In the phone dialog, pressing the backdrop closes only the menu, not the dialog with its autosave.
  it("closes only the menu when the phone dialog backdrop is pressed", () => {
    onSubmit.mockClear();
    vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    try {
      render(<ComposerHarness initial={draft} />);
      fireEvent.click(screen.getByText("その他", { selector: "summary" }));
      expect(moreOpen()).toBe(true);

      const { click } = pressWithMouse(document.querySelector(".memo-compose-mobile-modal")!);

      expect(click).toBe(false);
      expect(moreOpen()).toBe(false);
      expect(document.querySelector(".memo-compose-mobile-modal")).toHaveClass("is-open");
      expect(onSubmit).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
