import assert from "node:assert/strict";
import test from "node:test";

import {
  CHAT_ATTACHMENT_ACCEPT,
  getAttachmentIconClass,
  isSupportedChatAttachment,
  mergeChatAttachments,
} from "../lib/chat_page/file_attachments";
import type { AttachedFile } from "../lib/chat_page/types";

test("chat attachment accept list includes document formats", () => {
  assert.match(CHAT_ATTACHMENT_ACCEPT, /\.pdf/);
  assert.match(CHAT_ATTACHMENT_ACCEPT, /\.docx/);
  assert.match(CHAT_ATTACHMENT_ACCEPT, /\.xlsx/);
  assert.match(CHAT_ATTACHMENT_ACCEPT, /\.pptx/);
});

test("chat attachment validation allows document extensions", () => {
  assert.equal(isSupportedChatAttachment({ name: "a.pdf", type: "", size: 12 }), true);
  assert.equal(isSupportedChatAttachment({ name: "a.docx", type: "", size: 12 }), true);
  assert.equal(isSupportedChatAttachment({ name: "a.xlsx", type: "", size: 12 }), true);
  assert.equal(isSupportedChatAttachment({ name: "a.pptx", type: "", size: 12 }), true);
  assert.equal(isSupportedChatAttachment({ name: "a.exe", type: "", size: 12 }), false);
});

test("chat attachment merge deduplicates by file name and caps at five", () => {
  const existing: AttachedFile[] = [
    { id: "1", name: "a.txt", size: 1, content: "a" },
    { id: "2", name: "b.txt", size: 1, content: "b" },
    { id: "3", name: "c.txt", size: 1, content: "c" },
    { id: "4", name: "d.txt", size: 1, content: "d" },
  ];
  const additions: AttachedFile[] = [
    { id: "5", name: "a.txt", size: 1, content: "duplicate" },
    { id: "6", name: "e.pdf", size: 1, dataBase64: "QUJD" },
    { id: "7", name: "f.pdf", size: 1, dataBase64: "QUJD" },
  ];

  const merged = mergeChatAttachments(existing, additions);

  assert.deepEqual(
    merged.map((file) => file.name),
    ["a.txt", "b.txt", "c.txt", "d.txt", "e.pdf"],
  );
});

test("chat attachment icons reflect document family", () => {
  assert.equal(getAttachmentIconClass("a.pdf"), "bi-file-earmark-pdf");
  assert.equal(getAttachmentIconClass("a.docx"), "bi-file-earmark-word");
  assert.equal(getAttachmentIconClass("a.xlsx"), "bi-file-earmark-excel");
  assert.equal(getAttachmentIconClass("a.pptx"), "bi-file-earmark-ppt");
});
