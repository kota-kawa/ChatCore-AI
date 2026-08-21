import { memo, useEffect, useState } from "react";

import type { WebSearchImageV1 } from "../../lib/chat_page/types";

type WebSearchImagePartProps = {
  image: WebSearchImageV1;
};

function WebSearchImagePartComponent({ image }: WebSearchImagePartProps) {
  // 読み込めなかった画像は枠ごと消す。404 や hotlink 拒否のとき、代替テキストだけの
  // 空の枠が「画像が無い」ように見えてしまうため、何も出さない方が正しい。
  // Drop the whole frame when the image cannot load. On a 404 or a hotlink refusal
  // an alt-text-only box reads as "there is no image here", so showing nothing is
  // the better outcome.
  const [failed, setFailed] = useState(false);

  // 同じパーツが別の画像へ差し替わったときは、失敗状態を持ち越さない。
  // A new image in the same part must not inherit the previous failure.
  useEffect(() => {
    setFailed(false);
  }, [image.url]);

  if (failed) return null;

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
          onError={() => setFailed(true)}
        />
      </a>
    </figure>
  );
}

export const WebSearchImagePart = memo(WebSearchImagePartComponent);
WebSearchImagePart.displayName = "WebSearchImagePart";
