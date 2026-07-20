import assert from "node:assert/strict";
import test from "node:test";

import { authBootstrapScript } from "../pages/_document";
import { STORAGE_KEYS } from "../scripts/core/constants";

// ブートスクリプトは <head> でインライン実行されるため、モジュールを import できず
// localStorage のキーを文字列リテラルで持つ。定数側とずれると無言で無効化されるので、
// 実際にスクリプトを実行して属性が立つことまで検証する。
// The bootstrap script runs inline in <head>, so it cannot import modules and
// hardcodes the localStorage key. A drift from the constant would silently
// disable it, so we execute the script and assert the resulting attribute.
function runBootstrap(storedValue: string | null) {
  const store = new Map<string, string>();
  if (storedValue !== null) {
    store.set(STORAGE_KEYS.authStateCache, storedValue);
  }

  const attributes = new Map<string, string>();
  const documentElement = {
    setAttribute(name: string, value: string) {
      attributes.set(name, value);
    },
  };

  const context = {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
    },
    document: { documentElement },
  };

  new Function("window", "localStorage", "document", authBootstrapScript)(
    context,
    context.localStorage,
    context.document,
  );

  return attributes.get("data-cc-auth") ?? null;
}

test("auth bootstrap marks the document as logged in from the cached state", () => {
  assert.equal(runBootstrap("1"), "in");
});

test("auth bootstrap marks the document as logged out from the cached state", () => {
  assert.equal(runBootstrap("0"), "out");
});

test("auth bootstrap stays neutral when no usable cached state exists", () => {
  assert.equal(runBootstrap(null), null);
  assert.equal(runBootstrap(""), null);
  assert.equal(runBootstrap("true"), null);
});

test("auth bootstrap reads the shared auth cache storage key", () => {
  assert.ok(
    authBootstrapScript.includes(`'${STORAGE_KEYS.authStateCache}'`),
    "bootstrap script must read STORAGE_KEYS.authStateCache",
  );
});
