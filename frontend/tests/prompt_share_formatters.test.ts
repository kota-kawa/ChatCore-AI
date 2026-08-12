import assert from "node:assert/strict";
import test from "node:test";

import { normalizePromptData } from "../scripts/prompt_share/formatters";
import type { PromptData } from "../scripts/prompt_share/types";

function promptData(overrides: Partial<PromptData> = {}): PromptData {
  return {
    title: "画像生成プロンプト",
    content: "画像を生成してください。",
    ...overrides
  };
}

test("normalizePromptData falls back to a reference attachment and normalizes a relative path", () => {
  const normalized = normalizePromptData(promptData({
    attachments: [
      { url: "  ", role: "reference", media_type: "image" },
      { url: "prompt_share/api/media/example.webp", role: "reference", media_type: "image" }
    ]
  }));

  assert.equal(normalized.reference_image_url, "/prompt_share/api/media/example.webp");
});

test("normalizePromptData prefers the explicit reference image URL", () => {
  const normalized = normalizePromptData(promptData({
    reference_image_url: "/prompt_share/api/media/explicit.png",
    attachments: [
      { url: "/prompt_share/api/media/fallback.png", role: "reference", media_type: "image" }
    ]
  }));

  assert.equal(normalized.reference_image_url, "/prompt_share/api/media/explicit.png");
});

test("normalizePromptData preserves absolute and protocol-relative image URLs", () => {
  const absolute = normalizePromptData(promptData({
    reference_image_url: "https://cdn.example.com/prompts/example.png"
  }));
  const protocolRelative = normalizePromptData(promptData({
    attachments: [
      { url: "//cdn.example.com/prompts/fallback.png", role: "reference", media_type: "image" }
    ]
  }));

  assert.equal(absolute.reference_image_url, "https://cdn.example.com/prompts/example.png");
  assert.equal(protocolRelative.reference_image_url, "//cdn.example.com/prompts/fallback.png");
});

test("normalizePromptData ignores attachments that are not reference media", () => {
  const normalized = normalizePromptData(promptData({
    attachments: [
      { url: "/prompt_share/api/media/non-reference.png", role: "preview", media_type: "image" }
    ]
  }));

  assert.equal(normalized.reference_image_url, "");
});

test("normalizePromptData leaves legacy upload paths unchanged", () => {
  const normalized = normalizePromptData(promptData({
    reference_image_url: "/static/uploads/prompt_share/legacy.png"
  }));

  assert.equal(normalized.reference_image_url, "/static/uploads/prompt_share/legacy.png");
});
