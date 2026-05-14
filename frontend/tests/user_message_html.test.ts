import assert from "node:assert/strict";
import test from "node:test";

import { formatUserInputForDisplay } from "../scripts/chat/chat_ui";

test("formatUserInputForDisplay does not render raw user HTML", () => {
  const html = formatUserInputForDisplay('<img src=x onerror=alert(1)> **hello**');

  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(html, /<img/i);
  assert.match(html, /<strong>hello<\/strong>/);
});
