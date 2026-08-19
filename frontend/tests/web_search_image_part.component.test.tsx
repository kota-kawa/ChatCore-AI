import { render } from "@testing-library/react";
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
    expect(container.querySelector("figcaption")).toHaveTextContent("Article title");
  });
});
