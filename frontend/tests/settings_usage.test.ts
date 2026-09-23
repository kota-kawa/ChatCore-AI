import assert from "node:assert/strict";
import test from "node:test";

import { parseSettingsSection } from "../scripts/user/settings/section_url";
import { formatUsageResetTime, usagePercent } from "../scripts/user/settings/usage";

test("usage percent never reads 100% before the limit is reached", () => {
  assert.equal(usagePercent(0), 0);
  assert.equal(usagePercent(-1), 0);
  assert.equal(usagePercent(Number.NaN), 0);
  assert.equal(usagePercent(0.424), 42);
  assert.equal(usagePercent(0.999), 99);
  assert.equal(usagePercent(1), 100);
});

test("reset times are shown in Japan time regardless of the viewer's zone", () => {
  // 2026-09-24T00:00+09:00 is 2026-09-23T15:00Z.
  assert.equal(formatUsageResetTime("2026-09-23T15:00:00+00:00", "ja"), "9月24日(木) 0:00");
  assert.equal(formatUsageResetTime("2026-09-24T00:00:00+09:00", "en"), "Thu, Sep 24, 12:00 AM");
  assert.equal(formatUsageResetTime("not a date", "ja"), "");
});

test("the usage section can be opened from the URL", () => {
  assert.equal(parseSettingsSection("usage"), "usage");
});
