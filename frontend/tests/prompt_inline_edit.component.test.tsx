import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PromptSharePage from "../pages/prompt_share";

const mocks = vi.hoisted(() => ({
  fetchPromptList: vi.fn(),
  settingsFetchJsonOrThrow: vi.fn(),
  showToast: vi.fn()
}));

vi.mock("../components/prompt_share/use_prompt_share_auth", () => ({
  usePromptShareAuth: () => ({
    authUiReady: true,
    currentUserId: 42,
    isLoggedIn: true
  })
}));

vi.mock("../components/prompt_share/use_prompt_share_page_setup", () => ({
  usePromptSharePageSetup: () => false
}));

vi.mock("../scripts/components/prompt_assist", () => ({
  initPromptAssist: () => null
}));

vi.mock("../scripts/prompt_share/api", () => ({
  createPrompt: vi.fn(),
  fetchPromptList: mocks.fetchPromptList,
  fetchPromptSearchResults: vi.fn()
}));

vi.mock("../scripts/user/settings/api", () => ({
  settingsFetchJsonOrThrow: mocks.settingsFetchJsonOrThrow
}));

vi.mock("../scripts/core/toast", () => ({
  showToast: mocks.showToast
}));

const ownedPrompt = {
  id: 12,
  title: "変更前のタイトル",
  content: "変更前の本文",
  description: "編集前の説明",
  category: "business",
  author: "Kota",
  author_user_id: 42,
  content_format: "prompt",
  media_type: "text",
  attributes: {},
  input_examples: "",
  output_examples: "",
  created_at: "2026-08-01T00:00:00Z"
};

describe("prompt share inline editing", () => {
  beforeEach(() => {
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    mocks.fetchPromptList.mockResolvedValue({
      prompts: [ownedPrompt],
      pagination: { has_next: false }
    });
    mocks.settingsFetchJsonOrThrow.mockResolvedValue({
      payload: { message: "更新しました。" }
    });
  });

  it("本人のカードから編集して保存すると、再読込なしでカードへ反映する", async () => {
    render(
      <PromptSharePage
        initialPrompts={[ownedPrompt]}
        initialPagination={{ has_next: false }}
      />
    );

    await waitFor(() => {
      expect(mocks.fetchPromptList).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByRole("button", { name: "その他の操作" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "プロンプト編集" }));

    const titleInput = screen.getByDisplayValue("変更前のタイトル");
    fireEvent.change(titleInput, { target: { value: "変更後のタイトル" } });
    fireEvent.click(screen.getByRole("button", { name: "変更を保存" }));

    await waitFor(() => {
      expect(mocks.settingsFetchJsonOrThrow).toHaveBeenCalledWith(
        "/prompt_manage/api/prompts/12",
        expect.objectContaining({
          method: "PUT",
          body: expect.stringContaining('"title":"変更後のタイトル"')
        }),
        expect.any(Object)
      );
    });
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "変更後のタイトル" })).toBeInTheDocument();
    });
    expect(screen.queryByRole("dialog", { name: "プロンプトを編集" })).not.toBeInTheDocument();
    expect(mocks.showToast).toHaveBeenCalledWith("更新しました。", { variant: "success" });
  });

  it("更新に失敗した場合は元のカード内容と編集モーダルを維持する", async () => {
    mocks.settingsFetchJsonOrThrow.mockRejectedValueOnce(new Error("更新できませんでした。"));
    render(
      <PromptSharePage
        initialPrompts={[ownedPrompt]}
        initialPagination={{ has_next: false }}
      />
    );

    await waitFor(() => {
      expect(mocks.fetchPromptList).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByRole("button", { name: "その他の操作" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "プロンプト編集" }));
    fireEvent.change(screen.getByDisplayValue("変更前のタイトル"), {
      target: { value: "反映してはいけないタイトル" }
    });
    fireEvent.click(screen.getByRole("button", { name: "変更を保存" }));

    await waitFor(() => {
      expect(mocks.showToast).toHaveBeenCalledWith("更新できませんでした。", {
        variant: "error"
      });
    });
    expect(screen.getByRole("heading", { name: "変更前のタイトル" })).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "プロンプトを編集" })).toBeInTheDocument();
  });
});
