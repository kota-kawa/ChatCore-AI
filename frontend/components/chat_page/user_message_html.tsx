import { memo, useMemo } from "react";

import type { ChatAttachedImage } from "../../lib/chat_page/types";
import { formatUserInputForDisplay } from "../../scripts/chat/chat_ui";

// ユーザーメッセージHTML表示のprops型定義
// Props type definition for the user message HTML display
type UserMessageHtmlProps = {
  text: string;
  attachedFileNames?: string[];
  attachedImages?: ChatAttachedImage[];
};

// ユーザーのメッセージとファイル添付を表示するコンポーネント
// Component that displays the user's message and attached files
function UserMessageHtmlComponent({ text, attachedFileNames, attachedImages }: UserMessageHtmlProps) {
  // formatUserInputForDisplay escapes the fallback path and sanitizes marked HTML
  // before returning it, so dangerouslySetInnerHTML is limited to safe markup.
  const formatted = useMemo(() => formatUserInputForDisplay(text), [text]);
  // サムネイルで出した画像は、名前のチップから外す。
  // Images already shown as thumbnails are left out of the name chips.
  const documentNames = useMemo(() => {
    const imageNames = new Set((attachedImages ?? []).map((image) => image.name));
    return (attachedFileNames ?? []).filter((name) => !imageNames.has(name));
  }, [attachedFileNames, attachedImages]);

  return (
    <>
      {/* 添付画像のサムネイル（画像がある場合のみ） / Attached image thumbnails (shown only when images are attached) */}
      {attachedImages && attachedImages.length > 0 && (
        <div className="user-message-images">
          {attachedImages.map((image, index) => (
            <img
              key={`${index}-${image.name}`}
              className="user-message-image"
              src={image.src}
              alt={image.name}
              width={image.width}
              height={image.height}
              loading="lazy"
              decoding="async"
            />
          ))}
        </div>
      )}
      {/* 添付ファイルのチップ表示（添付がある場合のみ） / Attachment chips (shown only when files are attached) */}
      {documentNames.length > 0 && (
        <div className="user-message-attachments">
          {documentNames.map((name) => (
            <div key={name} className="user-message-attachment-chip">
              <i className="bi bi-file-earmark-text" aria-hidden="true"></i>
              <span>{name}</span>
            </div>
          ))}
        </div>
      )}
      <div dangerouslySetInnerHTML={{ __html: formatted }}></div>
    </>
  );
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const UserMessageHtml = memo(UserMessageHtmlComponent);
UserMessageHtml.displayName = "UserMessageHtml";
