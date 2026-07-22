import { describe, expect, it } from "vitest";

import { moveFocusOutOfHiddenRegion } from "../lib/chat_page/focus_management";

describe("moveFocusOutOfHiddenRegion", () => {
  it("moves focus to the fallback before its region is hidden", () => {
    const region = document.createElement("div");
    const focusedChild = document.createElement("button");
    const fallback = document.createElement("button");
    region.append(focusedChild);
    document.body.append(region, fallback);

    try {
      focusedChild.focus();
      moveFocusOutOfHiddenRegion(region, fallback);
      region.setAttribute("aria-hidden", "true");

      expect(fallback).toHaveFocus();
      expect(region).toHaveAttribute("aria-hidden", "true");
    } finally {
      region.remove();
      fallback.remove();
    }
  });
});
