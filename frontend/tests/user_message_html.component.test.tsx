import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { UserMessageHtml } from "../components/chat_page/user_message_html";

describe("UserMessageHtml attached images", () => {
  it("draws image thumbnails and keeps only the documents as name chips", () => {
    const { container } = render(
      <UserMessageHtml
        text="この写真を見て"
        attachedFileNames={["photo.png", "notes.txt"]}
        attachedImages={[{ name: "photo.png", src: "/api/chat/images/abc/thumbnail", width: 640, height: 480 }]}
      />,
    );

    const images = container.querySelectorAll<HTMLImageElement>(".user-message-image");
    expect(images).toHaveLength(1);
    expect(images[0].getAttribute("src")).toBe("/api/chat/images/abc/thumbnail");
    expect(images[0].getAttribute("alt")).toBe("photo.png");
    expect(images[0].getAttribute("width")).toBe("640");
    const chips = Array.from(container.querySelectorAll(".user-message-attachment-chip")).map((chip) => chip.textContent);
    expect(chips).toEqual(["notes.txt"]);
  });

  it("keeps an image name as a chip when no thumbnail is available", () => {
    const { container } = render(<UserMessageHtml text="hi" attachedFileNames={["photo.png"]} />);

    expect(container.querySelector(".user-message-images")).toBeNull();
    expect(container.querySelector(".user-message-attachment-chip")?.textContent).toBe("photo.png");
  });
});
