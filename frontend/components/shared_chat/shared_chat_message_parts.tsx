import { memo } from "react";

import type { ChatMessagePart } from "../../lib/chat_page/types";
import { BotMessageHtml } from "../chat_page/bot_message_html";
import { InteractiveButtons } from "../chat_page/interactive_buttons";
import { SandboxArtifactFrame } from "../chat_page/sandbox_artifact_frame";
import { WebSearchImagePart } from "../chat_page/web_search_image_part";
import { GenerativeUiStatusNotice } from "../chat_page/generative_ui_status_notice";

// 共有ページ用のアシスタントメッセージ本体。通常チャットの BotMessageParts と
// 同じクラス構成・同じレンダラーを使い、送信を伴う対話型ボタンだけ無効化する。
// Assistant message body for the shared page. It mirrors the class names and renderers of
// the regular chat's BotMessageParts, and only disables the send-triggering interactive buttons.
type SharedChatMessagePartsProps = {
  fallbackText: string;
  parts?: ChatMessagePart[];
};

function SharedChatMessagePartsComponent({ fallbackText, parts }: SharedChatMessagePartsProps) {
  // partsが空の場合はフォールバックテキストをテキストパーツとして使用する
  // Use fallback text as a text part when parts is empty
  const renderParts = parts && parts.length > 0 ? parts : [{ type: "text" as const, text: fallbackText }];

  return (
    <div className="bot-message-parts">
      {renderParts.map((part, index) => {
        if (part.type === "text") {
          return part.text ? (
            <div key={`text-${index}`} className="bot-message-part bot-message-part--text">
              <BotMessageHtml text={part.text} />
            </div>
          ) : null;
        }
        if (part.type === "sandbox_artifact") {
          return (
            <div key={`artifact-${index}`} className="bot-message-part bot-message-part--artifact">
              <SandboxArtifactFrame artifact={part.artifact} />
            </div>
          );
        }
        if (part.type === "interactive_buttons") {
          // 共有ページからは返信を送れないため、送信先を渡さず読み取り専用で描く
          // Replies cannot be sent from the shared page, so render read-only without a send target
          return (
            <div key={`buttons-${index}`} className="bot-message-part bot-message-part--buttons">
              <InteractiveButtons buttons={part.buttons} />
            </div>
          );
        }
        if (part.type === "artifact_status") {
          return (
            <div key={`artifact-status-${index}`} className="bot-message-part bot-message-part--artifact-status">
              <GenerativeUiStatusNotice status={part.status} />
            </div>
          );
        }
        if (part.type === "web_search_image") {
          return (
            <div key={`web-search-image-${index}`} className="bot-message-part bot-message-part--web-search-image">
              <WebSearchImagePart image={part.image} />
            </div>
          );
        }
        return null;
      })}
    </div>
  );
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const SharedChatMessageParts = memo(SharedChatMessagePartsComponent);
SharedChatMessageParts.displayName = "SharedChatMessageParts";
