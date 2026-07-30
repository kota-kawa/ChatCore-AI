import { useCallback, useRef, useState } from "react";

import { fetchPromptAuthorProfile, fetchPromptList } from "../../scripts/prompt_share/api";
import type { PromptAuthorProfile, PromptData, PromptPagination } from "../../scripts/prompt_share/types";
import { AUTHOR_PROFILE_PROMPTS_PAGE_SIZE } from "./prompt_share_page_constants";
import type { PromptRecord } from "./prompt_card";
import { useTranslation } from "../../contexts/locale_context";

type UsePromptAuthorProfileOptions = {
  toPromptRecords: (items: PromptData[]) => PromptRecord[];
};

// SNS風プロフィールモーダルの状態（プロフィール情報・投稿一覧・読み込み状態）を管理する
// Manages state for the SNS-style profile modal: profile info, post feed, and loading state
export function usePromptAuthorProfile({ toPromptRecords }: UsePromptAuthorProfileOptions) {
  const { t } = useTranslation();
  const [authorProfile, setAuthorProfile] = useState<PromptAuthorProfile | null>(null);
  const [authorProfilePrompts, setAuthorProfilePrompts] = useState<PromptRecord[]>([]);
  const [authorProfilePagination, setAuthorProfilePagination] = useState<PromptPagination | null>(null);
  const [isAuthorProfileLoading, setIsAuthorProfileLoading] = useState(false);
  const [isLoadingMoreAuthorPrompts, setIsLoadingMoreAuthorPrompts] = useState(false);
  const [authorProfileError, setAuthorProfileError] = useState<string | null>(null);
  // 非同期取得の完了時に、まだ同じユーザーを見ているかを確認するための参照
  // Tracks which author is being viewed, so a stale async response cannot overwrite a newer one
  const activeAuthorIdRef = useRef<number | null>(null);

  // モーダルを閉じる際に呼び出し、次回オープン時のちらつきを防ぐ
  // Called when the modal closes to prevent stale data from flashing on next open
  const resetAuthorProfile = useCallback(() => {
    activeAuthorIdRef.current = null;
    setAuthorProfile(null);
    setAuthorProfilePrompts([]);
    setAuthorProfilePagination(null);
    setIsAuthorProfileLoading(false);
    setIsLoadingMoreAuthorPrompts(false);
    setAuthorProfileError(null);
  }, []);

  // 指定した投稿者のプロフィールと投稿一覧を並行取得する
  // Fetches the given author's profile and post feed in parallel
  const loadAuthorProfile = useCallback(
    async (authorUserId: number) => {
      activeAuthorIdRef.current = authorUserId;
      setIsAuthorProfileLoading(true);
      setAuthorProfileError(null);
      setAuthorProfile(null);
      setAuthorProfilePrompts([]);
      setAuthorProfilePagination(null);
      try {
        const [profileData, feedData] = await Promise.all([
          fetchPromptAuthorProfile(authorUserId),
          fetchPromptList({ authorId: authorUserId, limit: AUTHOR_PROFILE_PROMPTS_PAGE_SIZE })
        ]);
        if (activeAuthorIdRef.current !== authorUserId) {
          return;
        }
        if (!profileData.user) {
          throw new Error(
            profileData.message || profileData.error || t("promptShare.authorProfileLoadFailed")
          );
        }
        setAuthorProfile(profileData.user);
        const records = Array.isArray(feedData.prompts) ? toPromptRecords(feedData.prompts) : [];
        setAuthorProfilePrompts(records);
        setAuthorProfilePagination(feedData.pagination || null);
      } catch (error) {
        if (activeAuthorIdRef.current !== authorUserId) {
          return;
        }
        setAuthorProfileError(error instanceof Error ? error.message : String(error));
      } finally {
        if (activeAuthorIdRef.current === authorUserId) {
          setIsAuthorProfileLoading(false);
        }
      }
    },
    [t, toPromptRecords]
  );

  // 表示中の投稿者の次ページを取得し、既存の一覧へ追記する
  // Fetches the next page for the currently viewed author and appends it to the list
  const loadMoreAuthorPrompts = useCallback(async () => {
    const authorUserId = activeAuthorIdRef.current;
    if (!authorUserId || !authorProfilePagination?.has_next || isLoadingMoreAuthorPrompts) {
      return;
    }
    setIsLoadingMoreAuthorPrompts(true);
    try {
      const data = await fetchPromptList({
        authorId: authorUserId,
        limit: AUTHOR_PROFILE_PROMPTS_PAGE_SIZE,
        cursor: authorProfilePagination.next_cursor || null
      });
      if (activeAuthorIdRef.current !== authorUserId) {
        return;
      }
      const records = Array.isArray(data.prompts) ? toPromptRecords(data.prompts) : [];
      setAuthorProfilePrompts((current) => [...current, ...records]);
      setAuthorProfilePagination(data.pagination || null);
    } catch (error) {
      if (activeAuthorIdRef.current === authorUserId) {
        setAuthorProfileError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      if (activeAuthorIdRef.current === authorUserId) {
        setIsLoadingMoreAuthorPrompts(false);
      }
    }
  }, [authorProfilePagination, isLoadingMoreAuthorPrompts, toPromptRecords]);

  return {
    authorProfile,
    authorProfileError,
    authorProfilePagination,
    authorProfilePrompts,
    isAuthorProfileLoading,
    isLoadingMoreAuthorPrompts,
    loadAuthorProfile,
    loadMoreAuthorPrompts,
    resetAuthorProfile
  };
}
