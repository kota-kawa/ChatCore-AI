// ルームを開く URL の組み立てと、room クエリの取り込み（読み取りと URL からの除去）を検証する。
// Tests building the open-room URL and consuming the room query (reading it and stripping it from the URL).

import { beforeEach, describe, expect, it } from "vitest";

import { buildHomeRoomUrl, consumeRoomIdFromUrl } from "../lib/chat_page/room_url";

function setUrl(url: string, state: unknown = null) {
  window.history.replaceState(state, "", url);
}

function currentUrl() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

describe("buildHomeRoomUrl", () => {
  it("encodes the client-generated room id so it round-trips through the query", () => {
    for (const roomId of ["1700000000000", "room a/b?c&d=e#f", "日本語のルーム", "100%"]) {
      const url = buildHomeRoomUrl(roomId);
      expect(url.startsWith("/?room=")).toBe(true);
      expect(new URL(url, "http://localhost").searchParams.get("room")).toBe(roomId);
    }
  });
});

describe("consumeRoomIdFromUrl", () => {
  beforeEach(() => {
    setUrl("/");
  });

  it("returns the room id and removes only the room query, keeping other parameters and the hash", () => {
    setUrl("/?a=1&room=1700000000000&b=2#section");
    expect(consumeRoomIdFromUrl()).toBe("1700000000000");
    expect(currentUrl()).toBe("/?a=1&b=2#section");
  });

  it("decodes an id built by buildHomeRoomUrl", () => {
    setUrl(buildHomeRoomUrl("room a/b?c&d=e#f"));
    expect(consumeRoomIdFromUrl()).toBe("room a/b?c&d=e#f");
    expect(currentUrl()).toBe("/");
  });

  it("returns null and leaves the URL alone when there is no room query", () => {
    setUrl("/?a=1#x");
    expect(consumeRoomIdFromUrl()).toBeNull();
    expect(currentUrl()).toBe("/?a=1#x");
  });

  it("ignores empty, whitespace-only, over-long, control-character and malformed values but still strips them", () => {
    const unusable = ["", "%20%20", "a".repeat(129), "abc%00def", "%E0%A4%A"];
    for (const value of unusable) {
      setUrl(`/?room=${value}&keep=1`);
      expect(consumeRoomIdFromUrl()).toBeNull();
      expect(currentUrl()).toBe("/?keep=1");
    }
  });

  it("accepts an id of exactly the maximum length", () => {
    const roomId = "a".repeat(128);
    setUrl(`/?room=${roomId}`);
    expect(consumeRoomIdFromUrl()).toBe(roomId);
  });

  it("uses the first value when room is repeated and strips every occurrence", () => {
    setUrl("/en?room=first&room=second");
    expect(consumeRoomIdFromUrl()).toBe("first");
    expect(currentUrl()).toBe("/en");
  });

  it("keeps history.state so the Next.js router can still handle back navigation", () => {
    const state = { __N: true, url: "/", as: "/?room=abc", options: {}, key: "k1" };
    setUrl("/?room=abc", state);
    consumeRoomIdFromUrl();
    expect(window.history.state).toEqual(state);
  });
});
