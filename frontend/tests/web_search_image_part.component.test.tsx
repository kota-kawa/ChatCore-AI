import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WebSearchImagePart } from "../components/chat_page/web_search_image_part";

describe("WebSearchImagePart", () => {
  it("renders the selected site image and links back to its source page", () => {
    const { container } = render(
      <WebSearchImagePart
        image={{
          url: "https://cdn.example.com/hero.jpg",
          alt: "Relevant photo",
          sourceUrl: "https://example.com/article",
          sourceTitle: "Article title",
        }}
      />,
    );

    const image = container.querySelector<HTMLImageElement>(".web-search-image-part__image");
    const link = container.querySelector<HTMLAnchorElement>(".web-search-image-part__link");

    expect(image?.getAttribute("src")).toBe("https://cdn.example.com/hero.jpg");
    expect(image?.getAttribute("alt")).toBe("Relevant photo");
    expect(image?.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(link?.getAttribute("href")).toBe("https://example.com/article");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link?.getAttribute("title")).toBe("Article title");
    expect(container.querySelector("figcaption")).toBeNull();
  });

  it("renders nothing when the image fails to load", () => {
    const { container } = render(
      <WebSearchImagePart
        image={{
          url: "https://cdn.example.com/missing.jpg",
          alt: "Relevant photo",
          sourceUrl: "https://example.com/article",
        }}
      />,
    );

    const image = container.querySelector<HTMLImageElement>(".web-search-image-part__image");
    expect(image).not.toBeNull();

    fireEvent.error(image!);

    // 壊れた画像の代替テキストだけの枠は「画像が無い」ように見えるため、枠ごと消す。
    // An alt-text-only frame reads as "no image here", so the frame is removed.
    expect(container.querySelector(".web-search-image-part")).toBeNull();
    expect(container.innerHTML).toBe("");
  });
});
