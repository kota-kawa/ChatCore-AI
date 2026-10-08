import { act } from "@testing-library/react";
import { memoEditorViews, type MemoEditorHandle } from "../lib/memo/editor";

export function memoEditor(element: HTMLElement): MemoEditorHandle {
  const view = memoEditorViews.get(element);
  if (!view) throw new Error("Memo editor is not mounted");
  return view;
}

export function memoEditorValue(element: HTMLElement) {
  return memoEditor(element).state.doc.toString();
}

export function changeMemoEditor(element: HTMLElement, value: string) {
  const view = memoEditor(element);
  act(() => {
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value }, userEvent: "input" });
  });
}

// jsdom has no layout engine. Real geometry is checked separately with Playwright.
if (!Range.prototype.getClientRects) {
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
}
if (!Range.prototype.getBoundingClientRect) {
  Range.prototype.getBoundingClientRect = () => new DOMRect();
}
