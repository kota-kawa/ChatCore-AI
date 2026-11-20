// ホームの初期描画前スクリプトが、チャット画面を先に出すか（セットアップ画面を隠すか）を検証する。
// Tests whether the home bootstrap script boots the chat view (hides the setup view) before hydration.

import assert from "node:assert/strict";
import test from "node:test";

import { homeViewBootstrapScript } from "../pages/_document";
import { STORAGE_KEYS } from "../scripts/core/constants";

const BOOT_ATTRIBUTE = "data-cc-home-boot-view";

// ブートスクリプトは <head> のインラインで動くため、実際にスクリプトを実行して属性が立つかを見る。
// The script runs inline in <head>, so execute it and look at the resulting attribute.
function runBootstrap(options: { pathname?: string; search?: string; stored?: Record<string, string> }) {
  const store = new Map<string, string>(Object.entries(options.stored ?? {}));
  const attributes = new Map<string, string>();
  const context = {
    location: { pathname: options.pathname ?? "/", search: options.search ?? "" },
    localStorage: { getItem: (key: string) => store.get(key) ?? null },
    document: {
      documentElement: {
        setAttribute(name: string, value: string) {
          attributes.set(name, value);
        },
      },
    },
  };

  new Function("location", "localStorage", "document", homeViewBootstrapScript)(
    context.location,
    context.localStorage,
    context.document,
  );

  return attributes.get(BOOT_ATTRIBUTE) ?? null;
}

const LOGGED_IN = { [STORAGE_KEYS.authStateCache]: "1" };

test("home bootstrap boots the chat view when the last view was chat", () => {
  assert.equal(runBootstrap({ stored: { [STORAGE_KEYS.homePageViewState]: "chat" } }), "chat");
});

test("home bootstrap boots the chat view for a room query when the cache says logged in", () => {
  assert.equal(runBootstrap({ search: "?room=1700000000000", stored: LOGGED_IN }), "chat");
  assert.equal(runBootstrap({ search: "?a=1&room=abc", stored: LOGGED_IN }), "chat");
  assert.equal(runBootstrap({ pathname: "/en", search: "?room=abc", stored: LOGGED_IN }), "chat");
});

test("home bootstrap ignores the room query for guests, unknown auth, empty values and other parameters", () => {
  assert.equal(runBootstrap({ search: "?room=abc", stored: { [STORAGE_KEYS.authStateCache]: "0" } }), null);
  assert.equal(runBootstrap({ search: "?room=abc" }), null);
  assert.equal(runBootstrap({ search: "?room=", stored: LOGGED_IN }), null);
  assert.equal(runBootstrap({ search: "?room=%20%20&a=1", stored: LOGGED_IN }), null);
  assert.equal(runBootstrap({ search: "?room=+", stored: LOGGED_IN }), null);
  assert.equal(runBootstrap({ search: "?room=%20x", stored: LOGGED_IN }), "chat");
  assert.equal(runBootstrap({ search: "?chatroom=abc", stored: LOGGED_IN }), null);
});

test("home bootstrap does nothing outside the home page", () => {
  assert.equal(runBootstrap({ pathname: "/memo", search: "?room=abc", stored: LOGGED_IN }), null);
});

test("home bootstrap reads the shared storage keys", () => {
  assert.ok(homeViewBootstrapScript.includes(`'${STORAGE_KEYS.homePageViewState}'`));
  assert.ok(homeViewBootstrapScript.includes(`'${STORAGE_KEYS.authStateCache}'`));
});
