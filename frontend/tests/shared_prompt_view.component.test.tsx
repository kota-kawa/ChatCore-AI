import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "../contexts/locale_context";
import SharedPromptPage from "../pages/shared/prompt/[id]/[[...slug]]";
import { recordPromptView } from "../scripts/prompt_share/api";


vi.mock("../scripts/prompt_share/api", () => ({
  recordPromptView: vi.fn()
}));
vi.mock("../scripts/components/popup_menu", () => ({}));


describe("shared prompt view tracking", () => {
  beforeEach(() => {
    vi.mocked(recordPromptView).mockResolvedValue({
      status: "success",
      view_count: 11
    });
  });

  it("共有詳細がクライアントで表示されたときに1回だけ記録する", async () => {
    const props = {
      payload: {
        prompt: {
          id: 42,
          title: "共有プロンプト",
          content: "本文",
          content_format: "prompt",
          media_type: "text"
        }
      },
      recommendedPrompts: [],
      promptHtml: {
        content: "<p>本文</p>",
        inputExamples: "",
        outputExamples: "",
        skillMarkdown: "",
        skillPythonScript: ""
      },
      pageUrl: "https://chatcore-ai.com/shared/prompt/42/shared-prompt",
      defaultOgImageUrl: "https://chatcore-ai.com/static/img.jpg"
    };

    const { rerender } = render(
      <LocaleProvider initialLocale="ja">
        <SharedPromptPage {...props} />
      </LocaleProvider>
    );

    await waitFor(() => {
      expect(recordPromptView).toHaveBeenCalledOnce();
      expect(recordPromptView).toHaveBeenCalledWith(42);
    });

    rerender(
      <LocaleProvider initialLocale="ja">
        <SharedPromptPage {...props} />
      </LocaleProvider>
    );
    expect(recordPromptView).toHaveBeenCalledOnce();
  });
});
