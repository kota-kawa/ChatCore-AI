// チャット生成 SSE の1イベントを「画面へ加える変化」へ翻訳する純関数群。
// React にも fetch にも依存しないので、イベント列と期待する変化だけでテストできる。
// 文字送りやタイマーなどの演出は generation_stream_consumer.ts が担当する。
// Pure functions that translate one chat-generation SSE event into the change
// it should make to the screen. They depend on neither React nor fetch, so an
// event sequence can be tested against the expected changes alone. Pacing and
// timing effects live in generation_stream_consumer.ts.

import { normalizeChatResponsePayload } from "./api_contract";
import { getStreamingGenerativeUiDisplayText } from "./generative_ui_stream";
import type { ChatGenerationPhase, ChatMessagePart, StreamParsedEvent } from "./types";
import { getWebSearchFailureStatus } from "./web_search_failure_status";

export type StreamLocalize = (ja: string, en: string) => string;

export type GenerationStreamEventContext = {
  // ここまでに受信済みの生テキスト。payload が本文を省略したときの既定値になる。
  // Raw text received so far; the fallback when a payload omits the body.
  streamedText: string;
  localize: StreamLocalize;
};

export type GenerationStreamAction =
  // 何もしないイベント（未知のイベント名、空チャンクなど）。
  // An event that changes nothing (unknown event name, empty chunk, ...).
  | { kind: "ignored" }
  | { kind: "chunk"; text: string }
  | { kind: "parts_updated"; displayText: string; parts: ChatMessagePart[] | null }
  | { kind: "thinking_status"; text: string; phase: ChatGenerationPhase }
  | { kind: "done"; roomTitle: unknown; responseText: string; parts?: ChatMessagePart[] }
  // 完了したが本文もパーツも無い = 回答なし。空の吹き出しではなくエラーにする。
  // Completed with neither body nor answer parts: no answer at all, so this
  // becomes an error instead of a blank bubble.
  | { kind: "empty_answer"; roomTitle: unknown; message: string }
  | { kind: "incomplete"; roomTitle: unknown; finalText: string; parts?: ChatMessagePart[]; message: string }
  | { kind: "aborted"; finalText: string; parts?: ChatMessagePart[] }
  | { kind: "error"; message: string };

const IGNORED: GenerationStreamAction = { kind: "ignored" };

function thinkingStatus(text: string, phase: ChatGenerationPhase): GenerationStreamAction {
  return { kind: "thinking_status", text, phase };
}

function readNumberField(data: Record<string, unknown>, key: string): number {
  const value = data[key];
  return typeof value === "number" ? value : 0;
}

// 事前検索済みのクエリは再検索していないので、0件として扱わない。
// An already prefetched query was not searched again, so it must not read as zero hits.
function isAlreadySearched(data: Record<string, unknown>): boolean {
  return data.status === "already_searched";
}

function interpretSharedPromptSearchEvent(
  event: string,
  data: Record<string, unknown>,
  localize: StreamLocalize,
): GenerationStreamAction | null {
  if (event === "shared_prompt_search_started") {
    return thinkingStatus(localize("共有プロンプトを検索しています", "Searching shared prompts"), "web-search");
  }

  if (event === "shared_prompt_search_completed") {
    if (isAlreadySearched(data)) {
      return thinkingStatus(
        localize("取得済みの共有プロンプトを読み込んでいます", "Reading the shared prompts already retrieved"),
        "web-search",
      );
    }
    const promptCount = readNumberField(data, "prompt_count");
    return thinkingStatus(
      promptCount > 0
        ? localize("見つかった共有プロンプトを読み込んでいます", "Reading the shared prompts that matched")
        : localize("該当する共有プロンプトはありませんでした。思考中", "No shared prompt matched. Preparing an answer"),
      promptCount > 0 ? "web-search" : "generating",
    );
  }

  if (event === "shared_prompt_search_failed") {
    return thinkingStatus(
      localize("共有プロンプトの検索に失敗しました。思考中", "Shared prompt search failed. Preparing an answer"),
      "generating",
    );
  }

  return null;
}

