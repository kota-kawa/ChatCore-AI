import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MemoComposeFormState } from "../lib/memo/types";

import {
  MemoPageControllerProvider,
  useMemoPageComposerContext,
  useMemoPageListContext,
} from "../contexts/memo_page/memo_page_context";

vi.mock("../hooks/memo_page/use_memo_page_controller", async () => {
  const React = await import("react");
  const controllerHarness = await import("./memo_page_context_harness");
  const emptyForm: MemoComposeFormState = { ai_response: "", title: "", collection_id: null, background_color: null };
  return {
    useMemoPageController() {
      const [formState, setFormState] = React.useState(emptyForm);
      return controllerHarness.createMemoPageControllerStub({ formState, setFormState });
    },
  };
});

const listRenders = vi.fn();

function ComposerProbe() {
  const { formState, setFormState } = useMemoPageComposerContext();
  return (
    <button
      type="button"
      onClick={() => setFormState((previous) => ({ ...previous, ai_response: "書きかけ" }))}
    >
      {formState.ai_response || "入力"}
    </button>
  );
}

function ListProbe() {
  useMemoPageListContext();
  listRenders();
  return <div>一覧</div>;
}

describe("MemoPageControllerProvider", () => {
  it("keeps list consumers from rendering when composer input changes", () => {
    render(
      <MemoPageControllerProvider>
        <ComposerProbe />
        <ListProbe />
      </MemoPageControllerProvider>,
    );

    expect(screen.getByText("入力")).toBeInTheDocument();
    expect(listRenders).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "入力" }));

    expect(screen.getByText("書きかけ")).toBeInTheDocument();
    expect(listRenders).toHaveBeenCalledTimes(1);
  });
});
