import assert from "node:assert/strict";
import test from "node:test";

import {
  CHAT_ATTACHMENT_ACCEPT,
  getAttachmentIconClass,
  isSupportedChatAttachment,
  mergeChatAttachments,
  MAX_ATTACHMENT_NAME_LENGTH,
  MAX_ATTACHMENT_TEXT_LENGTH,
  readSelectedChatAttachments,
} from "../lib/chat_page/file_attachments";
import type { AttachedFile } from "../lib/chat_page/types";

// Node にはブラウザの FileReader が無いので、File/Blob が持つ .text() /
// .arrayBuffer() を土台にした最小限の互換実装を用意する。
// Node has no browser FileReader, so provide a minimal shim built on the
// .text()/.arrayBuffer() that File/Blob already expose.
class FakeFileReader {
  public result: string | ArrayBuffer | null = null;
  public onload: ((event: { target: { result: string | ArrayBuffer | null } }) => void) | null = null;
  public onerror: (() => void) | null = null;

  readAsText(file: Blob) {
    file
      .text()
      .then((text) => {
        this.result = text;
        this.onload?.({ target: { result: this.result } });
      })
      .catch(() => this.onerror?.());
  }

  readAsDataURL(file: Blob) {
    file
      .arrayBuffer()
      .then((buffer) => {
        const base64 = Buffer.from(buffer).toString("base64");
        this.result = `data:${file.type || "application/octet-stream"};base64,${base64}`;
        this.onload?.({ target: { result: this.result } });
      })
      .catch(() => this.onerror?.());
  }
}

(globalThis as unknown as { FileReader: typeof FakeFileReader }).FileReader = FakeFileReader;

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

// バグ4: フロントの上限はバイト数だけだったため、1MB未満でも文字数が
// バックエンドの上限(services/attached_files.py の
// MAX_ATTACHED_FILE_CONTENT_LENGTH = 100,000)を超えるファイルを通してしまい、
// /api/chat が ValidationError になって無関係な400だけが表示されていた。
// Bug 4: the frontend only capped bytes, so a file under 1MB whose character
// count exceeded the backend limit (MAX_ATTACHED_FILE_CONTENT_LENGTH = 100,000
// in services/attached_files.py) slipped through, and /api/chat failed
// validation with an unrelated 400.
test("readSelectedChatAttachments rejects text content over the backend's character limit", async () => {
  // 1バイト文字を並べているので、1MB制限は超えないが文字数制限は超える。
  // Single-byte characters keep it under the 1MB cap while exceeding the character cap.
  const oversizedContent = "a".repeat(MAX_ATTACHMENT_TEXT_LENGTH + 1);
  const file = new File([oversizedContent], "big.log", { type: "text/plain" });
  assert.ok(file.size < 1_048_576);

  const errors: string[] = [];
  const selected = await readSelectedChatAttachments([file], [], (message) => errors.push(message));

  assert.deepEqual(selected, []);
  assert.equal(errors.length, 1);
  assert.match(errors[0], /10万文字を超える/);
});

test("readSelectedChatAttachments accepts text content exactly at the backend's character limit", async () => {
  const content = "a".repeat(MAX_ATTACHMENT_TEXT_LENGTH);
  const file = new File([content], "ok.log", { type: "text/plain" });

  const errors: string[] = [];
  const selected = await readSelectedChatAttachments([file], [], (message) => errors.push(message));

  assert.equal(errors.length, 0);
  assert.equal(selected.length, 1);
  assert.equal(selected[0].content?.length, MAX_ATTACHMENT_TEXT_LENGTH);
});

test("readSelectedChatAttachments rejects file names over the backend's length limit", async () => {
  const longName = `${"a".repeat(MAX_ATTACHMENT_NAME_LENGTH + 1)}.txt`;
  const file = new File(["short content"], longName, { type: "text/plain" });

  const errors: string[] = [];
  const selected = await readSelectedChatAttachments([file], [], (message) => errors.push(message));

  assert.deepEqual(selected, []);
  assert.equal(errors.length, 1);
  assert.match(errors[0], /ファイル名が256文字を超える/);
});
