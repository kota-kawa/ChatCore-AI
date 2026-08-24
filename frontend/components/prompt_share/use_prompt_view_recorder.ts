import { useCallback } from "react";

import { recordPromptView } from "../../scripts/prompt_share/api";
import { getPromptId } from "./prompt_share_page_utils";
import type { PromptRecord } from "./prompt_card";


type UsePromptViewRecorderOptions = {
  updatePromptRecord: (
    clientId: string,
    updater: (prompt: PromptRecord) => PromptRecord
  ) => void;
};


// 詳細を開いた実ユーザーの閲覧を記録し、最新件数を一覧・モーダル双方へ反映する。
// Record a real client-side detail open and mirror the latest count into feed/modal state.
export function usePromptViewRecorder({
  updatePromptRecord
}: UsePromptViewRecorderOptions) {
  return useCallback(
    (prompt: PromptRecord) => {
      const promptId = getPromptId(prompt);
      if (!promptId) {
        return;
      }
      void recordPromptView(promptId)
        .then((payload) => {
          if (typeof payload.view_count !== "number") {
            return;
          }
          updatePromptRecord(prompt.clientId, (current) => ({
            ...current,
            view_count: payload.view_count
          }));
        })
        .catch((error) => {
          console.error("プロンプトビュー記録エラー:", error);
        });
    },
    [updatePromptRecord]
  );
}
