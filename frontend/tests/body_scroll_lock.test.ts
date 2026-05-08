import assert from "node:assert/strict";
import test from "node:test";

import { acquireBodyScrollLock } from "../scripts/core/body_scroll_lock";

function installFakeDom(initialOverflow = "") {
  const fakeBody = {
    style: {
      overflow: initialOverflow,
    },
  };

  Object.defineProperty(globalThis, "window", {
    value: {},
    configurable: true,
  });
  Object.defineProperty(globalThis, "document", {
    value: {
      body: fakeBody,
    },
    configurable: true,
  });

  return fakeBody;
}

test("acquireBodyScrollLock restores overflow after all locks release", () => {
  const body = installFakeDom("auto");

  const releaseFirst = acquireBodyScrollLock();
  const releaseSecond = acquireBodyScrollLock();

  assert.equal(body.style.overflow, "hidden");

  releaseFirst();
  assert.equal(body.style.overflow, "hidden");

  releaseSecond();
  assert.equal(body.style.overflow, "auto");
});

test("acquireBodyScrollLock releases idempotently", () => {
  const body = installFakeDom("");
  const release = acquireBodyScrollLock();

  release();
  release();

  assert.equal(body.style.overflow, "");
});
