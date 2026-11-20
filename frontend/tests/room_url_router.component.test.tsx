// Next.js のルーターが動いているとき、room クエリの除去がルーター経由（shallow）で行われ、router.asPath と履歴の state に room が残らないことを検証する。
// Tests that, with the Next.js router running, the room query is removed through the router (shallow) so neither router.asPath nor the history state keeps it.

import { beforeEach, describe, expect, it, vi } from "vitest";

const routerMock = vi.hoisted(() => ({
  router: {} as object | null,
  asPath: "/",
  replace: vi.fn(async () => true),
}));

vi.mock("next/router", () => ({ default: routerMock }));

import { consumeRoomIdFromUrl } from "../lib/chat_page/room_url";

describe("consumeRoomIdFromUrl with the Next.js router", () => {
  beforeEach(() => {
    routerMock.router = {};
    routerMock.replace.mockClear();
    window.history.replaceState(null, "", "/");
  });

  it("removes only room through a shallow router.replace based on router.asPath, keeping other parameters and the hash", () => {
    routerMock.asPath = "/?a=1&room=abc&b=2#section";
    window.history.replaceState(null, "", routerMock.asPath);

    expect(consumeRoomIdFromUrl()).toBe("abc");

    expect(routerMock.replace).toHaveBeenCalledTimes(1);
    expect(routerMock.replace).toHaveBeenCalledWith("/?a=1&b=2#section", undefined, { shallow: true, scroll: false });
  });

  it("returns an unusable value as null but still removes it", () => {
    routerMock.asPath = "/?room=%20";
    window.history.replaceState(null, "", routerMock.asPath);

    expect(consumeRoomIdFromUrl()).toBeNull();
    expect(routerMock.replace).toHaveBeenCalledWith("/", undefined, { shallow: true, scroll: false });
  });

  it("does not touch the router when there is no room query", () => {
    routerMock.asPath = "/?a=1";
    window.history.replaceState(null, "", routerMock.asPath);

    expect(consumeRoomIdFromUrl()).toBeNull();
    expect(routerMock.replace).not.toHaveBeenCalled();
  });

  it("falls back to history.replaceState when the router is not running", () => {
    routerMock.router = null;
    window.history.replaceState(null, "", "/?room=abc&keep=1");

    expect(consumeRoomIdFromUrl()).toBe("abc");
    expect(routerMock.replace).not.toHaveBeenCalled();
    expect(`${window.location.pathname}${window.location.search}`).toBe("/?keep=1");
  });
});
