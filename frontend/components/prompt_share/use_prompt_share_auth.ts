import { useEffect, useState } from "react";

import { setLoggedInState } from "../../scripts/core/app_state";
import { resilientFetch } from "../../scripts/core/resilient_fetch";
import {
  readCachedAuthState,
  writeCachedAuthState
} from "../../scripts/prompt_share/storage";

// 認証状態の管理。キャッシュから即座にUIを表示し、API確認後に最新の状態へ更新する
// Auth state management: shows UI immediately from cache, then syncs with the API
export function usePromptShareAuth() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [authUiReady, setAuthUiReady] = useState(false);

  useEffect(() => {
    const cachedAuthState = readCachedAuthState();
    if (cachedAuthState !== null) {
      setIsLoggedIn(cachedAuthState);
      setLoggedInState(cachedAuthState);
      setAuthUiReady(true);
    }

    let cancelled = false;
    // タイムアウト0でAPI呼び出しをマイクロタスクキューに遅延させ、キャッシュが先にレンダリングされるようにする
    // Defers the API call to the next tick so the cached state renders first
    const timerId = window.setTimeout(() => {
      void resilientFetch("/api/current_user", { credentials: "same-origin" })
        .then((res) => (res.ok ? res.json() : { logged_in: false }))
        .then((data: { logged_in?: boolean }) => {
          if (cancelled) {
            return;
          }
          const loggedIn = Boolean(data.logged_in);
          setIsLoggedIn(loggedIn);
          setLoggedInState(loggedIn);
          setAuthUiReady(true);
          writeCachedAuthState(loggedIn);
        })
        .catch((error) => {
          if (cancelled) {
            return;
          }
          console.error("Error checking login status:", error);
          setIsLoggedIn(false);
          setLoggedInState(false);
          setAuthUiReady(true);
        });
    }, 0);

    return () => {
      cancelled = true;
      window.clearTimeout(timerId);
    };
  }, []);

  return {
    authUiReady,
    isLoggedIn
  };
}
