import assert from "node:assert/strict";
import test from "node:test";

import {
  buildPromptCreateFormData,
  containsGuestPostUrl
} from "../scripts/prompt_share/guest_post";

test("guest prompt payload always uses the text-only contract", () => {
  const formData = buildPromptCreateFormData({
    isGuest: true,
    title: "議事録の要約",
    category: "business",
    content: "以下の議事録を要約してください。",
    description: "会議後の要点整理に使うプロンプト",
    contentFormat: "skill",
    mediaType: "image",
    inputExamples: "入力例",
    outputExamples: "出力例",
    aiModel: "ChatGPT",
    attributes: { skill_markdown: "# hidden" },
    resources: [{ path: "helper.py", role: "script", content: "print('hidden')" }],
    referenceImageFile: new File(["image"], "example.png", { type: "image/png" })
  });

  assert.equal(formData.get("title"), "議事録の要約");
  assert.equal(formData.get("content"), "以下の議事録を要約してください。");
  assert.equal(formData.get("description"), "会議後の要点整理に使うプロンプト");
  assert.equal(formData.get("content_format"), "prompt");
  assert.equal(formData.get("media_type"), "text");
  assert.equal(formData.get("category"), "");
  assert.equal(formData.get("input_examples"), "");
  assert.equal(formData.get("output_examples"), "");
  assert.equal(formData.get("ai_model"), "");
  assert.deepEqual(JSON.parse(String(formData.get("attributes"))), {});
  assert.deepEqual(JSON.parse(String(formData.get("resources"))), []);
  assert.equal(formData.get("reference_image"), null);
});

test("signed-in prompt payload preserves the selected type and optional fields", () => {
  const referenceImageFile = new File(["image"], "example.png", { type: "image/png" });
  const formData = buildPromptCreateFormData({
    isGuest: false,
    title: "画像プロンプト",
    category: "creative",
    content: "夜の都市",
    description: "夜景の画像生成に使うプロンプト",
    contentFormat: "prompt",
    mediaType: "image",
    inputExamples: "",
    outputExamples: "",
    aiModel: "Midjourney",
    attributes: {},
    resources: [],
    referenceImageFile
  });

  assert.equal(formData.get("content_format"), "prompt");
  assert.equal(formData.get("media_type"), "image");
  assert.equal(formData.get("category"), "creative");
  assert.equal(formData.get("ai_model"), "Midjourney");
  assert.equal(formData.get("description"), "夜景の画像生成に使うプロンプト");
  assert.equal(formData.get("reference_image"), referenceImageFile);
});

test("guest URL detection catches common web links without rejecting ordinary text", () => {
  assert.equal(containsGuestPostUrl("https://example.com"), true);
  assert.equal(containsGuestPostUrl("See www.example.com for details"), true);
  assert.equal(containsGuestPostUrl("URLを含まない通常のテキスト"), false);
});
