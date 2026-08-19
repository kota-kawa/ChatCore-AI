import { memo } from "react";

import type { WebSearchImageV1 } from "../../lib/chat_page/types";

type WebSearchImagePartProps = {
  image: WebSearchImageV1;
};

function WebSearchImagePartComponent({ image }: WebSearchImagePartProps) {
  return (
    <figure className="web-search-image-part">
      <a
        className="web-search-image-part__link"
        href={image.sourceUrl}
        target="_blank"
        rel="noopener noreferrer"
        title={image.sourceTitle || undefined}
      >
        <img
          className="web-search-image-part__image"
          src={image.url}
          alt={image.alt}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
        />
      </a>
    </figure>
  );
}

export const WebSearchImagePart = memo(WebSearchImagePartComponent);
WebSearchImagePart.displayName = "WebSearchImagePart";
