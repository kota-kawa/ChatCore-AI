import { fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { usePromptModalManager } from "../components/prompt_share/use_prompt_modal_manager";

function PromptModalManagerHarness() {
  const postModalRef = useRef<HTMLDivElement | null>(null);
  const promptDetailModalRef = useRef<HTMLDivElement | null>(null);
  const promptShareModalRef = useRef<HTMLDivElement | null>(null);
  const { activeModal, closeModal, openModal } = usePromptModalManager({
    isPostSubmitting: false,
    onCloseDetail: vi.fn(),
    onClosePost: vi.fn(),
    postModalRef,
    promptDetailModalRef,
    promptShareModalRef
  });

  return (
    <>
      <button type="button" onClick={() => openModal("detail")}>
        詳細を開く
      </button>
      <div
        aria-hidden={activeModal === "detail" ? "false" : "true"}
        ref={promptDetailModalRef}
      >
        <button type="button" onClick={() => closeModal("detail")}>
          詳細を閉じる
        </button>
      </div>
      <div ref={postModalRef} />
      <div ref={promptShareModalRef} />
    </>
  );
}

describe("usePromptModalManager", () => {
  it("restores focus before hiding a closed modal", () => {
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    render(<PromptModalManagerHarness />);

    const opener = screen.getByRole("button", { name: "詳細を開く" });

    opener.focus();
    fireEvent.click(opener);
    const closer = screen.getByRole("button", { name: "詳細を閉じる" });
    const modal = closer.parentElement;
    if (!modal) {
      throw new Error("詳細モーダルが見つかりません。");
    }

    const originalSetAttribute = HTMLElement.prototype.setAttribute;
    let focusedElementWhenHidden: Element | null = null;
    vi.spyOn(HTMLElement.prototype, "setAttribute").mockImplementation(function (this: HTMLElement, name, value) {
      if (this === modal && name === "aria-hidden" && value === "true") {
        focusedElementWhenHidden = document.activeElement;
      }
      originalSetAttribute.call(this, name, value);
    });

    fireEvent.click(closer);

    expect(focusedElementWhenHidden).toBe(opener);
    expect(opener).toHaveFocus();
    expect(modal).toHaveAttribute("aria-hidden", "true");
  });
});
