import assert from "node:assert/strict";
import test from "node:test";

import {
  hasImageAttachments,
  modelAcceptsImageInput,
  toBubbleImagesFromAttachments,
  toBubbleImagesFromHistory,
} from "../lib/chat_page/chat_images";
import { normalizeChatHistoryMessages } from "../lib/chat_page/api_contract";

const IMAGE_ID = "0123456789abcdef".repeat(3);

test("only GPT-6 Luna reads images", () => {
  assert.equal(modelAcceptsImageInput("gpt-6-luna"), true);
  assert.equal(modelAcceptsImageInput("openai/gpt-oss-120b"), false);
  assert.equal(modelAcceptsImageInput("qwen/qwen3.8-27b"), false);
});

test("image attachments are detected by file name", () => {
  assert.equal(hasImageAttachments([{ id: "1", name: "notes.txt", size: 1 }]), false);
  assert.equal(hasImageAttachments([{ id: "1", name: "notes.txt", size: 1 }, { id: "2", name: "a.WEBP", size: 1 }]), true);
});

test("a just-sent bubble uses the local previews of image attachments", () => {
  const images = toBubbleImagesFromAttachments([
    { id: "1", name: "notes.txt", size: 1, content: "x" },
    { id: "2", name: "photo.png", size: 1, previewUrl: "data:image/webp;base64,AA==" },
  ]);
  assert.deepEqual(images, [{ name: "photo.png", src: "data:image/webp;base64,AA==" }]);
  assert.equal(toBubbleImagesFromAttachments([{ id: "1", name: "notes.txt", size: 1 }]), undefined);
});

test("history images point at the private thumbnail route", () => {
  assert.deepEqual(toBubbleImagesFromHistory([{ id: IMAGE_ID, name: "photo.png", width: 640, height: 0 }]), [
    { name: "photo.png", src: `/api/chat/images/${IMAGE_ID}/thumbnail`, width: 640, height: undefined },
  ]);
});

test("history payload keeps only well-formed image references", () => {
  const [message] = normalizeChatHistoryMessages([
    {
      id: 1,
      message: "hi",
      sender: "user",
      timestamp: "",
      attached_images: [
        { id: IMAGE_ID, name: "photo.png", width: 10, height: 20 },
        { id: "../escape", name: "bad.png", width: 1, height: 1 },
        "junk",
      ],
    },
  ]);
  assert.deepEqual(message.attached_images, [{ id: IMAGE_ID, name: "photo.png", width: 10, height: 20 }]);
});
