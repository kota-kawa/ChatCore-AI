import { memo } from "react";

import { useTranslation } from "../../contexts/locale_context";
import type { ChatMessagePart, InteractiveButtonsV1 } from "../../lib/chat_page/types";
import { BotMessageHtml } from "../chat_page/bot_message_html";
import { SandboxArtifactFrame } from "../chat_page/sandbox_artifact_frame";
import { WebSearchImagePart } from "../chat_page/web_search_image_part";

// 共有ページ用のアシスタントメッセージ本体。通常チャットの BotMessageParts と
// 同じクラス構成・同じレンダラーを使い、送信を伴う対話型ボタンだけ無効化する。
// Assistant message body for the shared page. It mirrors the class names and renderers of
// the regular chat's BotMessageParts, and only disables the send-triggering interactive buttons.
type SharedChatMessagePartsProps = {
  fallbackText: string;
  parts?: ChatMessagePart[];
};

// yes_no 形式は固定の 2 択、それ以外は AI が提示した選択肢をそのまま並べる
// The yes_no format always offers the same two choices; other formats list the AI's options
function resolveButtonLabels(buttons: InteractiveButtonsV1) {
  if (buttons.type === "yes_no") return ["Yes", "No"];
  return buttons.options ?? [];
}

function SharedChatMessagePartsComponent({ fallbackText, parts }: SharedChatMessagePartsProps) {
  const { locale } = useTranslation();
  const english = locale === "en";
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
          // 共有ページからは返信を送れないため、見た目はそのままに操作だけ封じる
          // Replies cannot be sent from the shared page, so keep the look but block interaction
          return (
            <div key={`buttons-${index}`} className="bot-message-part bot-message-part--buttons">
              <div className="interactive-buttons-container">
                <div className="interactive-buttons-question">{part.buttons.question}</div>
                <div className="interactive-buttons-actions">
                  {resolveButtonLabels(part.buttons).map((label, optionIndex) => (
                    <button
                      key={`${label}-${optionIndex}`}
                      type="button"
                      className={`interactive-button ${optionIndex === 0 ? "primary" : "secondary"}`}
                      disabled
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <p className="interactive-buttons-readonly-note">
                  {english ? "Interactive buttons are unavailable in shared views." : "対話型ボタンは共有画面では動作しません。"}
                </p>
              </div>
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
