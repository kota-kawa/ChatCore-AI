import { memo } from "react";

import type { ToolApprovalDecision } from "../../lib/chat_page/tool_approval_api";
import type { ChatMessagePart } from "../../lib/chat_page/types";
import { BotMessageHtml } from "./bot_message_html";
import { SandboxArtifactFrame } from "./sandbox_artifact_frame";
import { InteractiveButtons } from "./interactive_buttons";
import { ToolApprovalCard } from "./tool_approval_card";
import { WebSearchImagePart } from "./web_search_image_part";
import { GenerativeUiStatusNotice } from "./generative_ui_status_notice";

// ボットメッセージのパーツ表示コンポーネントのprops型定義
// Props type definition for the bot message parts display component
type BotMessagePartsProps = {
  fallbackText: string;
  parts?: ChatMessagePart[];
  // 生成中かどうか。末尾のテキストパートだけが単語フェードインの対象になる
  // Whether generation is in flight; only the last text part fades words in
  streaming?: boolean;
  // 選択ボタンで選んだ選択肢を次の発話として送る
  // Sends the option chosen on the choice buttons as the next message
  onChoiceSubmit?: (text: string) => void;
  // 回答済みや生成中で、選択ボタンを押せない状態
  // The choice buttons cannot be pressed because they were answered or a reply is generating
  choicesDisabled?: boolean;
  // 承認カードの決定を送る / Sends the decision made on an approval card
  onToolApprovalDecide?: (approvalId: string, decision: ToolApprovalDecision) => Promise<void>;
  // 生成中や後ろに利用者の発言があるなど、承認カードを決められない状態
  // The approval cards cannot be decided because a reply is generating or the user wrote after them
  approvalsDisabled?: boolean;
};

// ボットメッセージを構成するパーツ（テキスト / サンドボックスアーティファクト / 選択ボタン / 承認カード）を順番に描画するコンポーネント
// Component that renders the parts of a bot message in order (text / sandbox artifact / choice buttons / approval cards)
function BotMessagePartsComponent({
  fallbackText,
  parts,
  streaming = false,
  onChoiceSubmit,
  choicesDisabled = false,
  onToolApprovalDecide,
  approvalsDisabled = false,
}: BotMessagePartsProps) {
  // partsが空の場合はフォールバックテキストをテキストパーツとして使用する
  // Use fallback text as a text part when parts is empty
  const renderParts = parts && parts.length > 0 ? parts : [{ type: "text" as const, text: fallbackText }];
  // 伸び続けるのは最後のテキストパートだけなので、そこだけをアニメーション対象にする
  // Only the last text part keeps growing, so only it is animated
  const lastTextPartIndex = renderParts.reduce(
    (lastIndex, part, index) => (part.type === "text" && part.text ? index : lastIndex),
    -1
  );

  return (
    <div className="bot-message-parts">
      {renderParts.map((part, index) => {
        if (part.type === "text") {
          return part.text ? (
            <div key={`text-${index}`} className="bot-message-part bot-message-part--text">
              <BotMessageHtml text={part.text} streaming={streaming && index === lastTextPartIndex} />
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
              <InteractiveButtons buttons={part.buttons} onSubmit={onChoiceSubmit} disabled={choicesDisabled} />
            </div>
          );
        }
        if (part.type === "tool_approval") {
          return (
            <div key={`tool-approval-${part.approval.id}`} className="bot-message-part bot-message-part--tool-approval">
              <ToolApprovalCard approval={part.approval} onDecide={onToolApprovalDecide} disabled={approvalsDisabled} />
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
export const BotMessageParts = memo(BotMessagePartsComponent);
BotMessageParts.displayName = "BotMessageParts";
