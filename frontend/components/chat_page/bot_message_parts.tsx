import { memo } from "react";

import type { ChatMessagePart } from "../../lib/chat_page/types";
import { BotMessageHtml } from "./bot_message_html";
import { SandboxArtifactFrame } from "./sandbox_artifact_frame";
import { InteractiveButtons } from "./interactive_buttons";

type BotMessagePartsProps = {
  fallbackText: string;
  parts?: ChatMessagePart[];
};

function BotMessagePartsComponent({ fallbackText, parts }: BotMessagePartsProps) {
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
          return (
            <div key={`buttons-${index}`} className="bot-message-part bot-message-part--buttons">
              <InteractiveButtons buttons={part.buttons} messageId={`btn-${index}`} />
            </div>
          );
        }
        return null;
      })}
    </div>
  );
}

export const BotMessageParts = memo(BotMessagePartsComponent);
BotMessageParts.displayName = "BotMessageParts";
