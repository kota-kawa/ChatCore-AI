import type { ChatGenerationPhase } from "./types";

type InitialThinkingState = {
  text: string;
  generationPhase: ChatGenerationPhase;
};

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
    text: english ? "AI is preparing a response" : "AIが応答を準備しています",
    generationPhase: "preparing",
  };
}
