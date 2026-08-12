import { act, renderHook } from "@testing-library/react";
import type { ChangeEvent } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { usePromptImageSelection } from "../components/prompt_share/use_prompt_image_selection";
import type { MediaType } from "../scripts/prompt_share/types";

describe("画像生成プロンプトの作例画像", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("投稿タイプを一時的に切り替えても選択済み画像を保持する", () => {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:example");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const file = new File(["image"], "example.png", { type: "image/png" });
    const { result, rerender } = renderHook(
      ({ mediaType }: { mediaType: MediaType }) => usePromptImageSelection(mediaType),
      { initialProps: { mediaType: "image" as MediaType } },
    );

    act(() => {
      result.current.handleReferenceImageChange({
        target: { files: [file] },
      } as unknown as ChangeEvent<HTMLInputElement>);
    });
    expect(result.current.referenceImageFile).toBe(file);
    expect(result.current.promptImagePreviewUrl).toBe("blob:example");

    rerender({ mediaType: "text" });
    rerender({ mediaType: "image" });

    expect(result.current.referenceImageFile).toBe(file);
    expect(result.current.promptImagePreviewName).toContain("example.png");
  });
});
