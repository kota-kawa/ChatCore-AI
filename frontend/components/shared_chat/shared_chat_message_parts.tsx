// 共有チャットのアシスタント発言を、種類ごとの部品（本文・アーティファクト・ボタン・承認カードなど）として描画する。呼び出し元は shared_chat_message_list.tsx。
// Renders a shared chat's assistant message as typed parts (text, artifact, buttons, approval card, etc.). Used by shared_chat_message_list.tsx.
import { memo } from "react";

import type { ChatMessagePart } from "../../lib/chat_page/types";
import { AnswerTracePart, answerTraceSharesTextPart, type AnswerTraceMessagePart } from "../chat_page/answer_trace";
import { BotMessageHtml } from "../chat_page/bot_message_html";
import { InteractiveButtons } from "../chat_page/interactive_buttons";
import { StructuredUiRenderer } from "../chat_page/structured_ui_renderer";
import { ToolApprovalCard } from "../chat_page/tool_approval_card";
import { SandboxArtifactFrame } from "../chat_page/sandbox_artifact_frame";
import { WebSearchImagePart } from "../chat_page/web_search_image_part";
import { GenerativeUiStatusNotice } from "../chat_page/generative_ui_status_notice";

// 共有ページ用のアシスタントメッセージ本体。通常チャットの BotMessageParts と
// 同じクラス構成・同じレンダラーを使い、送信を伴う対話型ボタンだけ無効化する。
// 承認カードはサーバーが中身を伏せた読み取り専用の形で届き、状態だけを見せる。
// Assistant message body for the shared page. It mirrors the class names and renderers of
// the regular chat's BotMessageParts, and only disables the send-triggering interactive buttons.
// Approval cards arrive redacted and readonly from the server, and only their status is shown.
type SharedChatMessagePartsProps = {
  fallbackText: string;
  parts?: ChatMessagePart[];
};

// parts の type ごとに対応するレンダラーを選ぶ。未知の type は何も描画しない
// Pick the renderer for each part type; an unknown type renders nothing
function SharedChatMessagePartsComponent({ fallbackText, parts }: SharedChatMessagePartsProps) {
  // partsが空の場合はフォールバックテキストをテキストパーツとして使用する
  // Use fallback text as a text part when parts is empty
  const renderParts = parts && parts.length > 0 ? parts : [{ type: "text" as const, text: fallbackText }];
  const leadingTrace = answerTraceSharesTextPart(renderParts) ? (renderParts[0] as AnswerTraceMessagePart) : null;

  return (
    <div className="bot-message-parts">
      {renderParts.map((part, index) => {
        if (part.type === "text") {
          // 実行記録は、直後の本文と同じ枠の中に描く（通常のチャットと同じ余白にする）。
          // The execution record is drawn inside the wrapper of the prose that follows it, for the same spacing as the regular chat.
          const trace = index === 1 ? leadingTrace : null;
          return part.text || trace ? (
            <div key={`text-${index}`} className="bot-message-part bot-message-part--text">
              {trace ? <AnswerTracePart part={trace} /> : null}
              {part.text ? <BotMessageHtml text={part.text} /> : null}
            </div>
          ) : null;
        }
        if (part.type === "answer_trace" || part.type === "legacy_answer_trace") {
          if (leadingTrace && renderParts.length > 1) return null;
          return (
            <div key="answer-trace" className="bot-message-part bot-message-part--answer-trace">
              <AnswerTracePart part={part} />
            </div>
          );
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
        if (part.type === "structured_ui") {
          return (
            <div key={`structured-ui-${part.ui.id}`} className="bot-message-part bot-message-part--structured-ui">
              <StructuredUiRenderer ui={part.ui} />
            </div>
          );
        }
        if (part.type === "tool_approval") {
          return (
            <div key={`tool-approval-${part.approval.id}`} className="bot-message-part bot-message-part--tool-approval">
              <ToolApprovalCard approval={part.approval} />
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
