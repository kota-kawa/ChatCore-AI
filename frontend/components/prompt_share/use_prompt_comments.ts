import { useCallback, useRef, useState } from "react";

import { showConfirmModal } from "../../scripts/core/alert_modal";
import { showToast } from "../../scripts/core/toast";
import {
  createPromptComment,
  deletePromptComment,
  fetchPromptComments,
  reportPromptComment
} from "../../scripts/prompt_share/api";
import type { PromptCommentData } from "../../scripts/prompt_share/types";
import type { PromptRecord } from "./prompt_card";
import { getPromptId } from "./prompt_share_page_utils";

type UsePromptCommentsOptions = {
  detailPrompt: PromptRecord | null;
  isLoggedIn: boolean;
  updatePromptCommentCount: (promptId: string | number, nextCount: number) => void;
};

// 詳細モーダル内のコメント取得・投稿・削除・報告を管理する
// Manages comment loading, submission, deletion, and reporting in the detail modal
export function usePromptComments({
  detailPrompt,
  isLoggedIn,
  updatePromptCommentCount
}: UsePromptCommentsOptions) {
  const [detailComments, setDetailComments] = useState<PromptCommentData[]>([]);
  const [isDetailCommentsLoading, setIsDetailCommentsLoading] = useState(false);
  const [isCommentSubmitting, setIsCommentSubmitting] = useState(false);
  const [commentDraft, setCommentDraft] = useState("");
  const [commentActionPendingIds, setCommentActionPendingIds] = useState<Set<string>>(new Set());
  const detailPromptIdRef = useRef("");

  const resetPromptComments = useCallback(() => {
    detailPromptIdRef.current = "";
    setDetailComments([]);
    setCommentDraft("");
    setCommentActionPendingIds(new Set());
    setIsDetailCommentsLoading(false);
    setIsCommentSubmitting(false);
  }, []);

  // コメントの削除・報告操作の処理中に重複リクエストを防ぐためのフラグを管理する
  // Manages pending flags for comment delete/report operations to avoid duplicate requests
  const setCommentActionPending = useCallback((commentId: string, pending: boolean) => {
    setCommentActionPendingIds((current) => {
      const next = new Set(current);
      if (pending) {
        next.add(commentId);
      } else {
        next.delete(commentId);
      }
      return next;
    });
  }, []);

  // 指定プロンプトのコメントを取得する。モーダルの切り替えによる競合を防ぐためpromptIdで検証する
  // Fetches comments for a prompt; validates against the current promptId to prevent race conditions when switching modals
  const loadPromptComments = useCallback(
    async (promptId: string | number) => {
      const targetPromptId = String(promptId);
      detailPromptIdRef.current = targetPromptId;
      setIsDetailCommentsLoading(true);
      try {
        const payload = await fetchPromptComments(promptId);
        // 取得完了前にモーダルが切り替わっていた場合は結果を破棄する
        // Discard results if the modal was switched before the fetch completed
        if (detailPromptIdRef.current !== targetPromptId) {
          return;
        }
        const nextComments = Array.isArray(payload.comments) ? payload.comments : [];
        setDetailComments(nextComments);
        if (payload.comment_count !== undefined) {
          updatePromptCommentCount(promptId, payload.comment_count);
        }
      } catch (error) {
        if (detailPromptIdRef.current !== targetPromptId) {
          return;
        }
        console.error("コメント取得エラー:", error);
        showToast("コメントの読み込みに失敗しました。", { variant: "error" });
      } finally {
        if (detailPromptIdRef.current === targetPromptId) {
          setIsDetailCommentsLoading(false);
        }
      }
    },
    [updatePromptCommentCount]
  );

  // コメントを投稿し、成功したらレスポンスから直接コメントリストを更新する
  // Posts a comment and updates the comment list directly from the response to avoid a refetch
  const handleSubmitPromptComment = useCallback(async () => {
    if (!isLoggedIn) {
      showToast("コメントするにはログインが必要です。", { variant: "error" });
      return;
    }
    const promptId = getPromptId(detailPrompt);
    const content = commentDraft.trim();
    if (!promptId) {
      showToast("コメント対象のプロンプトが見つかりません。", { variant: "error" });
      return;
    }
    if (!content) {
      showToast("コメント内容を入力してください。", { variant: "error" });
      return;
    }
    const optimisticCommentId = `optimistic-comment-${Date.now()}`;
    const previousCommentCount = Number(detailPrompt?.comment_count || 0);
    const optimisticComment: PromptCommentData = {
      id: optimisticCommentId,
      prompt_id: promptId,
      user_id: 0,
      author_name: "あなた",
      content,
      created_at: new Date().toISOString(),
      mine: true,
      can_delete: false
    };
    setIsCommentSubmitting(true);
    setCommentDraft("");
    setDetailComments((current) => [...current, optimisticComment]);
    updatePromptCommentCount(promptId, previousCommentCount + 1);
    try {
      const payload = await createPromptComment(promptId, content);
      if (payload.comment_count !== undefined) {
        updatePromptCommentCount(promptId, payload.comment_count);
      }
      if (payload.comment) {
        setDetailComments((current) =>
          current.map((comment) => (String(comment.id) === optimisticCommentId ? payload.comment! : comment))
        );
      } else {
        // APIがコメントオブジェクトを返さなかった場合はコメント一覧を再取得する
        // If the API did not return a comment object, re-fetch the full comment list
        await loadPromptComments(promptId);
      }
      showToast("コメントを投稿しました。", { variant: "success" });
    } catch (error) {
      setDetailComments((current) => current.filter((comment) => String(comment.id) !== optimisticCommentId));
      updatePromptCommentCount(promptId, previousCommentCount);
      setCommentDraft(content);
      console.error("コメント投稿エラー:", error);
      showToast(error instanceof Error ? error.message : "コメント投稿に失敗しました。", {
        variant: "error"
      });
    } finally {
      setIsCommentSubmitting(false);
    }
  }, [commentDraft, detailPrompt, isLoggedIn, loadPromptComments, updatePromptCommentCount]);

  // ユーザーに確認を求めてからコメントを削除し、削除後はリストから該当コメントを除外する
  // Prompts the user for confirmation before deleting, then removes the comment from the local list
  const handleDeletePromptComment = useCallback(
    async (commentId: string | number) => {
      const confirmed = await showConfirmModal("このコメントを削除しますか？");
      if (!confirmed) {
        return;
      }
      const commentKey = String(commentId);
      setCommentActionPending(commentKey, true);
      const removedComment = detailComments.find((comment) => String(comment.id) === commentKey) || null;
      const currentPromptId = getPromptId(detailPrompt);
      const previousCommentCount = Number(detailPrompt?.comment_count || 0);
      setDetailComments((current) => current.filter((comment) => String(comment.id) !== commentKey));
      if (currentPromptId) {
        updatePromptCommentCount(currentPromptId, Math.max(0, previousCommentCount - 1));
      }
      try {
        const payload = await deletePromptComment(commentId);
        if (payload.prompt_id !== undefined && payload.comment_count !== undefined) {
          updatePromptCommentCount(payload.prompt_id, payload.comment_count);
        }
        showToast("コメントを削除しました。", { variant: "success" });
      } catch (error) {
        if (removedComment) {
          setDetailComments((current) => {
            if (current.some((comment) => String(comment.id) === commentKey)) return current;
            return [...current, removedComment as PromptCommentData];
          });
        }
        if (currentPromptId) {
          updatePromptCommentCount(currentPromptId, previousCommentCount);
        }
        console.error("コメント削除エラー:", error);
        showToast(error instanceof Error ? error.message : "コメント削除に失敗しました。", {
          variant: "error"
        });
      } finally {
        setCommentActionPending(commentKey, false);
      }
    },
    [detailComments, detailPrompt, setCommentActionPending, updatePromptCommentCount]
  );

  // コメントを不正利用として報告し、モデレーターによって非表示にされた場合はリストから即座に除外する
  // Reports a comment for abuse and removes it from the local list immediately if the server hides it
  const handleReportPromptComment = useCallback(
    async (commentId: string | number) => {
      if (!isLoggedIn) {
        showToast("コメントを報告するにはログインが必要です。", { variant: "error" });
        return;
      }
      const confirmed = await showConfirmModal("このコメントを報告しますか？");
      if (!confirmed) {
        return;
      }
      const commentKey = String(commentId);
      setCommentActionPending(commentKey, true);
      try {
        const payload = await reportPromptComment(commentId, "abuse");
        if (payload.already_reported) {
          showToast("このコメントはすでに報告済みです。", { variant: "info" });
        } else {
          showToast("コメントを報告しました。", { variant: "success" });
        }
        if (payload.hidden) {
          setDetailComments((current) => current.filter((comment) => String(comment.id) !== commentKey));
        }
        if (payload.prompt_id !== undefined && payload.comment_count !== undefined) {
          updatePromptCommentCount(payload.prompt_id, payload.comment_count);
        }
      } catch (error) {
        console.error("コメント報告エラー:", error);
        showToast(error instanceof Error ? error.message : "コメント報告に失敗しました。", {
          variant: "error"
        });
      } finally {
        setCommentActionPending(commentKey, false);
      }
    },
    [isLoggedIn, setCommentActionPending, updatePromptCommentCount]
  );

  // 詳細モーダルからコメントを手動で再読み込みするためのアクション
  // Action for manually refreshing comments from within the detail modal
  const reloadDetailComments = useCallback(() => {
    const promptId = getPromptId(detailPrompt);
    if (!promptId) return;
    void loadPromptComments(promptId);
  }, [detailPrompt, loadPromptComments]);

  return {
    commentActionPendingIds,
    commentDraft,
    detailComments,
    handleDeletePromptComment,
    handleReportPromptComment,
    handleSubmitPromptComment,
    isCommentSubmitting,
    isDetailCommentsLoading,
    loadPromptComments,
    reloadDetailComments,
    resetPromptComments,
    setCommentDraft
  };
}
