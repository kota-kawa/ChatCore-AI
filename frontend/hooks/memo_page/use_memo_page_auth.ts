import { useEffect, useLayoutEffect, useState } from "react";

import { setLoggedInState } from "../../scripts/core/app_state";
import {
  readCachedAuthState,
  releaseAuthBootAttribute,
  writeCachedAuthState,
} from "../../scripts/core/auth_state_cache";
import { resilientFetch } from "../../scripts/core/resilient_fetch";

// メモ画面の認証状態。キャッシュ済みの状態を最初のペイント前に反映し、その後サーバーと同期する。
// Auth state for the memo page: apply the cached state before first paint, then sync with the server.
export function useMemoPageAuth() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  // 認証状態を表示に反映してよいか。キャッシュ反映済み、またはサーバー確認済みで true。
  // これが false の間は認証依存のUIをどちらも描画しない（誤った側を一瞬見せないため）。
  // Whether the auth state can drive the UI: true once the cache is applied or
  // the server has answered. While false, neither auth-dependent variant renders,
  // so the wrong one is never shown even for a frame.
  const [authUiReady, setAuthUiReady] = useState(false);

  // キャッシュ済みの認証状態を最初のペイント前に反映する。useEffect だと
  // 未ログインの初期stateが一度描画され、ログイン済みでもゲスト向けUIがちらつく。
  // 反映と同時にプリハイドレーション用のフラグを外し、以降はReactが表示を制御する。
  // Apply the cached auth state before the first paint. With a plain useEffect
  // the logged-out initial state gets painted once, flashing the guest UI at
  // signed-in users. Releasing the pre-hydration flag hands control to React.
  useLayoutEffect(() => {
    const cachedAuthState = readCachedAuthState();
    if (cachedAuthState !== null) {
      setIsLoggedIn(cachedAuthState);
      setLoggedInState(cachedAuthState);
      setAuthUiReady(true);
    }

    releaseAuthBootAttribute();
  }, []);

  // 認証状態の同期を行う副作用
  // Effect to synchronize the authentication state
  useEffect(() => {
    let cancelled = false;

    const syncAuthState = async () => {
      try {
        const res = await resilientFetch("/api/current_user", { credentials: "same-origin" });
        const data = res.ok ? await res.json() : { logged_in: false };
        const loggedIn = Boolean(data.logged_in);
        if (cancelled) return;
        setIsLoggedIn(loggedIn);
        setLoggedInState(loggedIn);
        writeCachedAuthState(loggedIn);
      } catch {
        if (cancelled) return;
        setIsLoggedIn(false);
        setLoggedInState(false);
      } finally {
        if (!cancelled) setAuthUiReady(true);
      }
    };
    void syncAuthState();

    return () => {
      cancelled = true;
    };
  }, []);

  return { isLoggedIn, authUiReady };
}
