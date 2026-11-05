// 共有チャットページ（pages/shared/[token].tsx）の「このチャットを続ける」ボタン。共有された会話を自分のルームへ複製して通常のチャット画面へ移る。
// "Continue this chat" button on the shared chat page (pages/shared/[token].tsx): copies the shared conversation into the viewer's own room and opens the regular chat view.
import { useCallback, useEffect, useState } from "react";

import { useTranslation } from "../../contexts/locale_context";
import { ContentImportButton } from "../ui/content_import_button";
import {
  useImportActionState,
  type UseImportActionStateResult,
} from "../../hooks/use_import_action";
import { createForkedRoomId, forkSharedChat, rememberForkedChatRoom } from "../../lib/shared_chat/fork_shared_chat";
import { resilientFetch } from "../../scripts/core/resilient_fetch";

type SharedChatContinueButtonProps = {
  token: string;
  /**
   * 共有ページのヘッダーとフッターが同じ状態を共有し、複製リクエストが 1 つだけ走るようにする。
   * Share-page header and footer can use one guard so only one fork request runs.
   */
  actionState?: UseImportActionStateResult;
};

// 共有チャットは読み取り専用のまま保ち、「続ける」では会話を自分のルームへ複製してから
// 通常のチャット画面に遷移する。複製先だけに書き込むので、共有元の履歴は変更されない。
// The shared chat stays read-only: "continue" copies the conversation into a room owned by the
// viewer and then opens the regular chat view, so the source conversation is never modified.
export function SharedChatContinueButton({ token, actionState }: SharedChatContinueButtonProps) {
  const { locale } = useTranslation();
  const english = locale === "en";
  const fallbackActionState = useImportActionState();
  const { isPending: isForking, run: runImport } = actionState ?? fallbackActionState;
  const [errorMessage, setErrorMessage] = useState("");
  // null = 認証状態の確認中。確認できるまでは補足文を出さない。
  // null means the auth state is still being resolved; no hint is shown until it is known.
  const [isLoggedIn, setIsLoggedIn] = useState<boolean | null>(null);

  // ログイン状態を確認する。未ログインの場合だけ、複製が保存されない旨を表示するために使う
  // Check the login state; it is used only to show the note that a guest's copy is not saved
  useEffect(() => {
    let cancelled = false;
    resilientFetch("/api/current_user", { credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok) return false;
        const data = (await response.json().catch(() => ({}))) as { logged_in?: unknown };
        return Boolean(data?.logged_in);
      })
      .then((loggedIn) => {
        if (!cancelled) setIsLoggedIn(loggedIn);
      })
      .catch(() => {
        if (!cancelled) setIsLoggedIn(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 共有チャットを複製し、作成したルームを記憶してから "/" へ遷移する。実行中の重複クリックは無視し、失敗時はエラー文を表示する
  // Fork the shared chat, remember the created room and navigate to "/"; repeated clicks while pending are ignored and failures show an error message
  const handleContinue = useCallback(async () => {
    if (isForking) return;
    setErrorMessage("");

    const fallbackErrorMessage = english
      ? "Could not continue this chat."
      : "このチャットを続けられませんでした。";

    try {
      await runImport(async () => {
        const forkedRoom = await forkSharedChat(token, createForkedRoomId(), fallbackErrorMessage);
        rememberForkedChatRoom(forkedRoom);
        window.location.assign("/");
      });
    } catch (error) {
      setErrorMessage(error instanceof Error && error.message ? error.message : fallbackErrorMessage);
    }
  }, [english, isForking, runImport, token]);

  return (
    <div className="shared-chat-continue">
      <ContentImportButton
        variant="labelled"
        className="shared-chat-continue__button cc-press"
        pending={isForking}
        label={english ? "Continue this chat" : "このチャットを続ける"}
        pendingLabel={english ? "Preparing your copy…" : "コピーを準備しています..."}
        iconClass="bi-chat-dots"
        onClick={() => {
          void handleContinue();
        }}
      />

      {/* 未ログインでも続きは話せるが、その会話は保存されない点を先に伝える。 */}
      {/* Guests can continue too; say up front that their copy will not be saved. */}
      {isLoggedIn === false ? (
        <p className="shared-chat-continue__hint">
          {english
            ? "You are not signed in, so the copy opens as a temporary chat that is not saved."
            : "未ログインのため、コピーは保存されない一時的なチャットとして開きます。"}
        </p>
      ) : null}

      {errorMessage ? (
        <p className="shared-chat-continue__error" role="alert">
          {errorMessage}
        </p>
      ) : null}
    </div>
  );
}
