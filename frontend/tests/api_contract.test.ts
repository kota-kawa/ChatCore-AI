import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeChatResponsePayload,
  normalizeChatHistoryMessages,
  normalizeChatHistoryPagination,
  normalizeChatRoom,
  normalizeChatRooms,
  normalizeChatRoomsPayload,
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
