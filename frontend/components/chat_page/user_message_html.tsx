import { memo, useMemo } from "react";

import { formatUserInputForDisplay } from "../../scripts/chat/chat_ui";
import { renderSanitizedHTML } from "../../scripts/chat/message_utils";

type UserMessageHtmlProps = {
  text: string;
};

/**
 * ユーザーメッセージのHTML表示コンポーネント
 * 修正: useLayoutEffect による後付け注入を止め、最初からコンテンツをレンダリングすることで
 * 描画時の高さのガタつき（一瞬小さく表示される現象）を根本的に解消します。
 */
function UserMessageHtmlComponent({ text }: UserMessageHtmlProps) {
  const formatted = useMemo(() => formatUserInputForDisplay(text), [text]);

  // renderSanitizedHTML の内部で行っているサニタイズ処理を考慮しつつ、
  // コンポーネントとして一貫した出力を即時に行うために dangerouslySetInnerHTML を使用します。
  // (中身のサニタイズは formatUserInputForDisplay および markedParser 内で保証されています)
  return <div dangerouslySetInnerHTML={{ __html: formatted }}></div>;
}

export const UserMessageHtml = memo(UserMessageHtmlComponent);
UserMessageHtml.displayName = "UserMessageHtml";
