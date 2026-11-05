// 生成を始めた直後に表示する「思考中」ステータスの文言と段階を、有効な検索対象（個人情報・共有プロンプト）から決める。
// Chooses the status text and phase shown right after generation starts, based on which search sources (personal knowledge, shared prompts) are enabled.
// Used by hooks/chat_page/use_home_page_generation_actions.ts.

import type { ChatGenerationPhase } from "./types";

// 表示する文言と、生成の段階（検索中か、回答の準備中か）。
// The text to display and the generation phase (searching or preparing a response).
type InitialThinkingState = {
  text: string;
  generationPhase: ChatGenerationPhase;
};

// メモ・マイコンテキストと共有プロンプトのどちらを検索するかに応じて文言を選ぶ。どちらも使わないときだけ「準備中」の段階にする。
// Picks the text by which of memos/My Context and shared prompts will be searched; only when neither is used does the phase become "preparing".
export function getInitialThinkingState(
  personalKnowledgeEnabled: boolean,
  sharedPromptsEnabled: boolean,
  locale: string,
): InitialThinkingState {
  const english = locale === "en";
  if (personalKnowledgeEnabled && sharedPromptsEnabled) {
    return {
      text: english
        ? "Searching your memos, My Context, and shared prompts"
        : "メモ、マイコンテキスト、共有プロンプトを検索しています",
      generationPhase: "web-search",
    };
  }
  if (personalKnowledgeEnabled) {
    return {
      text: english
        ? "Searching your memos and My Context"
        : "メモとマイコンテキストを検索しています",
      generationPhase: "web-search",
    };
  }
  if (sharedPromptsEnabled) {
    return {
      text: english ? "Searching shared prompts" : "共有プロンプトを検索しています",
      generationPhase: "web-search",
    };
  }
  return {
    text: english ? "AI is preparing a response" : "思考中",
    generationPhase: "preparing",
  };
}
