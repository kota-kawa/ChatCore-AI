import assert from "node:assert/strict";
import test from "node:test";

import { formatDate, formatDateTime } from "../lib/datetime";

// サーバーのTZが何であっても同じ文字列を返すことを確認する。
// ここがずれると SSR とブラウザで表示が変わり、React のハイドレーション不一致
// （React error #418 / #425）になる。
// Verify the output is identical whatever the process TZ is. A difference here changes
// the SSR output versus the browser and breaks hydration (React error #418 / #425).
function withTimeZone<T>(timeZone: string, run: () => T): T {
  const previous = process.env.TZ;
  process.env.TZ = timeZone;
  try {
    return run();
  } finally {
    if (previous === undefined) {
      delete process.env.TZ;
    } else {
      process.env.TZ = previous;
    }
  }
}

test("formatDateTime does not depend on the ambient time zone", () => {
  const value = "2026-08-04T16:05:00Z";
  const utc = withTimeZone("UTC", () => formatDateTime(value));
  const tokyo = withTimeZone("Asia/Tokyo", () => formatDateTime(value));
  const newYork = withTimeZone("America/New_York", () => formatDateTime(value));

  assert.equal(utc, tokyo);
  assert.equal(utc, newYork);
  // 表示は日本時間で固定する / The displayed value is pinned to Japan time
  assert.match(tokyo, /2026\/08\/05 01:05/);
});

test("formatDateTime treats offset-less database timestamps as UTC", () => {
  // PostgreSQL の TIMESTAMP はオフセットなしで直列化される。new Date() に直接渡すと
  // サーバーとブラウザのローカルTZで解釈が変わり、共有ページの hydration が失敗する。
  // PostgreSQL TIMESTAMP values are serialized without an offset. Passing one directly
  // to new Date() changes its meaning with the runtime TZ and breaks shared-page hydration.
  const value = "2026-08-04T16:05:00";
  const utc = withTimeZone("UTC", () => formatDateTime(value));
  const tokyo = withTimeZone("Asia/Tokyo", () => formatDateTime(value));
  const newYork = withTimeZone("America/New_York", () => formatDateTime(value));

  assert.equal(utc, tokyo);
  assert.equal(utc, newYork);
  assert.match(utc, /2026\/08\/05 01:05/);
});

test("formatDateTime preserves an explicit timestamp offset", () => {
  const value = "2026-08-05T01:05:00+09:00";
  const utc = withTimeZone("UTC", () => formatDateTime(value));
  const newYork = withTimeZone("America/New_York", () => formatDateTime(value));

  assert.equal(utc, newYork);
  assert.match(utc, /2026\/08\/05 01:05/);
});

test("formatDate does not depend on the ambient time zone", () => {
  const value = "2026-08-04T16:05:00Z";
  const utc = withTimeZone("UTC", () => formatDate(value));
  const tokyo = withTimeZone("Asia/Tokyo", () => formatDate(value));

  assert.equal(utc, tokyo);
  assert.match(tokyo, /2026\/08\/05/);
});

test("invalid or empty values still render as an empty string", () => {
  assert.equal(formatDateTime(""), "");
  assert.equal(formatDateTime("not-a-date"), "");
  assert.equal(formatDate(null), "");
});
