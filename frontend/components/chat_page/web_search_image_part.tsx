// Web 検索で得た画像を、出典リンク付きの図としてチャットの回答内に表示するコンポーネント。bot_message_parts.tsx と共有チャットから使われる。
// Component that shows an image found by web search inside a chat answer as a figure linked to its source.
import { memo, useEffect, useState } from "react";

import type { WebSearchImageV1 } from "../../lib/chat_page/types";

type WebSearchImagePartProps = {
  image: WebSearchImageV1;
};

// 検索画像1枚を出典ページへのリンク付きで表示する。読み込みに失敗したら何も描画しない。
// Renders one search image linked to its source page; renders nothing if the image fails to load.
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
          // 画像の配信元へ、閲覧元ページの URL を Referer として送らない。
          // Do not send the viewing page's URL to the image host as a Referer.
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      </a>
    </figure>
  );
}

export const WebSearchImagePart = memo(WebSearchImagePartComponent);
WebSearchImagePart.displayName = "WebSearchImagePart";
