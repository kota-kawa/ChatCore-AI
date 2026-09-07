import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeChatResponsePayload,
  normalizeChatHistoryMessages,
  normalizeChatHistoryPagination,
  normalizeChatHistoryPayload,
  normalizeChatRoom,
  normalizeChatRooms,
  normalizeChatRoomsPayload,
  normalizeGenerationStatusPayload,
  normalizeShareChatRoomPayload,
} from "../lib/chat_page/api_contract";

test("normalizeChatRoom normalizes incomplete payloads", () => {
  const normalized = normalizeChatRoom({
    id: 123,
    title: "   ",
    mode: "temporary",
    created_at: "2026-01-01T00:00:00Z",
    last_activity_at: "2026-02-01T00:00:00Z",
  });

  assert.deepEqual(normalized, {
    id: "123",
    title: "新規チャット",
    mode: "temporary",
    createdAt: "2026-01-01T00:00:00Z",
    lastActivityAt: "2026-02-01T00:00:00Z",
  });
});

test("normalizeChatRooms drops invalid room entries", () => {
  const normalized = normalizeChatRooms([
    { id: "room-1", title: "Room 1", mode: "normal" },
    null,
    { title: "missing-id" },
  ]);

  assert.equal(normalized.length, 1);
  assert.equal(normalized[0]?.id, "room-1");
});

test("normalizeChatRoomsPayload keeps room pagination", () => {
  const normalized = normalizeChatRoomsPayload({
    rooms: [{ id: "room-1", title: "Room 1", mode: "normal" }],
    pagination: {
      has_more: true,
      next_cursor: "cursor-20",
    },
  });

  assert.equal(normalized.rooms.length, 1);
  assert.deepEqual(normalized.pagination, {
    hasMore: true,
    nextCursor: "cursor-20",
  });
});

test("normalizeChatHistoryMessages keeps known fields only", () => {
  const normalized = normalizeChatHistoryMessages([
    { id: 5, message: "hello", sender: "user", timestamp: "2026-01-01" },
    { id: 0, message: null, sender: 3, timestamp: [] },
  ]);

  assert.deepEqual(normalized, [
    { id: 5, message: "hello", sender: "user", timestamp: "2026-01-01" },
    { id: undefined, message: undefined, sender: undefined, timestamp: undefined },
  ]);
});

test("normalizeChatHistoryPagination validates numeric boundaries", () => {
  const normalized = normalizeChatHistoryPagination({
    has_more: true,
    next_before_id: -10,
  });

  assert.deepEqual(normalized, {
    hasMore: true,
    nextBeforeId: null,
  });
});

test("normalizeChatResponsePayload keeps generated room title", () => {
  const normalized = normalizeChatResponsePayload({
    response: "answer",
    room_title: "Thread title",
  });

  assert.deepEqual(normalized, {
    response: "answer",
    error: undefined,
    roomTitle: "Thread title",
  });
});

test("normalizers keep valid sandbox artifact parts", () => {
  const artifact = {
    version: 1,
    title: "Diagram",
    description: "Interactive view",
    height: 360,
    html: "<div></div>",
    css: "body{margin:0}",
    js: "document.body.textContent = 'ok';",
  };

  const history = normalizeChatHistoryMessages([
    {
      id: 6,
      message: "answer",
      sender: "assistant",
      message_parts: [
        { type: "text", text: "answer" },
        { type: "sandbox_artifact", artifact },
      ],
    },
  ]);
  assert.equal(history[0]?.message_parts?.[1]?.type, "sandbox_artifact");

  const response = normalizeChatResponsePayload({
    response: "answer",
    parts: [{ type: "sandbox_artifact", artifact }],
  });
  assert.equal(response.parts?.[0]?.type, "sandbox_artifact");
});

test("normalizers keep safe web-search image parts", () => {
  const response = normalizeChatResponsePayload({
    response: "answer",
    parts: [
      { type: "text", text: "answer" },
      {
        type: "web_search_image",
        image: {
          url: "https://cdn.example.com/hero.jpg",
          alt: "Relevant photo",
          source_url: "https://example.com/article",
          source_title: "Article",
        },
      },
      {
        type: "web_search_image",
        image: {
          url: "javascript:alert(1)",
          alt: "Unsafe",
          source_url: "https://example.com/article",
        },
      },
    ],
  });

  assert.deepEqual(response.parts, [
    { type: "text", text: "answer" },
    {
      type: "web_search_image",
      image: {
        url: "https://cdn.example.com/hero.jpg",
        alt: "Relevant photo",
        sourceUrl: "https://example.com/article",
        sourceTitle: "Article",
      },
    },
  ]);
});

