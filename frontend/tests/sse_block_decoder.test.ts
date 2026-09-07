import assert from "node:assert/strict";
import test from "node:test";

import { createSseBlockDecoder } from "../lib/chat_page/sse_block_decoder";

const encoder = new TextEncoder();

function encode(text: string) {
  return encoder.encode(text);
}

test("createSseBlockDecoder returns only blocks that are already closed", () => {
  const decoder = createSseBlockDecoder(new TextDecoder());

  const blocks = decoder.push(encode("event: chunk\ndata: {}\n\nevent: done\ndata: {}"), false);

  assert.deepEqual(blocks, ["event: chunk\ndata: {}"]);
  assert.equal(decoder.pending, "event: done\ndata: {}");
});

test("createSseBlockDecoder joins a block split across reads", () => {
  const decoder = createSseBlockDecoder(new TextDecoder());

  assert.deepEqual(decoder.push(encode("event: ch"), false), []);
  assert.deepEqual(decoder.push(encode("unk\ndata: {\"text\":\"ab\"}"), false), []);
  assert.deepEqual(decoder.push(encode("\n\n"), false), ['event: chunk\ndata: {"text":"ab"}']);
});

test("createSseBlockDecoder accepts CRLF separators", () => {
  const decoder = createSseBlockDecoder(new TextDecoder());

  const blocks = decoder.push(encode("event: a\r\ndata: 1\r\n\r\nevent: b\r\ndata: 2\r\n\r\n"), true);

  assert.deepEqual(blocks, ["event: a\r\ndata: 1", "event: b\r\ndata: 2"]);
  assert.equal(decoder.pending, "");
});

// マルチバイト文字がチャンク境界で割れても文字化けさせない。
// A multibyte character split across chunk boundaries must not be mangled.
test("createSseBlockDecoder keeps a UTF-8 character split across two reads intact", () => {
  const decoder = createSseBlockDecoder(new TextDecoder());
  const payload = encode('data: {"text":"日本語"}\n\n');
  const cut = 12; // 「日」の途中で切る / cuts inside the first Japanese character

  assert.deepEqual(decoder.push(payload.slice(0, cut), false), []);
  const blocks = decoder.push(payload.slice(cut), false);

  assert.deepEqual(blocks, ['data: {"text":"日本語"}']);
});

// 再接続をまたいで TextDecoder を共有し、行バッファだけを作り直す運用を確かめる。
// The TextDecoder is shared across reconnects while only the buffer is recreated.
test("createSseBlockDecoder starts a fresh buffer per response", () => {
  const textDecoder = new TextDecoder();
  const first = createSseBlockDecoder(textDecoder);
  first.push(encode("event: chunk\ndata: {}"), false);

  const second = createSseBlockDecoder(textDecoder);

  assert.equal(second.pending, "");
  assert.deepEqual(second.push(encode("event: done\ndata: {}\n\n"), true), ["event: done\ndata: {}"]);
});

test("createSseBlockDecoder tolerates a read with no bytes", () => {
  const decoder = createSseBlockDecoder(new TextDecoder());

  assert.deepEqual(decoder.push(undefined, true), []);
  assert.equal(decoder.pending, "");
});
