// AI メッセージを構成するパーツ（本文・生成UI・選択ボタン・承認カード・検索画像など）を順に描画する。chat_message_list.tsx から使われる。
// Renders the parts of an AI message in order (text, generated UI, choice buttons, approval cards, search images, ...); used by chat_message_list.tsx.
import { memo } from "react";

import { isAnswerTracePart } from "../../lib/chat_page/answer_trace";
import type { ToolApprovalDecision } from "../../lib/chat_page/tool_approval_api";
import type { ChatMessagePart } from "../../lib/chat_page/types";
import { AnswerTracePart, answerTraceSharesTextPart, type AnswerTraceMessagePart } from "./answer_trace";
import { BotMessageHtml } from "./bot_message_html";
import { SandboxArtifactFrame } from "./sandbox_artifact_frame";
import { InteractiveButtons } from "./interactive_buttons";
import { StructuredUiRenderer } from "./structured_ui_renderer";
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
  // 選択ボタンや生成UIから質問・回答を入力欄へ反映する
  // Adds a question and answer from choice buttons or generated UI to the composer
  onCompose?: (text: string) => void;
  // 回答済みや生成中で、入力欄へ反映できない状態
  // The composer cannot be changed because the answer was handled or a reply is generating
  composeDisabled?: boolean;
  getStructuredUiStateScope?: (blockId: string) => string | undefined;
  // 承認カードの決定を送る / Sends the decision made on an approval card
  onToolApprovalDecide?: (approvalId: string, decision: ToolApprovalDecision, acknowledgeWarnings?: boolean) => Promise<void>;
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
  onCompose,
  composeDisabled = false,
  getStructuredUiStateScope,
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

  const leadingTrace = answerTraceSharesTextPart(renderParts) ? (renderParts[0] as AnswerTraceMessagePart) : null;
  const standaloneLeadingTrace = !leadingTrace && isAnswerTracePart(renderParts[0]);

  // 本文の key は本文どうしの何番目かで決める。生成中に実行記録が先頭へ加わっても、描画中の本文を作り直さない。
  // A text part's key is its ordinal among text parts, so an execution record joining at the head mid-generation does not remount the prose being drawn.
  // 先頭の記録と本文が別枠になっても、外側の開閉状態を保つため記録側に text-0 を残す。
  // Keep text-0 with the leading record when it and the text need separate wrappers, so the record stays mounted.
  let textOrdinal = standaloneLeadingTrace ? 1 : 0;

  return (
    <div className="bot-message-parts">
      {renderParts.map((part, index) => {
        // パーツの種類ごとに専用コンポーネントへ振り分ける。未知の種類は何も描画しない（最後の return null）
        // Dispatch each part type to its own component; unknown types render nothing (the final return null)
        if (part.type === "text") {
          const ordinal = textOrdinal;
          textOrdinal += 1;
          const trace = ordinal === 0 ? leadingTrace : null;
          return part.text || trace ? (
            <div key={`text-${ordinal}`} className="bot-message-part bot-message-part--text">
              {trace ? <AnswerTracePart key="answer-trace" part={trace} streaming={streaming} /> : null}
              {part.text ? (
                <BotMessageHtml key="text" text={part.text} streaming={streaming && index === lastTextPartIndex} />
              ) : null}
            </div>
          ) : null;
        }
        if (part.type === "answer_trace" || part.type === "legacy_answer_trace") {
          if (!leadingTrace) {
            return (
              <div key={index === 0 ? "text-0" : "answer-trace"} className="bot-message-part bot-message-part--answer-trace">
                <AnswerTracePart key="answer-trace" part={part} streaming={streaming} />
              </div>
            );
          }
          // 本文が続くときは、その本文の枠の中で描く。本文がまだ無ければ、本文が入る枠を先に作る。
          // When prose follows, the record is drawn inside that prose's wrapper; with no prose yet, the
          // wrapper the prose will join is created first.
          return renderParts.length === 1 ? (
            <div key="text-0" className="bot-message-part bot-message-part--text">
              <AnswerTracePart key="answer-trace" part={part} streaming={streaming} />
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
        if (part.type === "structured_ui") {
          return (
            <div key={`structured-ui-${part.ui.id}`} className="bot-message-part bot-message-part--structured-ui">
              <StructuredUiRenderer
                ui={part.ui}
                onCompose={onCompose}
                disabled={composeDisabled}
                stateScope={getStructuredUiStateScope?.(part.ui.id)}
              />
            </div>
          );
        }
        if (part.type === "interactive_buttons") {
          return (
            <div key={`buttons-${index}`} className="bot-message-part bot-message-part--buttons">
              <InteractiveButtons buttons={part.buttons} onCompose={onCompose} disabled={composeDisabled} />
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