test("normalizers keep legacy images below the answer trace", () => {
  const trace =
    '<details class="web-search-sources web-search-sources--trace">\n' +
    '<summary class="web-search-sources__summary">' +
    '<span class="web-search-sources__label">回答までのステップ</span>' +
    "</summary>\n" +
    '<div class="web-search-sources__list">' +
    '<details class="web-search-sources__step-details">' +
    '<summary class="web-search-sources__step-summary">step</summary>' +
    "<div>sources</div>" +
    "</details>" +
    "</div>\n" +
    "</details>";
  const image = {
    type: "web_search_image",
    image: {
      url: "https://cdn.example.com/hero.jpg",
      alt: "Relevant photo",
      source_url: "https://example.com/article",
    },
  };

  const response = normalizeChatResponsePayload({
    response: `${trace}\n\nanswer`,
    parts: [image, { type: "text", text: `${trace}\n\nanswer` }],
  });

  assert.deepEqual(response.parts, [
    { type: "text", text: trace },
    {
      type: "web_search_image",
      image: {
        url: "https://cdn.example.com/hero.jpg",
        alt: "Relevant photo",
        sourceUrl: "https://example.com/article",
      },
    },
    { type: "text", text: "answer" },
  ]);
});

test("normalizers keep generated UI and web-search image parts mutually exclusive", () => {
  const artifact = {
    version: 1,
    title: "Diagram",
    html: '<div id="app"></div>',
    css: "#app{padding:12px}",
    js: "document.getElementById('app').textContent = 'ready';",
  };

  const response = normalizeChatResponsePayload({
    response: "answer",
    parts: [
      {
        type: "web_search_image",
        image: {
          url: "https://cdn.example.com/hero.jpg",
          alt: "Relevant photo",
          source_url: "https://example.com/article",
        },
      },
      { type: "text", text: "answer" },
      { type: "sandbox_artifact", artifact },
    ],
  });

  assert.deepEqual(response.parts, [
    { type: "text", text: "answer" },
    { type: "sandbox_artifact", artifact },
  ]);
});

test("normalizers keep the three library declaration and drop unknown ones", () => {
  const artifact = {
    version: 1,
    title: "3D scene",
    height: 460,
    libraries: ["three", "react"],
    html: "<div id='app'></div>",
    css: "#app{height:420px}",
    js: "const scene = new THREE.Scene();",
  };

  const response = normalizeChatResponsePayload({
    response: "answer",
    parts: [{ type: "sandbox_artifact", artifact }],
  });

  const part = response.parts?.[0];
  assert.equal(part?.type, "sandbox_artifact");
  assert.deepEqual(
    part?.type === "sandbox_artifact" ? part.artifact.libraries : undefined,
    ["three"],
  );
});

// 日本語: ここから下は、生成 Zod スキーマ（`types/generated/api_schemas.ts`）へ置き換えた
//         正規化関数が、壊れたペイロードでも従来どおりの既定値へ落ちることを固定するテストです。
// English: The tests below pin the fallback behaviour of the normalizers that now validate through the
//          generated Zod schemas (`types/generated/api_schemas.ts`) when the payload is malformed.

test("normalizeChatHistoryPagination falls back on malformed pagination fields", () => {
  assert.deepEqual(
    normalizeChatHistoryPagination({ has_more: "yes", next_before_id: "12" }),
    { hasMore: false, nextBeforeId: null },
  );
  assert.deepEqual(normalizeChatHistoryPagination(undefined), { hasMore: false, nextBeforeId: null });
  assert.deepEqual(normalizeChatHistoryPagination("not-an-object"), { hasMore: false, nextBeforeId: null });
  assert.deepEqual(normalizeChatHistoryPagination({ has_more: null, next_before_id: null }), {
    hasMore: false,
    nextBeforeId: null,
  });
});

test("normalizeChatHistoryPagination keeps the lenient non-integer cursor behaviour", () => {
  // 日本語: 生成スキーマは整数のみを許すが、従来の正規化は有限の非整数も通していたため互換を保つ。
  // English: The generated schema allows integers only, but the previous normalizer passed finite
  //          non-integers through, so that leniency is preserved.
  assert.deepEqual(normalizeChatHistoryPagination({ has_more: true, next_before_id: 4.5 }), {
    hasMore: true,
    nextBeforeId: 4.5,
  });
  assert.deepEqual(normalizeChatHistoryPagination({ next_before_id: Number.POSITIVE_INFINITY }), {
    hasMore: false,
    nextBeforeId: null,
  });
  assert.deepEqual(normalizeChatHistoryPagination({ next_before_id: Number.NaN }), {
    hasMore: false,
    nextBeforeId: null,
  });
});

