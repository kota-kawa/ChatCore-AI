import assert from "node:assert/strict";
import test from "node:test";

import {
  buildSocialShareLinks,
  shareWithNativeSheet,
} from "../lib/share";

test("buildSocialShareLinks returns empty, non-focusable destinations without a URL", () => {
  assert.deepEqual(buildSocialShareLinks("   ", "Shared"), {
    x: "",
    line: "",
    facebook: "",
  });
});
test("buildSocialShareLinks encodes the URL and optional X text consistently", () => {
  const links = buildSocialShareLinks("https://example.com/shared?a=1&b=2", "共有しました。 & done");
  assert.match(links.x, /url=https%3A%2F%2Fexample.com%2Fshared%3Fa%3D1%26b%3D2/);
  assert.match(links.x, /text=%E5%85%B1%E6%9C%89%E3%81%97%E3%81%BE%E3%81%97%E3%81%9F%E3%80%82%20%26%20done/);
  assert.match(links.line, /url=https%3A%2F%2Fexample.com%2Fshared%3Fa%3D1%26b%3D2/);
  assert.match(links.facebook, /u=https%3A%2F%2Fexample.com%2Fshared%3Fa%3D1%26b%3D2/);
});

test("shareWithNativeSheet normalizes success, cancellation, and failure", async () => {
  const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  const share = async () => undefined;
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: { share } });
  assert.deepEqual(await shareWithNativeSheet({ url: "https://example.com" }), { status: "shared" });

  const cancelled = Object.assign(new Error("cancelled"), { name: "AbortError" });
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { share: async () => { throw cancelled; } },
  });
  assert.deepEqual(await shareWithNativeSheet({ url: "https://example.com" }), { status: "cancelled" });

  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { share: async () => { throw new Error("denied"); } },
  });
  const failed = await shareWithNativeSheet({ url: "https://example.com" });
  assert.equal(failed.status, "failed");
  assert.equal(failed.error instanceof Error ? failed.error.message : "", "denied");

  if (originalNavigator) {
    Object.defineProperty(globalThis, "navigator", originalNavigator);
  } else {
    delete (globalThis as { navigator?: unknown }).navigator;
  }
});
