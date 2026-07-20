import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";

import { DEFAULT_MODEL, MAX_SETUP_INFO_LENGTH, MODEL_OPTIONS } from "../../lib/chat_page/constants";
import {
  readRestorableHomePageViewState,
  writeStoredHomePageViewState,
} from "../../lib/chat_page/storage";
import { STORAGE_KEYS } from "../../scripts/core/constants";

// SSR では useLayoutEffect が警告を出すため、サーバーでは useEffect に切り替える
// useLayoutEffect warns during SSR, so fall back to useEffect on the server
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export type HomePageViewState = "setup" | "launching" | "chat";

type ChatCoreHydrationWindow = Window & {
  __CHAT_CORE_APP_HYDRATED__?: boolean;
};

/**
 * 保存されたセットアップ情報を読み込む
 * Read the stored setup information
 */
function readStoredSetupInfo() {
  if (typeof window === "undefined") return "";

  try {
    // ローカルストレージからセットアップ情報を取得し、最大長で切り取る
    // Get setup info from local storage and truncate it to the max length
    return (localStorage.getItem(STORAGE_KEYS.setupInfoDraft) ?? "").slice(0, MAX_SETUP_INFO_LENGTH);
  } catch {
    return "";
  }
}

/**
 * 一時モードが有効になっているかどうかを読み込む
 * Read whether the temporary mode is enabled
 */
function readStoredTemporaryModeEnabled() {
  if (typeof window === "undefined") return false;

  try {
    // ローカルストレージから一時モードの設定を取得する
    // Get the temporary mode setting from local storage
    return localStorage.getItem(STORAGE_KEYS.temporaryModeEnabled) === "1";
  } catch {
    return false;
  }
}

function readInitialPageViewState(): HomePageViewState {
  if (typeof window === "undefined") return "setup";

  // During the first document hydration the server markup is the setup view.
  // Keep that initial state to avoid hydration mismatches; the head bootstrap
  // CSS hides setup when a chat restore is pending. After the app has hydrated,
  // client-side route returns can start directly from the stored view.
  if (!(window as ChatCoreHydrationWindow).__CHAT_CORE_APP_HYDRATED__) return "setup";

  return readRestorableHomePageViewState();
}

/**
 * ホームページのUI状態を管理するカスタムフック
 * Custom hook to manage the UI state of the home page
 */
export function useHomePageUiState() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [authResolved, setAuthResolved] = useState(false);
  // キャッシュ由来の認証状態を反映済みかどうか。サーバー確認を待たずに
  // ログイン/ユーザーアイコンを描画してよいかの判定に使う。
  // Whether the cached auth state has been applied. Used to decide if the
  // login button / user icon can render without waiting for server confirmation.
  const [authHintApplied, setAuthHintApplied] = useState(false);
  const [pageViewState, setRawPageViewState] = useState<HomePageViewState>(readInitialPageViewState);
  const [setupInfo, setSetupInfo] = useState("");
  const [temporaryModeEnabled, setTemporaryModeEnabled] = useState(false);
  const [storedSetupStateLoaded, setStoredSetupStateLoaded] = useState(false);

  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [chatHeaderModelMenuOpen, setChatHeaderModelMenuOpen] = useState(false);
  const [selectedModel, setSelectedModel] = useState(DEFAULT_MODEL);

  const modelSelectRef = useRef<HTMLDivElement | null>(null);
  const chatHeaderModelSelectRef = useRef<HTMLDivElement | null>(null);

  const setPageViewState = useCallback<Dispatch<SetStateAction<HomePageViewState>>>((nextState) => {
    if (typeof nextState !== "function") {
      writeStoredHomePageViewState(nextState);
      setRawPageViewState(nextState);
      return;
    }

    setRawPageViewState((previous) => {
      const resolved = nextState(previous);
      writeStoredHomePageViewState(resolved);
      return resolved;
    });
  }, []);

  // 選択されたモデルのラベルを取得する
  // Get the label of the selected model
  const selectedModelLabel = useMemo(() => {
    return MODEL_OPTIONS.find((option) => option.value === selectedModel)?.label ?? MODEL_OPTIONS[0]?.label ?? "";
  }, [selectedModel]);

  // 選択されたモデルの短いラベルを取得する
  // Get the short label of the selected model
  const selectedModelShortLabel = useMemo(() => {
    return MODEL_OPTIONS.find((option) => option.value === selectedModel)?.shortLabel ?? MODEL_OPTIONS[0]?.shortLabel ?? "";
  }, [selectedModel]);

  // 初回マウント時に保存された設定を読み込む。最初の描画（ペイント）前に
  // 反映しないと、チャット画面の復元時にセットアップ画面が一瞬表示される
  // ため、useEffect ではなく layout effect で同期的に復元する。
  // Load stored settings on initial mount. This must apply before the first
  // paint — with a plain useEffect the setup view flashes for one frame when
  // restoring the chat view — so restore synchronously in a layout effect.
  useIsomorphicLayoutEffect(() => {
    setSetupInfo(readStoredSetupInfo());
    setTemporaryModeEnabled(readStoredTemporaryModeEnabled());
    setRawPageViewState(readRestorableHomePageViewState());
    setStoredSetupStateLoaded(true);
  }, []);

  // 最後に表示していたトップページのビューを保存する
  // Save the last visible top-page view so reloads restore the same screen.
  useEffect(() => {
    if (!storedSetupStateLoaded) return;
    writeStoredHomePageViewState(pageViewState);
  }, [pageViewState, storedSetupStateLoaded]);

  // セットアップ情報の変更をローカルストレージに保存する
  // Save setup info changes to local storage
  useEffect(() => {
    if (!storedSetupStateLoaded) return;

    try {
      if (setupInfo.length > 0 && setupInfo.length <= MAX_SETUP_INFO_LENGTH) {
        localStorage.setItem(STORAGE_KEYS.setupInfoDraft, setupInfo);
      } else {
        localStorage.removeItem(STORAGE_KEYS.setupInfoDraft);
      }
    } catch {
      // ローカルストレージの失敗を無視する
      // ignore localStorage failures
    }
  }, [setupInfo, storedSetupStateLoaded]);

  // 一時モードの変更をローカルストレージに保存する
  // Save temporary mode changes to local storage
  useEffect(() => {
    if (!storedSetupStateLoaded) return;

    try {
      localStorage.setItem(STORAGE_KEYS.temporaryModeEnabled, temporaryModeEnabled ? "1" : "0");
    } catch {
      // ローカルストレージの失敗を無視する
      // ignore localStorage failures
    }
  }, [storedSetupStateLoaded, temporaryModeEnabled]);

  const isChatVisible = pageViewState !== "setup";
  const isSetupVisible = pageViewState !== "chat";
  const isChatLaunching = pageViewState === "launching";

  return {
    loggedIn,
    setLoggedIn,
    authResolved,
    setAuthResolved,
    authHintApplied,
    setAuthHintApplied,
    pageViewState,
    setPageViewState,
    isChatVisible,
    isSetupVisible,
    isChatLaunching,
    setupInfo,
    setSetupInfo,
    temporaryModeEnabled,
    setTemporaryModeEnabled,
    storedSetupStateLoaded,
    modelMenuOpen,
    setModelMenuOpen,
    chatHeaderModelMenuOpen,
    setChatHeaderModelMenuOpen,
    selectedModel,
    setSelectedModel,
    modelSelectRef,
    chatHeaderModelSelectRef,
    selectedModelLabel,
    selectedModelShortLabel,
  };
}
