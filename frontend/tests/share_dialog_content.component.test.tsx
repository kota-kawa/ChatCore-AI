import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ShareDialogContent } from "../components/ui/share_dialog_content";

describe("ShareDialogContent", () => {
  it("disables copy, native share, and social destinations until the URL is ready", () => {
    const { container } = render(
      <ShareDialogContent
        shareUrl=""
        shareLoading={true}
        shareStatus={{ text: "Preparing", isError: false }}
        linkInputId="share-url"
        linkPlaceholder="Preparing"
        copyLabel="Copy"
        onCopyLink={vi.fn()}
        socialLinks={{ x: "", line: "", facebook: "" }}
        supportsNativeShare={true}
        nativeShareLabel="Share on device"
        onNativeShare={vi.fn()}
      />,
    );

    expect(container.querySelector("#share-url")).toHaveValue("");
    expect(container.querySelector("button")).toBeDisabled();
    expect(container.querySelectorAll("a")).toHaveLength(3);
    for (const link of container.querySelectorAll("a")) {
      expect(link).not.toHaveAttribute("href");
      expect(link).toHaveAttribute("aria-disabled", "true");
      expect(link).toHaveAttribute("tabindex", "-1");
    }
    expect(container.querySelector("button:last-of-type")).toBeDisabled();
  });

  it("keeps destination IDs, safe target attributes, and URLs once ready", () => {
    const { container } = render(
      <ShareDialogContent
        shareUrl="https://example.com/shared/abc"
        shareLoading={false}
        shareStatus={{ text: "Ready", isError: false }}
        linkInputId="share-url"
        copyButtonId="copy-share"
        linkPlaceholder="Preparing"
        copyLabel="Copy"
        onCopyLink={vi.fn()}
        socialLinks={{
          x: "https://twitter.com/intent/tweet?url=abc",
          line: "https://social-plugins.line.me/lineit/share?url=abc",
          facebook: "https://www.facebook.com/sharer/sharer.php?u=abc",
        }}
        socialLinkIds={{ x: "share-x", line: "share-line", facebook: "share-facebook" }}
        supportsNativeShare={false}
        nativeShareLabel="Share on device"
        onNativeShare={vi.fn()}
      />,
    );

    expect(container.querySelector("#copy-share")).toBeEnabled();
    expect(container.querySelector("#share-x")).toHaveAttribute("href", "https://twitter.com/intent/tweet?url=abc");
    expect(container.querySelector("#share-line")).toHaveAttribute("href", "https://social-plugins.line.me/lineit/share?url=abc");
    expect(container.querySelector("#share-facebook")).toHaveAttribute("href", "https://www.facebook.com/sharer/sharer.php?u=abc");
    for (const link of container.querySelectorAll("a")) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
      expect(link).not.toHaveAttribute("aria-disabled");
    }
  });
});