function interpretPersonalKnowledgeSearchEvent(
  event: string,
  data: Record<string, unknown>,
  localize: StreamLocalize,
): GenerationStreamAction | null {
  if (event === "personal_knowledge_search_started") {
    return thinkingStatus(
      localize("メモとマイコンテキストを検索しています", "Searching your memos and My Context"),
      "web-search",
    );
  }

  if (event === "personal_knowledge_search_completed") {
    if (isAlreadySearched(data)) {
      return thinkingStatus(
        localize("取得済みのメモを読み込んでいます", "Reading the notes already retrieved"),
        "web-search",
      );
    }
    const matchCount = readNumberField(data, "memo_count") + readNumberField(data, "context_fact_count");
    return thinkingStatus(
      matchCount > 0
        ? localize("見つかったメモを読み込んでいます", "Reading the notes that matched")
        : localize("該当するメモはありませんでした。思考中", "No notes matched. Preparing an answer"),
      matchCount > 0 ? "web-search" : "generating",
    );
  }

  if (event === "personal_knowledge_search_failed") {
    return thinkingStatus(
      localize("メモの検索に失敗しました。思考中", "Note search failed. Preparing an answer"),
      "generating",
    );
  }

  return null;
}

function interpretWebSearchEvent(
  event: string,
  data: Record<string, unknown>,
  localize: StreamLocalize,
): GenerationStreamAction | null {
  if (event === "web_search_started") {
    return thinkingStatus(localize("Web検索中", "Finding relevant information"), "web-search");
  }

  if (event === "web_search_completed") {
    return thinkingStatus(localize("検索結果を読み込んでいます", "Reading search results"), "web-search");
  }

  if (event === "web_search_failed") {
    switch (getWebSearchFailureStatus(data.code)) {
      case "configuration":
        return thinkingStatus(
          localize("検索設定を確認できませんでした。思考中", "Search settings were unavailable. Preparing an answer"),
          "generating",
        );
      case "quota_exceeded":
        return thinkingStatus(
          localize("Web検索の上限に達しました。思考中", "The web search limit was reached. Preparing an answer"),
          "generating",
        );
      case "request_failed":
      default:
        return thinkingStatus(
          localize("Web検索に失敗しました。思考中", "Web search failed. Preparing an answer"),
          "generating",
        );
    }
  }

  return null;
}

// チャットから読み書きするツール（メモなど）の進み具合。読み取りは検索と同じ段階として見せ、
// 書き込みは実行せず承認待ちを作るだけなので、回答の準備に戻ったことを伝える。
// Progress of the chat workspace tools (memos and so on). Reads show as the lookup phase like a
// search; writes never run on the spot but prepare a pending approval, so the status returns to
// preparing the answer.
const WORKSPACE_READ_TOOLS = new Set(["memo_list", "memo_search", "memo_read"]);
const WORKSPACE_WRITE_TOOLS = new Set(["memo_create", "memo_append", "memo_edit"]);

function interpretWorkspaceToolEvent(
  event: string,
  data: Record<string, unknown>,
  localize: StreamLocalize,
): GenerationStreamAction | null {
  const tool = typeof data.tool === "string" ? data.tool : "";

  if (event === "workspace_tool_started") {
    if (tool === "memo_read") {
      return thinkingStatus(localize("メモを読んでいます", "Reading a memo"), "web-search");
    }
    if (WORKSPACE_READ_TOOLS.has(tool)) {
      return thinkingStatus(localize("メモを探しています", "Looking through your memos"), "web-search");
    }
    if (WORKSPACE_WRITE_TOOLS.has(tool)) {
      return thinkingStatus(localize("メモの変更案を用意しています", "Preparing a memo change"), "generating");
    }
    return thinkingStatus(localize("作業を進めています", "Working on your request"), "generating");
  }

  if (event === "workspace_tool_completed") {
    if (WORKSPACE_READ_TOOLS.has(tool)) {
      return thinkingStatus(localize("読み込んだメモを確認しています", "Going through the memos read"), "web-search");
    }
    // 書き込みの完了は「常に承認」で自動実行したときだけ届く
    // A write only completes here when "always approve" ran it automatically
    if (WORKSPACE_WRITE_TOOLS.has(tool)) {
      return thinkingStatus(localize("メモを更新しました。思考中", "Updated the memo. Preparing an answer"), "generating");
    }
    return thinkingStatus(localize("思考中", "Preparing an answer"), "generating");
  }

  if (event === "workspace_tool_failed") {
    if (WORKSPACE_READ_TOOLS.has(tool) || WORKSPACE_WRITE_TOOLS.has(tool)) {
      return thinkingStatus(
        localize("メモの操作に失敗しました。思考中", "The memo step failed. Preparing an answer"),
        "generating",
      );
    }
    return thinkingStatus(localize("作業に失敗しました。思考中", "A step failed. Preparing an answer"), "generating");
  }

  if (event === "tool_approval_prepared") {
    return thinkingStatus(
      localize("承認待ちの変更を用意しました。思考中", "A change is waiting for your approval. Preparing an answer"),
      "generating",
    );
  }

  return null;
}

