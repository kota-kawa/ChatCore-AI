import { fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { usePromptModalManager } from "../components/prompt_share/use_prompt_modal_manager";
import { getModalFocusableElements } from "../components/prompt_share/prompt_share_page_utils";

function PromptModalManagerHarness({ isEditSaving = false }: { isEditSaving?: boolean }) {
  const editModalRef = useRef<HTMLDivElement | null>(null);
  const postModalRef = useRef<HTMLDivElement | null>(null);
  const promptDetailModalRef = useRef<HTMLDivElement | null>(null);
  const promptShareModalRef = useRef<HTMLDivElement | null>(null);
  const promptAuthorProfileModalRef = useRef<HTMLDivElement | null>(null);
  const { activeModal, closeModal, openModal } = usePromptModalManager({
    isEditSaving,
    isPostSubmitting: false,
    onCloseEdit: vi.fn(),
    onCloseDetail: vi.fn(),
    onClosePost: vi.fn(),
    onCloseProfile: vi.fn(),
    editModalRef,
    postModalRef,
    promptDetailModalRef,
    promptShareModalRef,
    promptAuthorProfileModalRef
  });

  return (
    <>
      <button type="button" onClick={() => openModal("detail")}>
        詳細を開く
      </button>
      <button type="button" onClick={() => openModal("edit")}>
        編集を開く
      </button>
      <button type="button" onClick={() => closeModal("edit")}>
        編集を閉じる
      </button>
      <output>{activeModal || "none"}</output>
      <div
        aria-hidden={activeModal === "detail" ? "false" : "true"}
        ref={promptDetailModalRef}
      >
        <button type="button" onClick={() => closeModal("detail")}>
          詳細を閉じる
        </button>
      </div>
      <div ref={postModalRef} />
      <div ref={editModalRef}>
        <button type="button">編集フォーム</button>
      </div>
      <div ref={promptShareModalRef} />
    </>
  );
}

describe("usePromptModalManager", () => {
  it("送信中fieldsetから継承して無効な要素をフォーカス対象から除外する", () => {
    const modal = document.createElement("div");
    modal.innerHTML = `
      <fieldset disabled><input id="disabled-child" /></fieldset>
      <button id="available">閉じる</button>
    `;
    document.body.append(modal);
    const getClientRects = vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue({ length: 1 } as DOMRectList);

    expect(getModalFocusableElements(modal).map((element) => element.id)).toEqual(["available"]);

    getClientRects.mockRestore();
    modal.remove();
  });

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

  // 背景スクロールのロックは開いている間だけ掛かり、閉じると解除される
  // The background scroll lock applies only while a modal is open and lifts on close
  it("locks the page scroll while a modal is open", () => {
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    render(<PromptModalManagerHarness />);

    fireEvent.click(screen.getByRole("button", { name: "詳細を開く" }));
    expect(document.body).toHaveClass("ps-modal-open");
    expect(document.body.style.position).toBe("fixed");

    fireEvent.click(screen.getByRole("button", { name: "詳細を閉じる" }));
    expect(document.body).not.toHaveClass("ps-modal-open");
    expect(document.body.style.position).toBe("");
  });

  // Escape 自体は ModalShell が扱うが、保存中は closeModal が閉じるのを拒む
  // ModalShell owns Escape itself, but closeModal refuses to close while saving
  it("保存中の編集モーダルは閉じない", () => {
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    render(<PromptModalManagerHarness isEditSaving />);

    fireEvent.click(screen.getByRole("button", { name: "編集を開く" }));
    expect(screen.getByText("edit")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "編集を閉じる" }));

    expect(screen.getByText("edit")).toBeInTheDocument();
  });
});
