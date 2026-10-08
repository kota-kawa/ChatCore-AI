import { act, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import type { MemoEditorHandle } from "../lib/memo/editor";
import { describe, expect, it, vi } from "vitest";

import { MemoEditor } from "../components/memo/MemoEditor";
import { changeMemoEditor, memoEditor, memoEditorValue } from "./memo_editor_harness";
import { executeActionSteps } from "../lib/chat_page/mini_chat_runtime";

function Harness({ initial = "# 見出し\n\n本文 **強調** と *斜体*\n\n- [ ] 牛乳\n\n```js\nconst a = 1;\n```\n\n| A | B |\n|---|---|\n| C | D |", editing = false }) {
  const [value, setValue] = useState(initial);
  const [source, setSource] = useState(editing);
  const ref = useRef<MemoEditorHandle | null>(null);
  return <>
    <MemoEditor value={value} onChange={setValue} sourceMode={source} editorRef={ref} label="本文" placeholder="メモを入力" id="test-editor" />
    <button onClick={() => setSource(!source)}>原文</button>
    <button onClick={() => setValue(value + "\nAIが追記")}>外部更新</button>
    <output data-testid="stored">{value}</output>
  </>;
}

const element = () => screen.getByRole("textbox", { name: "本文" });

describe("MemoEditor", () => {
  it("renders Markdown while keeping its source unchanged", () => {
    render(<Harness />);
    expect(document.querySelector("h1")).toHaveTextContent("見出し");
    expect(document.querySelector("strong")).toHaveTextContent("強調");
    expect(screen.getByRole("checkbox", { name: "牛乳" })).not.toBeChecked();
    expect(screen.getByRole("columnheader", { name: "A" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "D" })).toBeInTheDocument();
    expect(screen.getByTestId("stored").textContent).toBe(memoEditorValue(element()));
  });

  it("keeps formatted content editable without showing Markdown on clicks", () => {
    render(<Harness />);
    const view = memoEditor(element());
    act(() => {
      view.dispatch({ selection: { anchor: view.state.doc.toString().indexOf("強調") + 1 } });
      view.focus();
    });
    fireEvent.click(document.querySelector("td")!);
    fireEvent.click(document.querySelector("pre code")!);
    expect(element()).toHaveAttribute("contenteditable", "true");
    expect(document.querySelector("strong")).toHaveTextContent(/^強調$/);
    expect(element()).not.toHaveTextContent("**強調**");
    expect(document.querySelector("h1")).toHaveTextContent("見出し");
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(document.querySelector("pre code")).toHaveTextContent("const a = 1;");
    expect(document.querySelector(".memo-rich-code-language")).toHaveTextContent("js");
    expect(document.querySelector(".hljs-keyword")).toHaveTextContent("const");
  });

  it("renders ordered lists and keeps their original source until changed", () => {
    render(<Harness initial={"3) first\n8) second"} />);
    expect(document.querySelector("ol")).toHaveAttribute("start", "3");
    expect(document.querySelectorAll("li")).toHaveLength(2);
    expect(memoEditorValue(element())).toBe("3) first\n8) second");
  });

  it("toggles a formatted checklist without exposing the source", () => {
    render(<Harness initial={"- [ ] first\n- [x] second"} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "second" }));
    expect(memoEditorValue(element())).toContain("- [ ] second");
    expect(element()).not.toHaveTextContent("[ ]");
  });

  it("keeps numbered checklist items editable with their numbering", () => {
    render(<Harness initial={"3) [ ] first\n8) [x] second"} />);
    expect(document.querySelector("ol")).toHaveAttribute("start", "3");
    expect(screen.getByRole("checkbox", { name: "second" })).toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: "first" }));
    expect(memoEditorValue(element())).toContain("3. [x] first");
    expect(memoEditorValue(element())).toContain("4. [x] second");
  });

  it("preserves the undo history across source mode and external updates", () => {
    render(<Harness initial="元の本文" editing />);
    const view = memoEditor(element());
    changeMemoEditor(element(), "手編集");
    fireEvent.click(screen.getByText("原文", { selector: "button" }));
    fireEvent.click(screen.getByText("原文", { selector: "button" }));
    expect(memoEditor(element())).toBe(view);
    fireEvent.click(screen.getByText("外部更新"));
    act(() => { view.undo(); });
    expect(screen.getByTestId("stored")).toHaveTextContent("手編集");
    act(() => { view.undo(); });
    expect(screen.getByTestId("stored")).toHaveTextContent("元の本文");
    act(() => { view.redo(); });
    expect(screen.getByTestId("stored")).toHaveTextContent("手編集");
  });

  it("continues checklists and exits an empty item with the mobile input event", () => {
    render(<Harness initial="- [x] 卵" editing />);
    const view = memoEditor(element());
    act(() => { view.dispatch({ selection: { anchor: view.state.doc.length } }); view.focus(); });
    fireEvent.keyDown(element(), { key: "Enter", keyCode: 13 });
    expect(memoEditorValue(element())).toBe("- [x] 卵\n- [ ] ");
    act(() => { element().dispatchEvent(new InputEvent("beforeinput", { inputType: "insertParagraph", bubbles: true, cancelable: true })); });
    expect(memoEditorValue(element())).toBe("- [x] 卵\n");
  });

  it("keeps a table and rich formatting across source display changes", () => {
    render(<Harness />);
    const view = memoEditor(element());
    fireEvent.click(screen.getByText("原文", { selector: "button" }));
    expect(element()).toHaveTextContent("**強調**");
    fireEvent.click(screen.getByText("原文", { selector: "button" }));
    expect(memoEditor(element())).toBe(view);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(document.querySelector("strong")).toHaveTextContent("強調");
  });

  it("does not continue the list during Japanese composition", () => {
    render(<Harness initial="- [ ] 日本語" editing />);
    const view = memoEditor(element());
    act(() => { view.dispatch({ selection: { anchor: view.state.doc.length } }); });
    act(() => { element().dispatchEvent(new InputEvent("beforeinput", { inputType: "insertParagraph", isComposing: true, bubbles: true, cancelable: true })); });
    expect(memoEditorValue(element())).toBe("- [ ] 日本語");
  });

  it("edits legacy JSON-string memos without changing their storage format", () => {
    const initial = JSON.stringify("# 見出し\n\n本文");
    render(<Harness initial={initial} editing />);
    expect(memoEditorValue(element())).toBe("# 見出し\n\n本文");
    expect(screen.getByTestId("stored").textContent).toBe(initial);
    changeMemoEditor(element(), "# 見出し\n\n変更後");
    expect(screen.getByTestId("stored").textContent).toBe(JSON.stringify("# 見出し\n\n変更後"));
  });

  it("keeps list-looking text in code blocks as code on Enter", () => {
    render(<Harness initial={"```text\n- example\n```"} editing />);
    const view = memoEditor(element());
    act(() => { view.dispatch({ selection: { anchor: view.state.doc.toString().indexOf("example") + 7 } }); view.focus(); });
    fireEvent.keyDown(element(), { key: "Enter", keyCode: 13 });
    expect(memoEditorValue(element())).toBe("```text\n- example\n\n```");
  });

  it("accepts the existing page agent's input action and makes it undoable", async () => {
    render(<Harness initial="元の本文" editing />);
    vi.spyOn(element(), "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, 300, 100));
    await act(async () => {
      const result = await executeActionSteps([{ action: "input", selector: "#test-editor", value: "# 入力したメモ", risk: "low", description: "メモ本文を入力する" }], {
        navigateInternal: async () => ({ ok: false, clientSide: false }),
        setUnloadContext: () => undefined,
      });
      expect(result).toEqual({ ok: true });
    });
    expect(screen.getByTestId("stored")).toHaveTextContent("# 入力したメモ");
    act(() => { memoEditor(element()).undo(); });
    expect(screen.getByTestId("stored")).toHaveTextContent("元の本文");
  });

  it("keeps unsafe URLs and raw HTML inert", () => {
    render(<Harness initial={'[unsafe](javascript:alert(1))\n\n<script>window.BAD=1</script>\n\n| A | B |\n|---|---|\n| <img src=x onerror=alert(1)> | D |'} />);
    expect(document.querySelector("a[href^='javascript:']")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect(document.querySelector("[onerror]")).toBeNull();
  });
});