test("normalizeChatHistoryMessages falls back for malformed entries", () => {
  assert.deepEqual(normalizeChatHistoryMessages("not-an-array"), []);
  assert.deepEqual(normalizeChatHistoryMessages([null, 7, "x"]), [
    { id: undefined, message: undefined, sender: undefined, timestamp: undefined },
    { id: undefined, message: undefined, sender: undefined, timestamp: undefined },
    { id: undefined, message: undefined, sender: undefined, timestamp: undefined },
  ]);
  assert.deepEqual(
    normalizeChatHistoryMessages([
      {
        id: "5",
        message: { text: "hello" },
        sender: 3,
        timestamp: 20260101,
        message_parts: "broken",
        attached_file_names: "broken",
        sibling_ids: "broken",
        version_index: "broken",
        version_count: 0,
      },
    ]),
    [{ id: undefined, message: undefined, sender: undefined, timestamp: undefined }],
  );
});

test("normalizeChatHistoryMessages keeps good entries next to a malformed sibling", () => {
  const normalized = normalizeChatHistoryMessages([
    { id: 4, message: "kept", sender: "user", timestamp: "2026-01-01" },
    { id: "bad", message: 42 },
  ]);

  assert.equal(normalized.length, 2);
  assert.equal(normalized[0]?.message, "kept");
  assert.equal(normalized[1]?.message, undefined);
});

test("normalizeChatHistoryPayload falls back on malformed payloads", () => {
  assert.deepEqual(normalizeChatHistoryPayload(undefined), {
    error: undefined,
    messages: [],
    pagination: { hasMore: false, nextBeforeId: null },
    roomMode: "normal",
  });
  assert.deepEqual(
    normalizeChatHistoryPayload({
      error: { message: "boom" },
      messages: "broken",
      pagination: "broken",
      room_mode: 7,
    }),
    {
      error: undefined,
      messages: [],
      pagination: { hasMore: false, nextBeforeId: null },
      roomMode: "normal",
    },
  );
});

test("normalizeChatHistoryPayload ignores malformed contract siblings", () => {
  // 日本語: `detail` / `params` / `code` が壊れていても、読み取る項目は落ちない
  //         （生成スキーマをペイロード全体で `parse` していないことの担保）。
  // English: Broken `detail` / `params` / `code` must not drop the fields we read, proving the generated
  //          schema is not applied to the whole payload with `parse`.
  const normalized = normalizeChatHistoryPayload({
    error: "history unavailable",
    detail: 12345,
    params: "broken",
    code: 500,
    messages: [{ id: 9, message: "hello", sender: "assistant", timestamp: "2026-01-01" }],
    pagination: { has_more: true, next_before_id: 3 },
    room_mode: "temporary",
  });

  assert.deepEqual(normalized, {
    error: "history unavailable",
    messages: [{ id: 9, message: "hello", sender: "assistant", timestamp: "2026-01-01" }],
    pagination: { hasMore: true, nextBeforeId: 3 },
    roomMode: "temporary",
  });
});

test("normalizeGenerationStatusPayload falls back on malformed payloads", () => {
  assert.deepEqual(normalizeGenerationStatusPayload(undefined), {
    error: undefined,
    is_generating: false,
    has_replayable_job: false,
  });
  assert.deepEqual(normalizeGenerationStatusPayload([1, 2, 3]), {
    error: undefined,
    is_generating: false,
    has_replayable_job: false,
  });
  assert.deepEqual(
    normalizeGenerationStatusPayload({ error: 500, is_generating: "true", has_replayable_job: 1 }),
    { error: undefined, is_generating: false, has_replayable_job: false },
  );
  assert.deepEqual(
    normalizeGenerationStatusPayload({
      error: "generation failed",
      detail: 12345,
      params: "broken",
      is_generating: true,
      has_replayable_job: false,
    }),
    { error: "generation failed", is_generating: true, has_replayable_job: false },
  );
});

test("normalizeChatResponsePayload falls back on malformed payloads", () => {
  assert.deepEqual(normalizeChatResponsePayload(undefined), {
    response: undefined,
    error: undefined,
    roomTitle: undefined,
  });
  assert.deepEqual(
    normalizeChatResponsePayload({ response: 5, error: {}, room_title: 9, parts: "broken" }),
    { response: undefined, error: undefined, roomTitle: undefined },
  );
  assert.deepEqual(
    normalizeChatResponsePayload({ response: "answer", detail: 12345, params: "broken", code: 200 }),
    { response: "answer", error: undefined, roomTitle: undefined },
  );
});

test("normalizeShareChatRoomPayload falls back on malformed payloads", () => {
  assert.deepEqual(normalizeShareChatRoomPayload(undefined), { shareUrl: undefined });
  assert.deepEqual(normalizeShareChatRoomPayload({ share_url: 42 }), { shareUrl: undefined });
  assert.deepEqual(normalizeShareChatRoomPayload({ share_url: null, detail: 12345 }), {
    shareUrl: undefined,
  });
  assert.deepEqual(
    normalizeShareChatRoomPayload({ share_url: "https://example.com/s/abc", share_token: 5 }),
    { shareUrl: "https://example.com/s/abc" },
  );
});