function interpretDoneEvent(
  data: Record<string, unknown>,
  context: GenerationStreamEventContext,
): GenerationStreamAction {
  const donePayload = normalizeChatResponsePayload(data);
  const responseText = donePayload.response ?? context.streamedText;
  // 検索画像だけのパーツは回答ではない。サーバー側の空判定と同じ規則で扱う。
  // Web-search image parts alone are not an answer; mirror the server-side rule.
  const hasAnswerParts = donePayload.parts?.some((part) => part.type !== "web_search_image") ?? false;

  if (!responseText.trim() && !hasAnswerParts) {
    return {
      kind: "empty_answer",
      roomTitle: data.room_title,
      message: context.localize(
        "AIからの回答が空でした。もう一度お試しください。",
        "The AI returned an empty answer. Please try again.",
      ),
    };
  }

  return {
    kind: "done",
    roomTitle: data.room_title,
    responseText,
    parts: donePayload.parts,
  };
}

function interpretIncompleteEvent(
  data: Record<string, unknown>,
  context: GenerationStreamEventContext,
): GenerationStreamAction {
  const incompletePayload = normalizeChatResponsePayload(data);
  return {
    kind: "incomplete",
    roomTitle: data.room_title,
    finalText: incompletePayload.response ?? context.streamedText,
    parts: incompletePayload.parts,
    message:
      typeof data.message === "string"
        ? data.message
        : context.localize(
            "回答の生成が途中で終了しました。途中までの回答は保存されています。",
            "The response ended early. The partial answer was saved.",
          ),
  };
}

export function interpretGenerationStreamEvent(
  parsed: StreamParsedEvent,
  context: GenerationStreamEventContext,
): GenerationStreamAction {
  const { data } = parsed;
  const { localize } = context;

  if (parsed.event === "chunk") {
    const text = typeof data.text === "string" ? data.text : "";
    return text ? { kind: "chunk", text } : IGNORED;
  }

  if (parsed.event === "response_parts_updated") {
    const updatePayload = normalizeChatResponsePayload(data);
    const displayText = updatePayload.response ?? getStreamingGenerativeUiDisplayText(context.streamedText);
    return {
      kind: "parts_updated",
      displayText,
      parts: updatePayload.parts?.length ? updatePayload.parts : null,
    };
  }

  const progressStatus =
    interpretSharedPromptSearchEvent(parsed.event, data, localize) ??
    interpretPersonalKnowledgeSearchEvent(parsed.event, data, localize) ??
    interpretWebSearchEvent(parsed.event, data, localize) ??
    interpretWorkspaceToolEvent(parsed.event, data, localize);
  if (progressStatus) return progressStatus;

  if (parsed.event === "response_generation_started") {
    return thinkingStatus(localize("思考中", "Preparing an answer"), "generating");
  }

  if (parsed.event === "done") return interpretDoneEvent(data, context);
  if (parsed.event === "incomplete") return interpretIncompleteEvent(data, context);

  if (parsed.event === "aborted") {
    // 停止時にサーバーが保存した生成途中のテキストを優先して表示する。
    // Prefer the partial text the server persisted on stop so it is not lost.
    const abortedPayload = normalizeChatResponsePayload(data);
    return {
      kind: "aborted",
      finalText: abortedPayload.response ?? context.streamedText,
      parts: abortedPayload.parts,
    };
  }

  if (parsed.event === "error") {
    return {
      kind: "error",
      message:
        typeof data.message === "string"
          ? data.message
          : localize("ストリーミング生成中にエラーが発生しました。", "An error occurred while streaming the response."),
    };
  }

  return IGNORED;
}
