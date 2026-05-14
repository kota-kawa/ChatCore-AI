import { memo, useMemo } from "react";

import { formatUserInputForDisplay } from "../../scripts/chat/chat_ui";

type UserMessageHtmlProps = {
  text: string;
  attachedFileNames?: string[];
};

function UserMessageHtmlComponent({ text, attachedFileNames }: UserMessageHtmlProps) {
  // formatUserInputForDisplay escapes the fallback path and sanitizes marked HTML
  // before returning it, so dangerouslySetInnerHTML is limited to safe markup.
  const formatted = useMemo(() => formatUserInputForDisplay(text), [text]);

  return (
    <>
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

export const UserMessageHtml = memo(UserMessageHtmlComponent);
UserMessageHtml.displayName = "UserMessageHtml";
