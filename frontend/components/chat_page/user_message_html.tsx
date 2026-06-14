import { memo, useMemo } from "react";

import { formatUserInputForDisplay } from "../../scripts/chat/chat_ui";

// ユーザーメッセージHTML表示のprops型定義
// Props type definition for the user message HTML display
type UserMessageHtmlProps = {
  text: string;
  attachedFileNames?: string[];
};

// ユーザーのメッセージとファイル添付を表示するコンポーネント
// Component that displays the user's message and attached files
function UserMessageHtmlComponent({ text, attachedFileNames }: UserMessageHtmlProps) {
  // formatUserInputForDisplay escapes the fallback path and sanitizes marked HTML
  // before returning it, so dangerouslySetInnerHTML is limited to safe markup.
  const formatted = useMemo(() => formatUserInputForDisplay(text), [text]);

  return (
    <>
      {/* 添付ファイルのチップ表示（添付がある場合のみ） / Attachment chips (shown only when files are attached) */}
      {attachedFileNames && attachedFileNames.length > 0 && (
        <div className="user-message-attachments">
          {attachedFileNames.map((name) => (
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
