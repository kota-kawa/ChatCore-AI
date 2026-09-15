import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useImeSubmitGuard } from "../hooks/use_ime_submit_guard";

// ガードを実DOMイベントで検証するための最小コンポーネント
// Minimal component that exercises the guard through real DOM events
function GuardedInput({ onSubmit }: { onSubmit: () => void }) {
  const { compositionHandlers, isComposingKeyEvent } = useImeSubmitGuard<HTMLTextAreaElement>();
  return (
    <textarea
      aria-label="input"
      {...compositionHandlers}
      onKeyDown={(event) => {
        if (event.key !== "Enter" || event.shiftKey) return;
        if (isComposingKeyEvent(event)) return;
        event.preventDefault();
        onSubmit();
      }}
    />
  );
}

function setup() {
  const onSubmit = vi.fn();
  render(<GuardedInput onSubmit={onSubmit} />);
  return { onSubmit, textarea: screen.getByLabelText("input") };
}

describe("useImeSubmitGuard", () => {
  it("変換していないEnterは送信として通す", () => {
    const { onSubmit, textarea } = setup();
    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("Shift+Enterは送信しない", () => {
    const { onSubmit, textarea } = setup();
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("変換中のEnter（isComposing）は送信しない", () => {
    const { onSubmit, textarea } = setup();
    fireEvent.compositionStart(textarea);
    fireEvent.keyDown(textarea, { key: "Enter", isComposing: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("Chrome/Edgeの変換中keydown（keyCode 229）は送信しない", () => {
    const { onSubmit, textarea } = setup();
    fireEvent.keyDown(textarea, { key: "Enter", keyCode: 229 });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("Firefoxの変換中keydown（key === \"Process\"）は送信しない", () => {
    const { onSubmit, textarea } = setup();
    fireEvent.keyDown(textarea, { key: "Process" });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  // macOS Safari は変換確定のEnterで compositionend を keydown より先に流すため、
  // keydown 時点では isComposing が false になっている。これが誤送信の本体。
  // Safari on macOS emits compositionend before the keydown of the confirming Enter, so
  // isComposing is already false by then. This is the actual misfire.
  it("compositionend直後のEnter（Safari/macOSの変換確定）は送信しない", () => {
    const { onSubmit, textarea } = setup();
    fireEvent.compositionStart(textarea);
    fireEvent.compositionEnd(textarea, { data: "日本語" });
    fireEvent.keyDown(textarea, { key: "Enter", isComposing: false });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  // Android のソフトキーボードは英単語の入力でも送信キーの直前に compositionend を出す。
  // ここまで猶予に含めると、英語入力の送信が丸ごと効かなくなる。
  // Android soft keyboards emit compositionend right before the send key even for plain English
  // words; covering that with the grace window would break sending on English input entirely.
  it("ASCIIだけの確定（Androidの英単語入力）は送信を止めない", () => {
    const { onSubmit, textarea } = setup();
    fireEvent.compositionStart(textarea);
    fireEvent.compositionEnd(textarea, { data: "hello" });
    fireEvent.keyDown(textarea, { key: "Enter", isComposing: false });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("変換確定から十分に間が空いたEnterは送信する", async () => {
    const { onSubmit, textarea } = setup();
    fireEvent.compositionStart(textarea);
    fireEvent.compositionEnd(textarea, { data: "日本語" });
    await new Promise((resolve) => setTimeout(resolve, 120));
    fireEvent.keyDown(textarea, { key: "Enter", isComposing: false });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
