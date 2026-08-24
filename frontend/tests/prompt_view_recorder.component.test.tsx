import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useCallback, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PromptRecord } from "../components/prompt_share/prompt_card";
import { usePromptViewRecorder } from "../components/prompt_share/use_prompt_view_recorder";
import { recordPromptView } from "../scripts/prompt_share/api";


vi.mock("../scripts/prompt_share/api", () => ({
  recordPromptView: vi.fn()
}));


const initialPrompt: PromptRecord = {
  id: 42,
  clientId: "prompt-42",
  title: "人気順テスト",
  content: "本文",
  liked: false,
  used_in_chat: false,
  view_count: 5
};


function PromptViewRecorderHarness() {
  const [prompt, setPrompt] = useState(initialPrompt);
  const updatePromptRecord = useCallback(
    (_clientId: string, updater: (current: PromptRecord) => PromptRecord) => {
      setPrompt((current) => updater(current));
    },
    []
  );
  const recordOpen = usePromptViewRecorder({ updatePromptRecord });

  return (
    <>
      <button type="button" onClick={() => recordOpen(prompt)}>詳細を開く</button>
      <output>{prompt.view_count}</output>
    </>
  );
}


describe("usePromptViewRecorder", () => {
  beforeEach(() => {
    vi.mocked(recordPromptView).mockResolvedValue({
      status: "success",
      view_count: 6
    });
  });

  it("詳細を開いたときに1ビューを記録して最新件数を反映する", async () => {
    render(<PromptViewRecorderHarness />);

    fireEvent.click(screen.getByRole("button", { name: "詳細を開く" }));

    await waitFor(() => {
      expect(recordPromptView).toHaveBeenCalledOnce();
      expect(recordPromptView).toHaveBeenCalledWith("42");
      expect(screen.getByText("6")).toBeInTheDocument();
    });
  });
});
