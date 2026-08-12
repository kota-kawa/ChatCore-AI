import { fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { initPromptAssist } from "../scripts/components/prompt_assist/init";
import { resilientFetch } from "../scripts/core/resilient_fetch";

vi.mock("../scripts/core/resilient_fetch", () => ({
  resilientFetch: vi.fn(),
}));

describe("投稿モーダルのAI補助", () => {
  afterEach(() => {
    document.body.replaceChildren();
    vi.restoreAllMocks();
  });

  it("投稿タイプ切替後は切替前の保留中レスポンスを表示しない", async () => {
    let resolveResponse: ((response: Response) => void) | undefined;
    vi.mocked(resilientFetch).mockImplementation(() => new Promise<Response>((resolve) => {
      resolveResponse = resolve;
    }));
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });

    const root = document.createElement("div");
    const title = document.createElement("input");
    const content = document.createElement("textarea");
    document.body.append(root, title, content);
    const controller = initPromptAssist({
      root,
      target: "shared_prompt_modal",
      fields: {
        title: { label: "タイトル", element: title },
        prompt_content: { label: "本文", element: content },
      },
    });

    fireEvent.click(root.querySelector<HTMLButtonElement>("[data-assist-run]")!);
    expect(root.querySelector(".prompt-assist")).toHaveClass("is-loading");

    controller?.updateForPromptType("image");
    resolveResponse?.(new Response(JSON.stringify({
      summary: "古いテキスト提案",
      suggested_fields: { title: "古いタイトル", prompt_content: "古い本文" },
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    await waitFor(() => {
      expect(root.querySelector("[data-assist-preview]")).toHaveAttribute("hidden");
    });
    expect(root).not.toHaveTextContent("古いテキスト提案");
    expect(root.querySelector("[data-assist-title]")).toHaveTextContent("画像生成プロンプト");
  });
});
